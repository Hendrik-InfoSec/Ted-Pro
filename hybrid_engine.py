import logging
import os
import json
import time
import requests
from typing import Generator, Optional

class HybridEngine:
    def __init__(self, api_key: str, model: str = "openai/gpt-3.5-turbo", db_path: Optional[str] = None, client_id: Optional[str] = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = api_key
        self.model = model
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        self.db_path = db_path
        self.client_id = client_id
        self.logger.info(f"HybridEngine initialized with API key: {bool(api_key)}, model: {model}, client_id: {client_id}")

    def search_local_db(self, question: str) -> Optional[str]:
        # Placeholder for local DB search
        self.logger.info("Checking local DB for match...")
        return None

    def add_lead(self, name: str, email: str, context: str = "chat"):
        """Add lead to database - placeholder implementation"""
        self.logger.info(f"📧 Lead added: {name} <{email}> - Context: {context}")
        # In a real implementation, this would save to a database
        return True

    def stream_answer(self, question: str) -> Generator[str, None, None]:
        """Stream answer from OpenRouter API"""
        self.logger.info(f"Processing question (stream): '{question}'")
        try:
            system_prompt = (
                "You are TedPro, a friendly, warm, and enthusiastic plushie marketing assistant for CuddleHeros. "
                "You have a playful personality and love helping people find the perfect plushie companion. "
                "Respond in a conversational, friendly tone with occasional emojis. "
                "Be helpful with product recommendations, shipping info, and custom orders. "
                "Show genuine excitement about plushies and making people happy. "
                "Keep responses engaging but concise - imagine you're talking to a friend about cute stuffed animals!"
            )
            
            for chunk in self.get_api_answer(question, stream=True, system_prompt=system_prompt):
                yield chunk
        except Exception as e:
            self.logger.error(f"Stream error: {str(e)}")
            yield f"I'm having trouble connecting right now. Please try again! 🧸"

    def get_api_answer(self, question: str, stream: bool = True, system_prompt: Optional[str] = None) -> Generator[str, None, None]:
        """Make API call to OpenRouter"""
        self.logger.info(f"Making OpenRouter API request (stream={stream})...")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": question})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv("SITE_URL", "http://localhost"),
            "X-Title": os.getenv("SITE_NAME", "TedPro")
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
                    raise ValueError(f"API error {response.status_code}: {error_detail}")
                
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
