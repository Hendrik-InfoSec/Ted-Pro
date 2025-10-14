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
        self.db_path = db_path  # Placeholder for local DB if implemented
        self.client_id = client_id  # Optional: For tracking per-client usage or sessions
        self.logger.info(f"HybridEngine initialized with API key: {bool(api_key)}, model: {model}, client_id: {client_id}")

    def search_local_db(self, question: str) -> Optional[str]:
        # Placeholder: Implement actual DB search if needed (e.g., using SQLite or vector DB)
        # For now, always return None to fallback to API
        self.logger.info("Checking local DB for match...")
        return None

    def transcribe_audio(self, audio_data: bytes, lang: str = "en") -> str:
        self.logger.info(f"Attempting audio transcription (lang={lang})")
        # Placeholder: Integrate Whisper API or local model here
        self.logger.warning("Using mock transcription - Whisper API not integrated")
        return "Mock transcribed text from audio input"  # Mock response

    def process_question(self, question: str, stream: bool = True) -> str:
        local_answer = self.search_local_db(question)
        if local_answer:
            return local_answer
        self.logger.info("No local match, streaming from OpenRouter API...")
        if stream:
            return "".join([chunk for chunk in self.stream_answer(question)])
        else:
            return self.get_api_answer(question, stream=False)

    def stream_answer(self, question: str) -> Generator[str, None, None]:
        self.logger.info(f"Processing question (stream): '{question}'")
        try:
            for chunk in self.get_api_answer(question, stream=True):
                yield chunk
        except Exception as e:
            self.logger.error(f"Stream error: {str(e)}")
            raise

    def get_api_answer(self, question: str, stream: bool = True) -> Generator[str, None, str]:
        self.logger.info(f"Making OpenRouter API request (stream={stream}, lang=en)...")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": question}],
            "stream": stream
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv("SITE_URL", "http://localhost"),  # Optional: Set your site URL
            "X-Title": os.getenv("SITE_NAME", "TedPro")  # Optional: Set your app name
        }
        if self.client_id:
            headers["X-Client-ID"] = self.client_id  # Optional: Pass client_id if needed for OpenRouter tracking
        
        start_time = time.time()
        for attempt in range(3):
            try:
                self.logger.info(f"Using API key: {self.api_key[:10]}...")
                self.logger.info(f"Sending request to: {self.api_url}")
                
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=30,
                    stream=stream
                )
                
                self.logger.info(f"API response status: {response.status_code}")
                
                if response.status_code != 200:
                    error_detail = response.text
                    raise ValueError(f"API error {response.status_code}: {error_detail}")
                
                if stream:
                    response_iter = response.iter_lines()
                    for line in response_iter:
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
                    return json_response["choices"][0]["message"]["content"]
                
                break  # Success, exit retry loop
                
            except Exception as e:
                self.logger.error(f"Unexpected API error: {str(e)}")
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff

# Example usage (deployment ready - integrate into your main.py)
# if __name__ == "__main__":
#     engine = HybridEngine(api_key="your_openrouter_api_key_here", client_id="6a63fa70-434c-47eb-b395-afd93a53240c")
#     answer_gen = engine.process_question("Hello, who are you?")
#     print(answer_gen)
