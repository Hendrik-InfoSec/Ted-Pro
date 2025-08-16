import os
from datetime import datetime, timedelta

# ---------- Optional Twilio (left intact) ----------
def get_twilio_client():
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

# ---------- Order Tracking (Mock) ----------
# Replace this with a real DB/API later. For now, a small in-memory sample.
_MOCK_ORDERS = {
    "1234": {"status": "Packed", "last_update": "Today 09:15", "eta": "3–5 business days"},
    "ORDER1234": {"status": "In Transit", "last_update": "Yesterday 17:40", "eta": "2–4 business days"},
    "CX89AB12": {"status": "Delivered", "last_update": "2 days ago", "eta": "Delivered"},
}

def get_order_status(order_id: str):
    if not order_id:
        return None
    # normalize: case-insensitive keys
    oid = order_id.strip()
    if oid in _MOCK_ORDERS:
        return _MOCK_ORDERS[oid]
    # try uppercase key
    up = oid.upper()
    if up in _MOCK_ORDERS:
        return _MOCK_ORDERS[up]
    # not found
    return None
