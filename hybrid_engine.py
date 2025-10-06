import json
import os
from pathlib import Path
import sqlite3
import requests
import logging
from typing import Dict, List, Optional
import hashlib

class HybridEngine:
    def __init__(self, api_key: str, client_id: str):
        self.api_key = api_key
        self.client_id = client_id
        self.client_path = Path(f"clients/{client_id}")
        self.client_path.mkdir(parents=True, exist_ok=True)
        self.knowledge_base = self.load_knowledge_base()
        self.conversation_history = []
        
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
        """Generate answer using hybrid approach"""
        try:
            # First try local knowledge base
            local_answer = self.search_local_knowledge(question)
            if local_answer:
                return local_answer
            
            # Fallback to API if available
            if self.api_key and self.api_key != "your-api-key-here":
                return self.get_api_answer(question)
            else:
                return self.get_fallback_answer(question)
                
        except Exception as e:
            logging.error(f"Answer generation error: {e}")
            return "I'm having trouble connecting to my knowledge base. Please try again later! 🧸"
    
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
    
    def get_api_answer(self, question: str) -> str:
        """Get answer from external API"""
        try:
            # This would be your actual API call
            # For now, return a placeholder
            return "I'd be happy to help with that! Based on your question, I recommend checking our product catalog in the sidebar. 🧸"
        except Exception as e:
            logging.error(f"API call failed: {e}")
            return self.get_fallback_answer(question)
    
    def get_fallback_answer(self, question: str) -> str:
        """Fallback answer when no specific match found"""
        fallback_responses = [
            "I'm a friendly plushie assistant! I can help with product info, pricing, shipping, and more. What would you like to know? 🧸",
            "Thanks for your question! I specialize in helping with plushie products and orders. Feel free to ask me anything!",
            "I'd love to help you with that! You can also check our product catalog in the sidebar for more details. 🎁"
        ]
        return random.choice(fallback_responses)
    
    def add_lead(self, name: str, email: str, context: str = "chat_capture"):
        """Add a new lead to the database"""
        try:
            db_path = self.client_path / "chat_data.db"
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR IGNORE INTO leads (name, email, context, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (name, email, context, datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            logging.info(f"Lead captured: {name} <{email}>")
            
        except Exception as e:
            logging.error(f"Lead capture error: {e}")
            raise

    def learn_from_interaction(self, question: str, answer: str, feedback: Optional[str] = None):
        """Learn from user interactions to improve responses"""
        # This would be your learning logic
        pass
