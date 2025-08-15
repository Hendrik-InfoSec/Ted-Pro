# SHOPIFY INTEGRATION
def get_order_status(order_id, shop_url, api_key):
    import requests
    headers = {
        "X-Shopify-Access-Token": api_key,
        "Content-Type": "application/json"
    }
    response = requests.get(
        f"https://{shop_url}/admin/api/2023-07/orders/{order_id}.json",
        headers=headers
    )
    return response.json().get("order", {}).get("fulfillment_status", "processing")

# TWILIO SMS
def send_sms(to_number, message, client_config):
    from twilio.rest import Client
    client = Client(client_config['twilio_sid'], client_config['twilio_token'])
    client.messages.create(
        body=f"🧸 {message}",
        from_=client_config['twilio_number'],
        to=to_number
    )