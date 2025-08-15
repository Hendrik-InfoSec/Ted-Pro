import os

def get_twilio_client():
    """
    Optional Twilio hook. Safe to import even without credentials.
    Only initialize if both SID and TOKEN exist.
    """
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        return None
    try:
        from twilio.rest import Client
        return Client(sid, token)
    except Exception:
        return None

def send_sms(to_number: str, body: str) -> bool:
    client = get_twilio_client()
    if not client:
        return False
    from_number = os.getenv("TWILIO_PHONE_NUMBER", "")
    if not from_number:
        return False
    try:
        client.messages.create(to=to_number, from_=from_number, body=body)
        return True
    except Exception:
        return False
