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
from rich.logging import RichHandler
from rich.traceback import install as install_rich_traceback

# Install rich traceback for better error formatting
install_rich_traceback()

class HybridEngine:
    def __init__(self, api_key: str, client_id: str):
        self.api_key = api_key
        self.client_id = client_id
        self.client_path = Path("/tmp") / client_id
        self.client_path.mkdir(parents=True, exist_ok=True)
        self.knowledge_base = self.load_knowledge_base()
        self.conversation_history: List[Dict[str, str]] = []
        self.logger = logging.getLogger("HybridEngine")
        self.logger.handlers = []
        self.logger.addHandler(RichHandler(rich_tracebacks=True))
        self.logger.setLevel(logging.INFO)
        self.session = requests.Session()
        self.model = os.getenv("OPENROUTER_MODEL", "openai/gpt-3.5-turbo")  # Default to GPT, allow DeepSeek
        self.logger.info(f"HybridEngine initialized with API key: {bool(api_key)}, model: {self.model}")
        
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
    
    def answer(self, question: str, lang: str = "en") -> str:
        """Generate answer using hybrid approach - ACTUALLY CALLS OPENROUTER (non-streaming)"""
        self.logger.info(f"Processing question (non-stream): '{question}'")
        start_time = time.time()
        try:
            local_answer = self.search_local_knowledge(question)
            if local_answer:
                self.logger.info("Using local knowledge base answer")
                return local_answer
            self.logger.info("No local match, calling OpenRouter API...")
            api_response = self.get_api_answer(question, lang, stream=False)
            response_time = time.time() - start_time
            self.logger.info(f"OpenRouter API response received in {response_time:.2f}s")
            return api_response
        except Exception as e:
            response_time = time.time() - start_time
            self.logger.error(f"Error after {response_time:.2f}s: {str(e)}", exc_info=True)
            return self.get_fallback_answer(question, lang)

    def stream_answer(self, question: str, lang: str = "en") -> Generator[str, None, None]:
        """Stream answer using hybrid approach - ACTUALLY CALLS OPENROUTER (streaming)"""
        self.logger.info(f"Processing question (stream): '{question}'")
        start_time = time.time()
        try:
            local_answer = self.search_local_knowledge(question)
            if local_answer:
                self.logger.info("Using local knowledge base answer (streaming as chunks)")
                # Yield in sentence chunks for better UI
                import re
                sentences = re.split(r'(?<=[.!?])\s+', local_answer)
                for sentence in sentences:
                    yield sentence + " "
                    time.sleep(0.05)  # Simulate streaming
                return
            self.logger.info("No local match, streaming from OpenRouter API...")
            for chunk in self.get_api_answer(question, lang, stream=True):
                yield chunk
            response_time = time.time() - start_time
            self.logger.info(f"OpenRouter API stream completed in {response_time:.2f}s")
        except Exception as e:
            response_time = time.time() - start_time
            self.logger.error(f"Stream error after {response_time:.2f}s: {str(e)}", exc_info=True)
            yield self.get_fallback_answer(question, lang)

    def search_local_knowledge(self, question: str) -> Optional[str]:
        """Search local FAQ and knowledge base"""
        question_lower = question.lower()
        for faq in self.knowledge_base.get("faqs", []):
            if any(keyword in question_lower for keyword in faq.get("keywords", [])):
                return faq.get("answer", "")
        for product in self.knowledge_base.get("products", []):
            if product.get("name", "").lower() in question_lower:
                return f"We have {product['name']} available! {product.get('description', '')}"
        return None
    
    def get_api_answer(self, question: str, lang: str = "en", stream: bool = False) -> Generator[str, None, None] | str:
        """ACTUAL OpenRouter API call with proper error handling and retry"""
        self.logger.info(f"Making OpenRouter API request (stream={stream}, lang={lang})...")
        if lang == "es":
            system_prompt = """Eres TedPro, un asistente de marketing amigable de peluches para una compañía llamada CuddleHeros. 
Sobre CuddleHeros:
- Vendemos peluches y animales de peluche de alta calidad
- Ofrecemos opciones de personalización (bordado, colores, tamaños)
- Enviamos internacionalmente
- Tenemos una política de devolución de 30 días
- Ofrecemos envoltura de regalos y notas personalizadas
Tu personalidad:
- Cálido, amigable y entusiasta sobre peluches 🧸
- Útil e informativo sobre productos
- Gentilmente promocional cuando sea apropiado
- Usa emojis ocasionalmente para ser atractivo
Mantén las respuestas concisas pero útiles. Si no sabes detalles específicos, sugiere revisar el sitio web o contactar soporte."""
        else:
            system_prompt = """You are TedPro, a friendly plushie marketing assistant for a company called CuddleHeros. 
About CuddleHeros:
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
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://ted-pro.streamlit.app",
                "X-Title": "TedPro Assistant"
            }
            data = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                "max_tokens": 500,
                "temperature": 0.7,
                "stream": stream
            }
            self.logger.info(f"Using API key: {self.api_key[:10]}...")
            self.logger.info(f"Sending request to: {url}")
            for attempt in range(3):
                try:
                    response = self.session.post(url, headers=headers, json=data, timeout=30, stream=stream)
                    if response.status_cde == 200:
                        break
                    else:
                        self.logger.warning(f"API attempt {attempt+1} failed: {response.status_code} {response.text}")
                        time.sleep(1)
                except requests.exceptions.RequestException as e:
                    self.logger.warning(f"API attempt {attempt+1} exception: {str(e)}")
                    time.sleep(1)
            else:
                raise ValueError(f"API failed after 3 attempts: {response.status_code} {response.text}")
            self.logger.info(f"Response status: {response.status_code}")
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
            self.logger.error("API request timed out", exc_info=True)
            raise
        except requests.exceptions.ConnectionError:
            self.logger.error("API connection error", exc_info=True)
            raise
        except Exception as e:
            self.logger.error(f"Unexpected API error: {str(e)}", exc_info=True)
            raise
    
    def get_fallback_answer(self, question: str, lang: str = "en") -> str:
        """Fallback answer when API fails"""
        if lang == "es":
            fallback_responses = [
                "¡Me encantaría ayudar con eso! Déjame revisar mis recursos y te daré la mejor información. 🧸",
                "¡Esa es una gran pregunta! Estoy aquí para ayudar con todo lo relacionado con peluches. Déjame encontrar la respuesta perfecta para ti. 🎁",
                "¡Gracias por tu pregunta! Me especializo en productos de peluches y estaré encantado de ayudarte. 💫",
                "Estoy experimentando algunas dificultades técnicas en este momento. ¡Por favor intenta de nuevo en un momento! 🧸"
            ]
        else:
            fallback_responses = [
                "I'd love to help with that! Let me check my resources and get back to you with the best information. 🧸",
                "That's a great question! I'm here to help with all things plushies. Let me find the perfect answer for you. 🎁",
                "Thanks for your question! I specialize in plushie products and would be happy to assist you. 💫",
                "I'm currently experiencing some technical difficulties. Please try again in a moment! 🧸"
            ]
        return random.choice(fallback_responses)
    
    def add_lead(self, name: str, email: str, context: str = "chat_capture", consent: bool = True):
        """Add a new lead to the database with hashing and consent check"""
        if not consent:
            self.logger.warning(f"Lead capture skipped due to lack of consent: {name} <{email}>")
            return
        try:
            hashed_email = hashlib.sha256(email.encode()).hexdigest()
            db_path = self.client_path / f"{self.client_id}_chat_data.db"
            with sqlite3.connect(db_path, timeout=10) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS leads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        hashed_email TEXT UNIQUE NOT NULL,
                        context TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        consent TEXT
                    )
                ''')
                cursor.execute('''
                    INSERT OR IGNORE INTO leads (name, hashed_email, context, timestamp, consent)
                    VALUES (?, ?, ?, ?, ?)
                ''', (name, hashed_email, context, datetime.now().isoformat(), 'YES' if consent else 'NO'))
                conn.commit()
            self.logger.info(f"Lead captured: {name} <{email}> (hashed: {hashed_email[:10]}...)")
        except Exception as e:
            self.logger.error(f"Lead capture error: {e}", exc_info=True)
            raise

    def transcribe_audio(self, audio_data: bytes, lang: str = "en") -> Optional[str]:
        """Placeholder for audio transcription with enhanced error handling"""
        self.logger.info(f"Attempting audio transcription (lang={lang})")
        try:
            # Mock transcription - replace with Whisper API when ready
            self.logger.warning("Using mock transcription - Whisper API not integrated")
            mock_text = "Mock transcribed text from audio input" if lang == "en" else "Texto transcrito simulado de entrada de audio"
            return mock_text
            # Example Whisper integration (uncomment when ready):
            # response = requests.post(
            #     "https://api.openai.com/v1/audio/transcriptions",
            #     headers={"Authorization": f"Bearer {self.api_key}"},
            #     files={"file": ("audio.wav", audio_data, "audio/wav")},
            #     data={"model": "whisper-1", "language": lang}
            # )
            # if response.status_code == 200:
            #     return response.json().get("text")
            # else:
            #     self.logger.error(f"Whisper API failed: {response.status_code} {response.text}")
            #     return None
        except Exception as e:
            self.logger.error(f"Audio transcription error: {e}", exc_info=True)
            return None
