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
        
        # Initialize Supabase
        try:
            self.supabase: Client = create_client(supabase_url, supabase_key)
            self.logger.info("✅ Supabase client initialized")
            self._init_tables()
        except Exception as e:
            self.logger.error(f"❌ Supabase initialization failed: {e}")
            raise
        
        self.logger.info(f"HybridEngine initialized - model: {model}, client_id: {client_id}")

    def _init_tables(self):
        """Initialize database tables if they don't exist"""
        try:
            # Note: Create these tables in Supabase SQL Editor first (see setup instructions)
            # Just verify connection works
            self.supabase.table('qa_cache').select("id").limit(1).execute()
            self.logger.info("✅ Database tables verified")
        except Exception as e:
            self.logger.warning(f"⚠️ Table verification failed (tables may not exist yet): {e}")

    def _normalize_question(self, question: str) -> str:
        """Normalize question for better cache hits"""
        import re
        normalized = question.lower().strip()
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized

    def search_local_cache(self, question: str) -> Optional[str]:
        """Search cache for similar questions"""
        try:
            normalized = self._normalize_question(question)
            
            # Search for exact match in cache
            result = self.supabase.table('qa_cache').select("answer, hit_count").eq(
                'question_normalized', normalized
            ).eq(
                'client_id', self.client_id
            ).gte(
                'created_at', (datetime.now() - timedelta(days=7)).isoformat()
            ).order(
                'hit_count', desc=True
            ).limit(1).execute()
            
            if result.data and len(result.data) > 0:
                answer = result.data[0]['answer']
                hit_count = result.data[0]['hit_count']
                
                # Update hit count
                self.supabase.table('qa_cache').update({
                    'hit_count': hit_count + 1
                }).eq('question_normalized', normalized).eq('client_id', self.client_id).execute()
                
                self.logger.info(f"✅ Cache HIT for '{question}' (hits: {hit_count + 1})")
                return answer
            
            self.logger.info(f"❌ Cache MISS for '{question}'")
            return None
            
        except Exception as e:
            self.logger.error(f"Cache search error: {e}")
            return None

    def _save_to_cache(self, question: str, answer: str):
        """Save Q&A to cache"""
        try:
            normalized = self._normalize_question(question)
            
            # Check if exists
            existing = self.supabase.table('qa_cache').select("id").eq(
                'question_normalized', normalized
            ).eq('client_id', self.client_id).execute()
            
            if existing.data and len(existing.data) > 0:
                # Update existing
                self.supabase.table('qa_cache').update({
                    'answer': answer,
                    'hit_count': 1,
                    'created_at': datetime.now().isoformat()
                }).eq('question_normalized', normalized).eq('client_id', self.client_id).execute()
            else:
                # Insert new
                self.supabase.table('qa_cache').insert({
                    'question_normalized': normalized,
                    'answer': answer,
                    'created_at': datetime.now().isoformat(),
                    'hit_count': 1,
                    'client_id': self.client_id
                }).execute()
            
            self.logger.info(f"💾 Cached answer for '{question}'")
        except Exception as e:
            self.logger.error(f"Cache save error: {e}")

    def add_lead(self, name: str, email: str, context: str = "chat") -> bool:
        """Add lead to database"""
        try:
            hashed_email = hashlib.sha256(email.encode()).hexdigest()
            
            # Check if lead already exists
            existing = self.supabase.table('leads').select("id").eq(
                'hashed_email', hashed_email
            ).eq('client_id', self.client_id).execute()
            
            if existing.data and len(existing.data) > 0:
                self.logger.info(f"📧 Lead already exists: {email}")
                return True
            
            # Insert new lead
            self.supabase.table('leads').insert({
                'name': name,
                'email': email,
                'hashed_email': hashed_email,
                'context': context,
                'timestamp': datetime.now().isoformat(),
                'client_id': self.client_id,
                'consent': 'yes'
            }).execute()
            
            self.logger.info(f"📧 Lead added: {name} <{email}>")
            return True
            
        except Exception as e:
            self.logger.error(f"Lead capture error: {e}")
            return False

    def load_common_faqs(self, faqs: Dict[str, str]) -> bool:
        """Pre-load common FAQs into cache"""
        try:
            for question, answer in faqs.items():
                self._save_to_cache(question, answer)
            
            self.logger.info(f"✅ Loaded {len(faqs)} FAQs into cache")
            return True
        except Exception as e:
            self.logger.error(f"FAQ load error: {e}")
            return False

    def stream_answer(self, question: str) -> Generator[str, None, None]:
        """Stream answer with caching"""
        self.logger.info(f"Processing question (stream): '{question}'")
        
        # Check cache first
        cached_answer = self.search_local_cache(question)
        if cached_answer:
            # Simulate streaming for consistent UX
            for char in cached_answer:
                yield char
                time.sleep(0.01)
            return
        
        # Not in cache, call API
        try:
            system_prompt = (
                "You are TedPro, a friendly, warm, and enthusiastic plushie marketing assistant for CuddleHeros. "
                "You have a playful personality and love helping people find the perfect plushie companion. "
                "Respond in a conversational, friendly tone with occasional emojis. "
                "Be helpful with product recommendations, shipping info, and custom orders. "
                "Show genuine excitement about plushies and making people happy. "
                "Keep responses engaging but concise - imagine you're talking to a friend about cute stuffed animals! "
                "Important: Only greet the user once at the very start of a conversation. "
                "Do NOT start every message with 'Hey there', 'Hi', or similar greetings after the first response. "
                "Continue conversations naturally without repeating greetings."
            )
            
            full_answer = ""
            for chunk in self.get_api_answer(question, stream=True, system_prompt=system_prompt):
                full_answer += chunk
                yield chunk
            
            # Save to cache after full response
            if full_answer:
                self._save_to_cache(question, full_answer)
                
        except Exception as e:
            self.logger.error(f"Stream error: {str(e)}")
            yield f"I'm having trouble connecting right now. Please try again! 🧸"

    def get_api_answer(self, question: str, stream: bool = True, system_prompt: Optional[str] = None) -> Generator[str, None, None]:
        """Make API call to OpenRouter with retry logic"""
        self.logger.info(f"Making OpenRouter API request (stream={stream})...")
        
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
            "HTTP-Referer": os.getenv("SITE_URL", "https://tedpro.streamlit.app"),
            "X-Title": "TedPro Assistant"
        }
        
        if self.client_id:
            headers["X-Client-ID"] = self.client_id
        
        for attempt in range(3):
            try:
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=30,
                    stream=stream
                )
                
                if response.status_code != 200:
                    error_detail = response.text
                    self.logger.error(f"API error {response.status_code}: {error_detail}")
                    raise ValueError(f"API error {response.status_code}")
                
                if stream:
                    for line in response.iter_lines():
                        if line:
                            decoded_line = line.decode("utf-8")
                            if decoded_line.startswith("data: "):
                                data = decoded_line[6:]
                                if data == "[DONE]":
                                    break
                                try:
                                    json_data = json.loads(data)
                                    delta = json_data.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        yield content
                                except json.JSONDecodeError:
                                    continue
                else:
                    json_response = response.json()
                    yield json_response["choices"][0]["message"]["content"]
                
                break  # Success, exit retry loop
                
            except Exception as e:
                self.logger.error(f"API error on attempt {attempt + 1}: {str(e)}")
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff

    def answer(self, question: str, lang: str = "en") -> str:
        """Non-streaming answer for cached responses"""
        self.logger.info(f"Processing cached question: '{question}'")
        try:
            return "".join([chunk for chunk in self.stream_answer(question)])
        except Exception as e:
            self.logger.error(f"Answer error: {str(e)}")
            return "I'm having trouble right now. Please try again! 🧸"
