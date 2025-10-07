import json
import os
from pathlib import Path
import sqlite3
import requests
import logging
from typing import Dict, List, Optional, Generator
import hashlib
import time
from datetime import datetime
import random

class HybridEngine:
    def __init__(self, api_key: str, client_id: str):
        self.api_key = api_key
        self.client_id = client_id
        # Use /tmp directory for Streamlit Cloud compatibility
        self.client_path = Path("/tmp") / client_id
        self.client_path.mkdir(parents=True, exist_ok=True)
        self.knowledge_base = self.load_knowledge_base()
        self.conversation_history: List[Dict[str, str]] = []
        self.logger = logging.getLogger("HybridEngine")
        self.session = requests.Session()  # Persistent session for better performance
        self.logger.info(f"🔧 HybridEngine initialized with API key: {bool(api_key)}")
        
    def load_knowledge_base(self) -> Dict:
        """Load FAQ and knowledge base"""
        knowledge_path = self.client_path / "knowledge" / "faq.json"
        if knowledge_path.exists():
            with open(knowledge_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"faqs": [], "products": []}
    
    def save_knowledge_base(self):
        """Save updated knowledge base"""
        knowledge_path = self.client_path / "knowledge" / "faq.json"
        knowledge_path.parent.mkdir(parents=True, exist_ok=True)
        with open(knowledge_path, 'w', encoding='utf-8') as f:
            json.dump(self.knowledge_base, f, indent=2)
    
    def answer(self, question: str) -> str:
        """Generate answer using hybrid approach - ACTUALLY CALLS OPENROUTER (non-streaming)"""
        self.logger.info(f"🔍 Processing question (non-stream): '{question}'")
        start_time = time.time()
        
        try:
            # First try local knowledge base
            local_answer = self.search_local_knowledge(question)
            if local_answer:
                self.logger.info("✅ Using local knowledge base answer")
                return local_answer
            
            self.logger.info("🌐 No local match, calling OpenRouter API...")
            
            # ACTUAL API CALL to OpenRouter (non-streaming)
            api_response = self.get_api_answer(question, stream=False)
            
            response_time = time.time() - start_time
            self.logger.info(f"✅ OpenRouter API response received in {response_time:.2f}s")
            
            return api_response
                
        except Exception as e:
            response_time = time.time() - start_time
            self.logger.error(f"❌ Error after {response_time:.2f}s: {str(e)}")
            return self.get_fallback_answer(question)
    
    def stream_answer(self, question: str) -> Generator[str, None, None]:
        """Stream answer using hybrid approach - ACTUALLY CALLS OPENROUTER (streaming)"""
        self.logger.info(f"🔍 Processing question (stream): '{question}'")
        start_time = time.time()
        
        try:
            # First try local knowledge base
            local_answer = self.search_local_knowledge(question)
            if local_answer:
                self.logger.info("✅ Using local knowledge base answer (streaming as single chunk)")
                yield local_answer
                return
            
            self.logger.info("🌐 No local match, streaming from OpenRouter API...")
            
            # ACTUAL API CALL to OpenRouter (streaming)
            for chunk in self.get_api_answer(question, stream=True):
                yield chunk
            
            response_time = time.time() - start_time
            self.logger.info(f"✅ OpenRouter API stream completed in {response_time:.2f}s")
                
        except Exception as e:
            response_time = time.time() - start_time
            self.logger.error(f"❌ Stream error after {response_time:.2f}s: {str(e)}")
            yield self.get_fallback_answer(question)
    
    def search_local_knowledge(self, question: str) -> Optional[str]:
        """Search local FAQ and knowledge base"""
        question_lower = question.lower()
        
        # Check FAQs
        for faq in self.knowledge_base.get("faqs", []):
            if any(keyword in question_lower for keyword in faq.get("keywords", [])):
                return faq.get("answer", "")
        
        # Check products
        for product in self.knowledge_base.get("products", []):
            if product.get("name", "").lower() in question_lower:
                return f"We have {product['name']} available! {product.get('description', '')}"
        
        return None
    
    def get_api_answer(self, question: str, stream: bool = False) -> Generator[str, None, None] | str:
        """ACTUAL OpenRouter API call with proper error handling and retry"""
        self.logger.info(f"📡 Making OpenRouter API request (stream={stream})...")
        
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://ted-pro.streamlit.app",  # Required by OpenRouter
                "X-Title": "TedPro Assistant"  # Required by OpenRouter
            }
            
            data = {
                "model": "openai/gpt-3.5-turbo",  # You can change this to other models
                "messages": [
                    {
                        "role": "system",
                        "content": """You are TedPro, a friendly plushie marketing assistant for a company called CuddleHeroes. 

About CuddleHeroes:
- We sell high-quality plushies and stuffed animals
- We offer customization options (embroidery, colors, sizes)
- We ship internationally
- We have a 30-day return policy
- We offer gift wrapping and personalized notes

Your personality:
- Warm, friendly, and enthusiastic about plushies 🧸
- Helpful and informative about products
- Gently promotional when appropriate
- Use emojis occasionally to be engaging

Keep responses concise but helpful. If you don't know specific details, suggest checking the website or contacting support."""
                    },
                    {
                        "role": "user", 
                        "content": question
                    }
                ],
                "max_tokens": 500,
                "temperature": 0.7,
                "stream": stream
            }
            
            self.logger.info(f"🔑 Using API key: {self.api_key[:10]}...")
            self.logger.info(f"📤 Sending request to: {url}")
            
            # Retry logic (up to 2 retries)
            for attempt in range(3):
                try:
                    response = self.session.post(url, headers=headers, json=data, timeout=30, stream=stream)
                    if response.status_code == 200:
                        break
                    else:
                        self.logger.warning(f"⚠️ API attempt {attempt+1} failed: {response.status_code} {response.text}")
                        time.sleep(1)  # Backoff
                except requests.exceptions.RequestException as e:
                    self.logger.warning(f"⚠️ API attempt {attempt+1} exception: {str(e)}")
                    time.sleep(1)
            else:
                raise ValueError(f"API failed after 3 attempts: {response.status_code} {response.text}")
            
            self.logger.info(f"📥 Response status: {response.status_code}")
            
            if stream:
                for line in response.iter_lines(decode_unicode=True):
                    if line and line.startswith("data: "):
                        if line == "data: [DONE]":
                            break
                        try:
                            data_json = json.loads(line[6:])
                            if 'choices' in data_json and data_json['choices']:
                                delta = data_json['choices'][0]['delta']
                                if 'content' in delta:
                                    yield delta['content']
                        except json.JSONDecodeError:
                            self.logger.warning(f"Invalid JSON in stream: {line}")
                return
            
            else:
                result = response.json()
                return result['choices'][0]['message']['content']
                
        except requests.exceptions.Timeout:
            self.logger.error("⏰ API request timed out")
            raise
        except requests.exceptions.ConnectionError:
            self.logger.error("🔌 API connection error")
            raise
        except Exception as e:
            self.logger.error(f"❌ Unexpected API error: {str(e)}")
            raise
    
    def get_fallback_answer(self, question: str) -> str:
        """Fallback answer when API fails"""
        fallback_responses = [
            "I'd love to help with that! Let me check my resources and get back to you with the best information. 🧸",
            "That's a great question! I'm here to help with all things plushies. Let me find the perfect answer for you. 🎁",
            "Thanks for your question! I specialize in plushie products and would be happy to assist you. 💫",
            "I'm currently experiencing some technical difficulties. Please try again in a moment! 🧸"
        ]
        return random.choice(fallback_responses)
    
    def add_lead(self, name: str, email: str, context: str = "chat_capture"):
        """Add a new lead to the database"""
        try:
            # Use /tmp directory for Streamlit Cloud compatibility
            db_path = Path("/tmp") / f"{self.client_id}_chat_data.db"
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
            
                cursor.execute('''
                    INSERT OR IGNORE INTO leads (name, email, context, timestamp)
                    VALUES (?, ?, ?, ?)
                ''', (name, email, context, datetime.now().isoformat()))
            
                conn.commit()
            self.logger.info(f"📧 Lead captured: {name} <{email}>")
            
        except Exception as e:
            self.logger.error(f"Lead capture error: {e}")
            raise

    def learn_from_interaction(self, question: str, answer: str, feedback: Optional[str] = None):
        """Learn from user interactions to improve responses"""
        # This would be your learning logic
        # For now, just log the interaction
        self.logger.debug(f"Learning from interaction - Q: {question}, A: {answer}, Feedback: {feedback}")
