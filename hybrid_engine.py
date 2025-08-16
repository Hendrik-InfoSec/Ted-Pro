import os
import json
from typing import List, Dict, Optional, Tuple
import requests
from rapidfuzz import fuzz, process
from tenacity import retry, stop_after_attempt, wait_exponential

# -------- Secrets Loader (env first, then Streamlit) --------
def get_secret(name: str, default: Optional[str] = None):
    v = os.getenv(name)
    if v:
        return v
    try:
        import streamlit as st  # lazy import
        if "secrets" in dir(st) and name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return default

# -------- FAQ Loader --------
def load_faqs() -> List[Dict[str, str]]:
    def _read(fp: str) -> List[Dict[str, str]]:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return []
    base = _read("faqs.json")
    client = _read("client_faq.json")
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

# -------- Fuzzy Booster --------
# domain keywords & synonyms we care about (shipping, returns, pricing, materials, gifts, sizes, custom)
DOMAIN_KEYWORDS = {
    "shipping": {"shipping", "delivery", "ship", "postage", "courier", "tracking"},
    "returns": {"return", "refund", "exchange", "warranty"},
    "pricing": {"price", "cost", "how much", "fees", "expensive", "cheap"},
    "materials": {"material", "fabric", "cotton", "polyester", "minky", "hypoallergenic", "safe"},
    "gifts": {"gift", "present", "wrap", "wrapping", "note"},
    "size": {"size", "sizing", "dimensions", "small", "medium", "large", "jumbo"},
    "custom": {"custom", "customize", "personalize", "embroidery", "bespoke"}
}

def _normalize_text(s: str) -> str:
    return " ".join(s.lower().strip().split())

def _keyword_overlap_bonus(user_text: str, q_text: str) -> int:
    """
    Adds a small bonus if important domain keywords overlap between the user query and the FAQ question.
    Bonus is modest (<= 12) to avoid overpowering the baseline similarity.
    """
    user = _normalize_text(user_text)
    ques = _normalize_text(q_text)

    bonus = 0
    for bucket in DOMAIN_KEYWORDS.values():
        if any(k in user for k in bucket) and any(k in ques for k in bucket):
            bonus += 4  # small additive bonus per matched topic
            if bonus >= 12:
                break
    return bonus

def boosted_best_match(user_text: str, questions: List[str]) -> Tuple[Optional[int], int]:
    """
    Compute a boosted score for each FAQ question and return (best_index, best_score).
    Base: token_set_ratio; Boost: keyword overlap.
    """
    best_idx, best_score = None, -1
    for i, q in enumerate(questions):
        base = fuzz.token_set_ratio(user_text, q)
        bonus = _keyword_overlap_bonus(user_text, q)
        score = min(100, base + bonus)  # cap at 100
        if score > best_score:
            best_idx, best_score = i, score
    return best_idx, best_score

def fuzzy_answer(user_text: str, faqs: List[Dict[str, str]], threshold: int = 82) -> Optional[str]:
    if not user_text or not faqs:
        return None
    pairs = [(f.get("question", ""), f.get("answer", "")) for f in faqs if f.get("question") and f.get("answer")]
    if not pairs:
        return None
    questions = [q for q, _ in pairs]
    idx, score = boosted_best_match(user_text, questions)
    if idx is not None and score >= threshold:
        return pairs[idx][1]
    return None

# -------- Order Tracking Intent (prototype) --------
def is_tracking_intent(text: str) -> bool:
    t = _normalize_text(text)
    # lightweight detection; can be replaced with classifier later
    triggers = ("track", "tracking", "where is", "status", "order")
    return any(k in t for k in triggers)

def extract_order_id(text: str) -> Optional[str]:
    # naive extraction: find a 4–10 digit-ish token
    import re
    m = re.search(r"(?:order\s*#?\s*)?([A-Za-z0-9]{4,12})", text, re.IGNORECASE)
    if not m:
        return None
    return m.group(1)

# -------- OpenRouter (DeepSeek/others) Chat Completions --------
class HybridEngine:
    """
    Hybrid router:
    1) Order-tracking prototype (if detected)
    2) Fuzzy FAQ with boosted domain matching
    3) LLM fallback via OpenRouter
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
        self.history: List[Dict[str, str]] = []

    def _clip_history(self):
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
            "HTTP-Referer": "https://cuddleheroes.example",
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
        return data["choices"][0]["message"]["content"].strip()

    # --- Order tracking mock hook (via api_integrations) ---
    def _try_order_tracking(self, text: str) -> Optional[str]:
        if not is_tracking_intent(text):
            return None
        oid = extract_order_id(text)
        if not oid:
            return ("I can help check your order status! Please share your order number "
                    "(e.g., ORDER1234) and I’ll look it up for you.")
        try:
            from api_integrations import get_order_status
        except Exception:
            return None
        status = get_order_status(oid)
        if not status:
            return f"I couldn’t find order **{oid}**. Could you confirm the number or the email used?"
        # friendly formatting
        parts = [f"**Order {oid}** status: {status['status']}"]
        if status.get("last_update"):
            parts.append(f"Last update: {status['last_update']}")
        if status.get("eta"):
            parts.append(f"ETA: {status['eta']}")
        return " • ".join(parts)

    def answer(self, user_text: str) -> str:
        # 1) Order tracking branch
        tracking = self._try_order_tracking(user_text)
        if tracking:
            return tracking

        # 2) Local FAQs with boosted fuzzy
        faq = fuzzy_answer(user_text, self.faqs, threshold=82)
        if faq:
            return faq

        # 3) LLM fallback
        try:
            out = self._call_openrouter(user_text)
            return out
        except Exception as e:
            return (
                "I’m here to help with our plushies! I couldn’t reach the AI right now. "
                "Could you rephrase your question about pricing, shipping, or customization? "
                f"(tech note: {type(e).__name__})"
            )
