import json
import os
from pathlib import Path

def create_client(client_name):
    """Auto-generates client folder structure"""
    client_path = Path(f"clients/{client_name}")
    client_path.mkdir(parents=True, exist_ok=True)
    
    # Create default files
    (client_path / "knowledge").mkdir()
    (client_path / "memory").mkdir()
    
    with open(client_path / "config.json", "w") as f:
        json.dump({
            "shop_name": client_name,
            "primary_color": "#FF6B6B",
            "api_keys": {}
        }, f, indent=2)
        
    print(f"✅ Client '{client_name}' setup complete!")

if __name__ == "__main__":
    create_client(input("Client business name: "))