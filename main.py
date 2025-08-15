import json
from datetime import datetime
from pathlib import Path
from hybrid_engine import HybridEngine
from utilities.backup_knowledge import backup_client_knowledge

class TedPro:
    def __init__(self, client_id):
        self.client_id = client_id
        self.engine = HybridEngine(client_id)
        self._validate_client_folder()

    def _validate_client_folder(self):
        base_path = Path("clients") / self.client_id
        knowledge_path = base_path / "knowledge"
        memory_path = base_path / "memory"

        # Create directories if missing
        knowledge_path.mkdir(parents=True, exist_ok=True)
        memory_path.mkdir(parents=True, exist_ok=True)

        required_files = {
            "config.json": {
                "name": self.client_id,
                "api_key": "",
                "model": "deepseek/deepseek-r1:free",
                "twilio_sid": "",
                "twilio_token": "",
                "twilio_number": "",
                "shop_url": ""
            },
            "knowledge/faq.json": {
                "Do you ship worldwide?": "Yes, we ship to most countries 🧸"
            },
            "memory/conversations.json": []
        }

        for rel_path, default_content in required_files.items():
            file_path = base_path / rel_path
            if not file_path.exists():
                file_path.write_text(json.dumps(default_content, indent=2))
                print(f"[TedPro] Created missing file: {file_path}")

    def respond(self, user_input):
        try:
            response = self.engine.respond(user_input)
            conv_file = Path(f"clients/{self.client_id}/memory/conversations.json")
            conversations = json.loads(conv_file.read_text()) if conv_file.exists() else []
            conversations.append({
                "user": user_input,
                "bot": response,
                "timestamp": datetime.now().isoformat()
            })
            conv_file.write_text(json.dumps(conversations, indent=2))
            return response
        except Exception as e:
            backup_client_knowledge(self.client_id)
            from utilities.email_alerts import notifier
            notifier.send_alert(self.client_id, str(e))
            return "🚨 Error logged - our team has been notified"

if __name__ == "__main__":
    bot = TedPro("demo_client")
    print(bot.respond("Do you ship worldwide?"))
