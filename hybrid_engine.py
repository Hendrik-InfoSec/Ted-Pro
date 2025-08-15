# hybrid_engine.py
import os
import requests

class HybridEngine:
    def __init__(self, api_key=None, model_name="gpt-4o-mini", temperature=0.7):
        """
        A lightweight wrapper to call OpenRouter (or other APIs later).
        """
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("Missing OpenRouter API key. Set OPENROUTER_API_KEY in your environment.")
        
        self.model_name = model_name
        self.temperature = temperature
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

    def get_answer(self, question: str) -> str:
        """
        Send the user's question to the AI model and return the answer.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "http://localhost",
            "X-Title": "Cuddleheroes Plush Bot"
        }

        payload = {
            "model": self.model_name,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": "You are a friendly, plush-loving assistant for Cuddleheroes. Keep answers warm, clear, and helpful."},
                {"role": "user", "content": question}
            ]
        }

        try:
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"Error: {e}")
            return "Oops! I had trouble answering that. Please try again."

    def log_question(self, question: str):
        """
        Could be extended to log Q&A for analytics or training later.
        """
        print(f"[LOG] User asked: {question}")
