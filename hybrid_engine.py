import logging
import os
import json
import time
import requests
import hashlib
from typing import Generator, Optional, Dict
from datetime import datetime, timedelta
from supabase import create_client, Client

class HybridEngine:
    def __init__(self, api_key: str, supabase_url: str, supabase_key: str,
                 model: str = "openai/gpt-3.5-turbo", client_id: Optional[str] = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = api_key
        self.model = model
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        self.client_id = client_id or "default"

        try:
            self.supabase: Client = create_client(supabase_url, supabase_key)
            self.logger.info("Supabase client initialized")
            self._init_tables()
        except Exception as e:
            self.logger.error(f"Supabase initialization failed: {e}")
            raise

    def _init_tables(self):
        try:
            self.supabase.table('qa_cache').select("id").limit(1).execute()
            self.logger.info("Database tables verified")
        except Exception as e:
            self.logger.warning(f"Table verification failed: {e}")

    def _normalize_question(self, question: str) -> str:
        import re
        normalized = question.lower().strip()
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized

    def search_local_cache(self, question: str) -> Optional[str]:
        try:
            normalized = self._normalize_question(question)
            result = self.supabase.table('qa_cache').select("answer, hit_count").eq(
                'question_normalized', normalized
            ).eq('client_id', self.client_id).gte(
                'created_at', (datetime.now() - timedelta(days=7)).isoformat()
            ).order('hit_count', desc=True).limit(1).execute()

            if result.data:
                hit_count = result.data[0]['hit_count']
                self.supabase.table('qa_cache').update({
                    'hit_count': hit_count + 1
                }).eq('question_normalized', normalized).eq('client_id', self.client_id).execute()
                self.logger.info(f"Cache HIT for '{question}'")
                return result.data[0]['answer']

            self.logger.info(f"Cache MISS for '{question}'")
            return None
        except Exception as e:
            self.logger.error(f"Cache search error: {e}")
            return None

    def _save_to_cache(self, question: str, answer: str):
        try:
            normalized = self._normalize_question(question)
            existing = self.supabase.table('qa_cache').select("id").eq(
                'question_normalized', normalized
            ).eq('client_id', self.client_id).execute()

            if existing.data:
                self.supabase.table('qa_cache').update({
                    'answer': answer, 'hit_count': 1,
                    'created_at': datetime.now().isoformat()
                }).eq('question_normalized', normalized).eq('client_id', self.client_id).execute()
            else:
                self.supabase.table('qa_cache').insert({
                    'question_normalized': normalized,
                    'answer': answer,
                    'created_at': datetime.now().isoformat(),
                    'hit_count': 1,
                    'client_id': self.client_id
                }).execute()
        except Exception as e:
            self.logger.error(f"Cache save error: {e}")

    def save_conversation(self, session_id: str, user_message: str, bot_response: str):
        """Save a single Q&A pair for analytics."""
        try:
            self.supabase.table('conversations').insert({
                'session_id': session_id,
                'user_message': user_message,
                'bot_response': bot_response[:1000],   # trim very long replies
                'created_at': datetime.now().isoformat(),
                'client_id': self.client_id
            }).execute()
            self.logger.info(f"Conversation saved for session {session_id[:8]}")
        except Exception as e:
            # Non-critical — log and continue, never crash the chat
            self.logger.error(f"Conversation save error: {e}")

    def add_lead(self, name: str, email: str, context: str = "chat") -> bool:
        try:
            hashed_email = hashlib.sha256(email.encode()).hexdigest()
            existing = self.supabase.table('leads').select("id").eq(
                'hashed_email', hashed_email
            ).eq('client_id', self.client_id).execute()

            if existing.data:
                self.logger.info(f"Lead already exists: {email}")
                return True

            self.supabase.table('leads').insert({
                'name': name,
                'email': email,
                'hashed_email': hashed_email,
                'context': context,
                'timestamp': datetime.now().isoformat(),
                'client_id': self.client_id,
                'consent': 'yes'
            }).execute()
            self.logger.info(f"Lead added: {name} <{email}>")
            return True
        except Exception as e:
            self.logger.error(f"Lead capture error: {e}")
            return False

    def search_products(self, query: str, max_results: int = 5) -> list:
        try:
            query = query.lower().strip()
            results = self.supabase.table('products').select('*').eq(
                'client_id', self.client_id
            ).or_(
                f"name.ilike.%{query}%,category.ilike.%{query}%,description.ilike.%{query}%"
            ).eq('in_stock', True).limit(max_results).execute()
            return results.data if results.data else []
        except Exception as e:
            self.logger.error(f"Product search error: {e}")
            return []

    def format_product_response(self, products: list) -> str:
        if not products:
            return "No matching products in stock right now."
        response = "Here are some options:\n\n"
        for i, p in enumerate(products, 1):
            price   = f"{p.get('currency','ZAR')} {p.get('price',0):.2f}"
            name    = p.get('name', 'Unknown')
            desc    = p.get('description', '')[:100]
            material = p.get('material', '')
            size    = f"{p.get('size_cm',0)}cm" if p.get('size_cm') else ''
            custom  = "\u2728 Customisable" if p.get('customisable') else ''
            response += f"**{i}. {name}** — {price}\n"
            if desc:     response += f"   {desc}\n"
            if material or size: response += f"   *{material} {size}*\n"
            if custom:   response += f"   {custom}\n"
            response += "\n"
        return response

    def load_common_faqs(self, faqs: Dict[str, str]) -> bool:
        try:
            for question, answer in faqs.items():
                self._save_to_cache(question, answer)
            self.logger.info(f"Loaded {len(faqs)} FAQs into cache")
            return True
        except Exception as e:
            self.logger.error(f"FAQ load error: {e}")
            return False

    def stream_answer(self, question: str) -> Generator[str, None, None]:
        self.logger.info(f"Processing question: '{question[:60]}'")

        cached = self.search_local_cache(question)
        if cached:
            for char in cached:
                yield char
                time.sleep(0.005)
            return

        try:
            # ----------------------------------------------------------------
            # Teddy's personality + soft topic guardrail
            # ----------------------------------------------------------------
            system_prompt = (
                "You are Teddy, a warm, playful, and knowledgeable marketing assistant for CuddleHeros — "
                "a premium plushie brand. Your personality is friendly, enthusiastic, and a little cuddly. "
                "You use occasional emojis and keep responses concise but helpful.\n\n"

                "Your main topics: CuddleHeros plushie products, pricing, shipping, custom orders, "
                "materials, safety, gifting ideas, and growing a plushie business.\n\n"

                "If someone asks something off-topic (unrelated to plushies, CuddleHeros, or gifting), "
                "respond warmly and briefly, then gently steer back. For example: "
                "'Ha, great question! I'm mostly a plushie expert, but here's what I know... "
                "Speaking of which, can I help you find the perfect plushie? \U0001f9f8' "
                "Never refuse rudely or say 'I can only talk about plushies.' Just redirect naturally.\n\n"

                "Important: Only greet the user once at the very start. "
                "Do not repeat 'Hi', 'Hey there', or similar greetings after the first message. "
                "Continue conversations naturally."
            )

            full_answer = ""
            for chunk in self.get_api_answer(question, stream=True, system_prompt=system_prompt):
                full_answer += chunk
                yield chunk

            if full_answer:
                self._save_to_cache(question, full_answer)

        except Exception as e:
            self.logger.error(f"Stream error: {e}")
            yield "I'm having trouble connecting right now. Please try again! \U0001f9f8"

    def get_api_answer(self, question: str, stream: bool = True,
                       system_prompt: Optional[str] = None) -> Generator[str, None, None]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": question})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": 0.7,
            "max_tokens": 500
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv("SITE_URL", "https://ted-pro.onrender.com"),
            "X-Title": "TedPro Assistant"
        }

        for attempt in range(3):
            try:
                response = requests.post(
                    self.api_url, headers=headers, json=payload,
                    timeout=30, stream=stream
                )
                if response.status_code != 200:
                    raise ValueError(f"API error {response.status_code}: {response.text}")

                if stream:
                    for line in response.iter_lines():
                        if line:
                            decoded = line.decode("utf-8")
                            if decoded.startswith("data: "):
                                data = decoded[6:]
                                if data == "[DONE]":
                                    break
                                try:
                                    json_data = json.loads(data)
                                    content = json_data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                    if content:
                                        yield content
                                except json.JSONDecodeError:
                                    continue
                else:
                    yield response.json()["choices"][0]["message"]["content"]
                break

            except Exception as e:
                self.logger.error(f"API attempt {attempt + 1} failed: {e}")
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)

    def answer(self, question: str) -> str:
        try:
            return "".join(self.stream_answer(question))
        except Exception as e:
            self.logger.error(f"Answer error: {e}")
            return "I'm having trouble right now. Please try again! \U0001f9f8"
