import os
import json
from typing import List, Dict, Optional
import requests
from rapidfuzz import fuzz, process
from tenacity import retry, stop_after_attempt, wait_exponential

# -------- Secrets Loader (env first, then Streamlit) --------
def get_secret(name: str, default: Optional[str] = None):
    # 1) Environment variables (works with GitHub/Streamlit secrets injection)
    v = os.getenv(name)
    if v:
        return v
    # 2) Streamlit secrets (only available when running in Streamlit Cloud)
    try:
        import streamlit as st  # lazy import
        if "secrets" in dir(st) and name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return default

# -------- FAQ Loader & Matcher --------
def load_faqs() -> List[Dict[str, str]]:
    def _read(fp: str) -> List[Dict[str, str]]:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return []
    base = _read("faqs.json")
    client = _read("client_faq.json")
    # Merge: client entries first (override vibe), then base
    merged = client + base
    # Deduplicate by normalized question text
    seen = set()
    deduped = []
    for item in merged:
        q = item.get("question", "").strip().lower()
        if q and q not in seen:
            seen.add(q)
            deduped.append(item)
    return deduped

def fuzzy_answer(user_text: str, faqs: List[Dict[str, str]], threshold: int = 80) -> Optional[str]:
    if not user_text or not faqs:
        return None
    questions = [f["question"] for f in faqs if "question" in f and "answer" in f]
    if not questions:
        return None
    match, score, idx = process.extractOne(
        user_text,
        questions,
        scorer=fuzz.token_set_ratio
    )
    if score >= threshold:
        return faqs[idx]["answer"]
    return None

# -------- OpenRouter (DeepSeek/others) Chat Completions --------
class HybridEngine:
    """
    Hybrid FAQ → LLM fallback engine.
    - 1) Try local fuzzy FAQ
    - 2) If low confidence, call OpenRouter (DeepSeek etc.)
    """
    def __init__(self,
                 api_key: str,
                 model_name: str = "deepseek/deepseek-r1:free",
                 temperature: float = 0.7,
                 system_prompt: Optional[str] = None,
                 max_history: int = 10):
        self.api_key = api_key or get_secret("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("Missing OPENROUTER_API_KEY")
        self.model_name = model_name
        self.temperature = float(temperature)
        self.max_history = max_history
        self.faqs = load_faqs()
        self.system_prompt = system_prompt or (
            "You are Teddy, a warm, caring plush bear representing Cuddleheroes. "
            "Be supportive, concise, and subtly sales-oriented. Guide users to explore "
            "or purchase plushies, discuss shipping/returns/materials/customization, "
            "and bring conversation back to plushies if it drifts."
        )
        self.history: List[Dict[str, str]] = []  # {'role': 'user'|'assistant'|'system', 'content': '...'}

    def _clip_history(self):
        # Keep last 10 user+assistant messages; keep system at the top
        non_sys = [m for m in self.history if m["role"] != "system"]
        if len(non_sys) > self.max_history:
            non_sys = non_sys[-self.max_history:]
        self.history = [{"role": "system", "content": self.system_prompt}] + non_sys

    def add_to_history(self, role: str, content: str):
        if not self.history or self.history[0].get("role") != "system":
            self.history.insert(0, {"role": "system", "content": self.system_prompt})
        self.history.append({"role": role, "content": content})
        self._clip_history()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.6, min=0.5, max=4))
    def _call_openrouter(self, prompt: str) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # Optional but nice:
            "HTTP-Referer": "https://cuddleheroes.example",  # replace if you want
            "X-Title": "Ted Pro"
        }
        messages = [{"role": "system", "content": self.system_prompt}] + \
                   [m for m in self.history if m["role"] != "system"] + \
                   [{"role": "user", "content": prompt}]
        payload = {
            "model": self.model_name,
            "temperature": self.temperature,
            "messages": messages,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        # OpenRouter returns choices similar to OpenAI-style
        return data["choices"][0]["message"]["content"].strip()

    def answer(self, user_text: str) -> str:
        # 1) Try fuzzy FAQ
        faq = fuzzy_answer(user_text, self.faqs, threshold=82)
        if faq:
            return faq

        # 2) LLM fallback
        try:
            out = self._call_openrouter(user_text)
            return out
        except Exception as e:
            # Fail-safe message (never crash UI)
            return (
                "I’m here to help with our plushies! I couldn’t reach the AI right now. "
                "Could you rephrase your question about pricing, shipping, or customization? "
                f"(tech note: {type(e).__name__})"
            )
