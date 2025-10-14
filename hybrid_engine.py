import logging
import os
import json
import time
import requests
import tempfile
import openai  # Added for real transcription
from typing import Generator, Optional

class HybridEngine:
    def __init__(self, api_key: str, model: str = "openai/gpt-3.5-turbo", db_path: Optional[str] = None, client_id: Optional[str] = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.api_key = api_key
        self.model = model
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        self.db_path = db_path  # Placeholder for local DB if implemented
        self.client_id = client_id  # Optional: For tracking per-client usage or sessions
        self.openai_api_key = os.getenv("OPENAI_API_KEY")  # For Whisper transcription
        if not self.openai_api_key:
            self.logger.warning("OPENAI_API_KEY not found - using mock transcription")
        self.logger.info(f"HybridEngine initialized with API key: {bool(api_key)}, model: {model}, client_id: {client_id}")

    def search_local_db(self, question: str) -> Optional[str]:
        # Placeholder: Implement actual DB search if needed (e.g., using SQLite or vector DB)
        # For now, always return None to fallback to API
        self.logger.info("Checking local DB for match...")
        return None

    def transcribe_audio(self, audio_data: bytes, lang: str = "en") -> str:
        self.logger.info(f"Attempting audio transcription (lang={lang})")
        if not self.openai_api_key:
            self.logger.warning("Using mock transcription - OPENAI_API_KEY not set")
            return "Mock transcribed text from audio input"
        
        try:
            # Save audio to temp file (Streamlit audio_input gives bytes)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_file_path = temp_file.name
            
            # Transcribe with Whisper
            openai.api_key = self.openai_api_key
            with open(temp_file_path, "rb") as audio_file:
                response = openai.Audio.transcribe(
                    model="whisper-1",
                    file=audio_file,
                    language=lang
                )
            transcribed_text = response['text']
            
            # Clean up temp file
            os.unlink(temp_file_path)
            
            self.logger.info(f"Transcription successful: {transcribed_text[:50]}...")
            return transcribed_text
        except Exception as e:
            self.logger.error(f"Audio transcription error: {str(e)}")
            return "Error transcribing audio - please try again or type your message."

    def process_question(self, question: str, stream: bool = True) -> str:
        local_answer = self.search_local_db(question)
        if local_answer:
            return local_answer
        self.logger.info("No local match, streaming from OpenRouter API...")
        if stream:
            return "".join([chunk for chunk in self.stream_answer(question)])
        else:
            return self.get_api_answer(question, stream=False)

    def stream_answer(self, question: str, lang: str = "en", *args, **kwargs) -> Generator[str, None, None]:
        # Added lang param to match main.py call: engine.stream_answer(user_input, st.session_state.language)
        # Flex args for any extras; now uses lang for prompt if needed (future: multi-lang models)
        if args or kwargs:
            self.logger.warning(f"stream_answer received extra args: {args}, kwargs: {kwargs} - ignoring for compatibility")
        self.logger.info(f"Processing question (stream): '{question}' (lang={lang})")
        try:
            # Enhanced prompt for TedPro persona + language
            system_prompt = (
                "You are TedPro, a friendly plushie marketing assistant. Respond helpfully about products, shipping, offers. "
                "Keep responses engaging, short, and fun. Use English only."
            ) if lang == "en" else (
                "Eres TedPro, un asistente amigable de peluches. Responde útil sobre productos, envíos, ofertas. "
                "Mantén respuestas atractivas, cortas y divertidas. Usa solo español."
            )
            for chunk in self.get_api_answer(question, stream=True, system_prompt=system_prompt):
                yield chunk
        except Exception as e:
            self.logger.error(f"Stream error: {str(e)}")
            raise

    def get_api_answer(self, question: str, stream: bool = True, system_prompt: Optional[str] = None) -> Generator[str, None, str]:
        self.logger.info(f"Making OpenRouter API request (stream={stream}, lang=en)...")
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
#     engine = HybridEngine(api_key="your_openrouter_api_key_here", client_id="tedpro_client")
#     answer_gen = engine.process_question("Hello, who are you?")
#     print(answer_gen)
