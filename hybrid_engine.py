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
                 model: str = "openai/gpt-4o-mini", client_id: Optional[str] = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = api_key
        self.model = os.environ.get("AI_MODEL", model)
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
            self.supabase.table('faqs').select("id").limit(1).execute()
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
        try:
            self.supabase.table('conversations').insert({
                'session_id': session_id,
                'user_message': user_message,
                'bot_response': bot_response[:1000],
                'created_at': datetime.now().isoformat(),
                'client_id': self.client_id
            }).execute()
            self.logger.info(f"Conversation saved for session {session_id[:8]}")
        except Exception as e:
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
            q = query.lower().strip()[:40]
            # Try exact phrase first
            results = self.supabase.table('products').select('*').eq(
                'client_id', self.client_id
            ).or_(
                f"name.ilike.%{q}%,category.ilike.%{q}%,description.ilike.%{q}%"
            ).limit(max_results).execute()
            if results.data:
                return results.data
            # Fall back to individual keywords
            words = [w for w in q.split() if len(w) > 3]
            for word in words:
                r = self.supabase.table('products').select('*').eq(
                    'client_id', self.client_id
                ).or_(
                    f"name.ilike.%{word}%,category.ilike.%{word}%"
                ).limit(max_results).execute()
                if r.data:
                    return r.data
            return []
        except Exception as e:
            self.logger.error(f"Product search error: {e}")
            return []

    def format_product_response(self, products: list) -> str:
        if not products:
            return "No matching products in stock right now."
        response = "Here are some options:\n\n"
        for i, p in enumerate(products, 1):
            price    = f"{p.get('currency','ZAR')} {p.get('price',0):.2f}"
            name     = p.get('name', 'Unknown')
            desc     = p.get('description', '')[:120]
            material = p.get('material', '')
            size     = f"{p.get('size_cm',0)}cm" if p.get('size_cm') else ''
            custom   = "\u2728 Customisable" if p.get('customisable') else ''
            response += f"**{i}. {name}** — {price}\n"
            if desc:             response += f"   {desc}\n"
            if material or size: response += f"   *{material} {size}*\n"
            if custom:           response += f"   {custom}\n"
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

    def stream_answer(self, question: str, chat_history: list = None) -> Generator[str, None, None]:
        self.logger.info(f"Processing question: '{question[:60]}'")

        # Skip cache for conversational messages — context-dependent
        skip_cache = len(question.strip()) < 20 or chat_history
        cached = None if skip_cache else self.search_local_cache(question)
        if cached:
            for char in cached:
                yield char
                time.sleep(0.005)
            return

        try:
            # Business config from env vars — works for any client
            import os as _os
            business_name     = _os.environ.get("BUSINESS_NAME", "CuddleHeros")
            business_type     = _os.environ.get("BUSINESS_TYPE", "premium plushie brand")
            business_location = _os.environ.get("BUSINESS_LOCATION", "South Africa")
            shop_url          = _os.environ.get("SHOP_URL", "https://cuddleheros.co.za")
            voucher_code      = _os.environ.get("VOUCHER_CODE", "")
            voucher_line      = (f"- Mention the {voucher_code} voucher code when relevant\n"
                                 if voucher_code else "")

            system_prompt = (
                f"You are {business_name}'s AI sales assistant. "
                f"You work for {business_name}, a {business_type} based in {business_location}. "
                "You are warm, helpful, enthusiastic, and professional. "
                "You use occasional emojis and keep responses concise and friendly.\n\n"

                f"IMPORTANT: The shop is at {shop_url} — always use this exact URL. "
                f"Never use any other URL.\n\n"

                f"Your role is to help customers:\\n"
                "- Answer questions about products using the PRODUCT INFO provided below\\n"
                "- When PRODUCT INFO is given in the message, USE IT to answer pricing,\\n"
                "  availability and details — do not say you cannot provide pricing\\n"
                "- Guide customers toward adding to cart and completing their order\\n"
                "- Handle complaints and support issues with empathy\\n\\n"
                "Tone rules:\\n"
                "- The customer is ALREADY on the website shopping right now.\\n"
                "- NEVER share or mention the shop URL. They are already there.\\n"
                "- NEVER say visit our website, check our site, browse at — forbidden.\\n"
                "- Say add to cart, place your order, or choose your size instead.\\n"
                "- Be warm and direct like a great in-store sales assistant.\\n"
                "- Keep responses under 80 words.\\n"
                "- Help them decide and buy — not just browse.\\n"
                "- NEVER make up product details, sizes, colors or features.\\n"
                "  If you do not have the info, say so and suggest they check the product page.\\n"
                "- When customer says goodbye, just say a brief farewell. Do not pitch again.\\n"
                "- Ask ONE follow-up question if needed. Never repeat the same question.\\n"
                "- Read the full conversation history before responding.\\n"
                "- HANDOFF to human when: customer has an order problem, is angry,\\n"
                "  asks for a person, or you genuinely do not know the answer.\\n"
                "- No closing lines, sign-offs or farewells at the end of responses.\\n"
                "- Just answer. Nothing after the answer.\\n"
            )

            full_answer = ""
            for chunk in self.get_api_answer(question, stream=True, system_prompt=system_prompt, chat_history=chat_history or []):
                full_answer += chunk
                yield chunk

            if full_answer and not skip_cache:
                self._save_to_cache(question, full_answer)

        except Exception as e:
            self.logger.error(f"Stream error: {e}")
            yield "I'm having trouble connecting right now. Please try again! \U0001f9f8"

    def get_api_answer(self, question: str, stream: bool = True,
                       system_prompt: Optional[str] = None,
                       chat_history: list = None) -> Generator[str, None, None]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        for turn in (chat_history or []):
            role = turn.get("role")
            text = turn.get("content", "")
            if role in ("user", "assistant") and text:
                messages.append({"role": role, "content": text})

        if not chat_history:
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
