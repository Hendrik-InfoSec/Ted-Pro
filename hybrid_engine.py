import json
import os
from pathlib import Path
import sqlite3
import requests
import logging
from typing import Dict, List, Optional
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
        self.conversation_history = []
        self.logger = logging.getLogger("HybridEngine")
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
        """Generate answer using hybrid approach - ACTUALLY CALLS OPENROUTER"""
        self.logger.info(f"🔍 Processing question: '{question}'")
        start_time = time.time()
        
        try:
            # First try local knowledge base
            local_answer = self.search_local_knowledge(question)
            if local_answer:
                self.logger.info("✅ Using local knowledge base answer")
                return local_answer
            
            self.logger.info("🌐 No local match, calling OpenRouter API...")
            
            # ACTUAL API CALL to OpenRouter
            api_response = self.get_api_answer(question)
            
            response_time = time.time() - start_time
            self.logger.info(f"✅ OpenRouter API response received in {response_time:.2f}s")
            
            return api_response
                
        except Exception as e:
            response_time = time.time() - start_time
            self.logger.error(f"❌ Error after {response_time:.2f}s: {str(e)}")
            return self.get_fallback_answer(question)
    
    def search_local_knowledge(self, question: str) -> Optional[str]:
        """Search local FAQ and knowledge base"""
        question_lower = question.lower()
        
        # Simple greetings - respond immediately without API call
        greetings = ["hi", "hello", "hey", "hola", "greetings", "howdy"]
        if question_lower.strip() in greetings:
            return "Hello there! 🧸 I'm TedPro, your friendly plushie assistant! How can I help you today? Whether you have questions about our products, shipping, or custom orders, I'm here to help!"
        
        # Check FAQs
        for faq in self.knowledge_base.get("faqs", []):
            if any(keyword in question_lower for keyword in faq.get("keywords", [])):
                return faq.get("answer", "")
        
        # Check products
        for product in self.knowledge_base.get("products", []):
            if product.get("name", "").lower() in question_lower:
                return f"We have {product['name']} available! {product.get('description', '')}"
        
        return None
    
    def get_api_answer(self, question: str) -> str:
        """ACTUAL OpenRouter API call with proper error handling"""
        self.logger.info(f"📡 Making OpenRouter API request...")
        
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://ted-pro.streamlit.app",
                "X-Title": "TedPro Assistant"
            }
            
            data = {
                "model": "openai/gpt-3.5-turbo",
                "messages": [
                    {
                        "role": "system",
                        "content": """You are TedPro, a friendly plushie marketing assistant. Be warm, helpful, and concise. Use emojis occasionally. Keep responses under 3 sentences unless more detail is needed."""
                    },
                    {
                        "role": "user", 
                        "content": question
                    }
                ],
                "max_tokens": 150,
                "temperature": 0.7
            }
            
            self.logger.info(f"🔑 Using API key: {self.api_key[:10]}...")
            
            # CRITICAL FIX: Reduced timeout to 15 seconds
            response = requests.post(url, headers=headers, json=data, timeout=15)
            self.logger.info(f"📥 Response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                answer = result['choices'][0]['message']['content']
                self.logger.info(f"✅ API success: {answer[:100]}...")
                return answer
            else:
                self.logger.error(f"❌ API error {response.status_code}: {response.text}")
                return "I'm having trouble connecting right now. Please try again! 🧸"
                
        except requests.exceptions.Timeout:
            self.logger.error("⏰ API request timed out after 15 seconds")
            return "I'm taking a bit longer than usual to respond. Please try again! 🧸"
        except requests.exceptions.ConnectionError:
            self.logger.error("🔌 API connection error")
            return "I'm having trouble connecting to my knowledge base. Please check your internet connection! 🧸"
        except Exception as e:
            self.logger.error(f"❌ Unexpected API error: {str(e)}")
            return "I encountered an unexpected error. Please try again! 🧸"
    
    def get_fallback_answer(self, question: str) -> str:
        """Fallback answer when API fails"""
        fallback_responses = [
            "I'd love to help with that! Let me check my resources and get back to you with the best information. 🧸",
            "That's a great question! I'm here to help with all things plushies. Let me find the perfect answer for you. 🎁",
            "Thanks for your question! I specialize in plushie products and would be happy to assist you. 💫",
        ]
        return random.choice(fallback_responses)
    
    def add_lead(self, name: str, email: str, context: str = "chat_capture"):
        """Add a new lead to the database"""
        try:
            # Use /tmp directory for Streamlit Cloud compatibility
            db_path = Path("/tmp") / f"{self.client_id}_chat_data.db"
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR IGNORE INTO leads (name, email, context, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (name, email, context, datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            self.logger.info(f"📧 Lead captured: {name} <{email}>")
            
        except Exception as e:
            self.logger.error(f"Lead capture error: {e}")
            raise
