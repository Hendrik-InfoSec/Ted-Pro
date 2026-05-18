import os
import uuid
import time
import smtplib
import logging
import hashlib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import pandas as pd

from hybrid_engine import HybridEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="TedPro Assistant", version="2.0.0")
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SECRET_KEY", "tedpro-secret-key-change-in-production"))
app.mount("/static", StaticFiles(directory="static"), name="static")

_engine = None

def get_engine():
    global _engine
    if _engine is None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        sb_url = os.environ.get("SUPABASE_URL")
        sb_key = os.environ.get("SUPABASE_KEY")
        if not all([api_key, sb_url, sb_key]):
            missing = []
            if not api_key: missing.append("OPENROUTER_API_KEY")
            if not sb_url: missing.append("SUPABASE_URL")
            if not sb_key: missing.append("SUPABASE_KEY")
            raise RuntimeError(f"Missing env vars: {', '.join(missing)}")
        _engine = HybridEngine(api_key=api_key, supabase_url=sb_url, supabase_key=sb_key, client_id="tedpro_client")
    return _engine

LOCAL_OFFSET_HOURS = 2

def get_teddy_time():
    utc_now = datetime.now()
    local_now = utc_now + timedelta(hours=LOCAL_OFFSET_HOURS)
    return local_now.strftime("%H:%M")

def apply_teddy_vibes(text: str) -> str:
    warm_closers = ["Paws and hugs, Teddy 🧸", "Stay cozy! 🍯", "Waiting for your next question! ✨", "Teddy out! 🐾"]
    if "price" in text.lower() or "cost" in text.lower():
        text = "I've sniffed out the best value for you! " + text
    return f"{text}\n\n*{warm_closers[int(time.time()) % len(warm_closers)]}*"

def send_welcome_email(name: str, email: str) -> bool:
    try:
        gmail_user = os.environ.get("GMAIL_USER")
        gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
        if not gmail_user or not gmail_password:
            logger.error("Missing Gmail credentials")
            return False
        greeting_name = name if name else "Friend"
        msg = MIMEMultipart('alternative')
        msg['Subject'] = "Welcome to the CuddleHeros VIP Club 🧸"
        msg['From'] = gmail_user
        msg['To'] = email
        html_content = f"""
        <html><body style="font-family:sans-serif;background:#FFF9F4;padding:20px;">
        <div style="max-width:600px;margin:0 auto;background:white;padding:30px;border-radius:20px;">
        <div style="text-align:center;font-size:60px;">🧸</div>
        <h1 style="color:#2D1B00;">Welcome {greeting_name}!</h1>
        <p style="color:#5A3A1B;">Thanks for joining the Honey-Pot!</p>
        <div style="background:#FFE4CC;padding:20px;border-radius:12px;text-align:center;margin:20px 0;">
        <p style="color:#8B6914;text-transform:uppercase;letter-spacing:2px;">Your Exclusive Voucher</p>
        <h2 style="color:#FF922B;font-size:36px;">TEDDY10</h2>
        <p style="color:#8B6914;">10% OFF your first order</p>
        </div>
        <a href="https://cuddleheros.com/shop" style="display:inline-block;background:#FF922B;color:white;padding:16px 40px;border-radius:30px;text-decoration:none;font-weight:600;">Shop the Catalog 🛍️</a>
        <p style="margin-top:30px;color:#8B6914;">Paws and hugs,<br><strong>Teddy 🧸</strong></p>
        </div></body></html>
        """
        msg.attach(MIMEText(html_content, 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, email, msg.as_string())
        logger.info(f"Welcome email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False

def init_session(request: Request):
    if "session_id" not in request.session:
        request.session["session_id"] = str(uuid.uuid4())
    if "chat_history" not in request.session:
        request.session["chat_history"] = []
    if "lead_captured" not in request.session:
        request.session["lead_captured"] = False

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
DEV_PASSWORD = os.environ.get("DEV_PASSWORD")
if not ADMIN_PASSWORD:
    logger.warning("ADMIN_PASSWORD not set - admin access disabled")
    ADMIN_PASSWORD = "__DISABLED__" + os.urandom(16).hex()
if not DEV_PASSWORD:
    logger.warning("DEV_PASSWORD not set - dev access disabled")
    DEV_PASSWORD = "__DISABLED__" + os.urandom(16).hex()

BASE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://unpkg.com/htmx.org@2.0.8"></script>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
body {{ font-family: 'Quicksand', sans-serif; background: #FFF9F4; }}
.teddy-gradient {{ background: linear-gradient(135deg, #FF922B 0%, #FF8C42 50%, #FFD5A5 100%); }}
@keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
.fade-in {{ animation: fadeIn 0.3s ease-in; }}
@keyframes float {{ 0%,100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-10px); }} }}
.float-anim {{ animation: float 3s ease-in-out infinite; }}
.chat-wrapper {{ max-height: calc(100vh - 280px); overflow-y: auto; scrollbar-width: thin; scrollbar-color: #FFD5A5 transparent; }}
.chat-wrapper::-webkit-scrollbar {{ width: 6px; }}
.chat-wrapper::-webkit-scrollbar-track {{ background: transparent; }}
.chat-wrapper::-webkit-scrollbar-thumb {{ background: #FFD5A5; border-radius: 3px; }}
</style>
</head>
<body class="min-h-screen bg-[#FFF9F4]">
{content}
</body>
</html>"""

def render_base(title: str, content: str) -> str:
    return BASE_HTML.format(title=title, content=content)

@app.get("/", response_class=HTMLResponse)
async def chat_page(request: Request):
    init_session(request)
    chat_history = request.session.get("chat_history", [])
    lead_captured = request.session.get("lead_captured", False)
    show_lead = len(chat_history) >= 2 and not lead_captured

    messages_html = ""
    for msg in chat_history:
        if msg["role"] == "user":
            messages_html += f'<div class="flex justify-end fade-in"><div class="flex items-end gap-2 max-w-[70%]"><div class="bg-gradient-to-br from-[#FF922B] to-[#FF8C42] text-white px-5 py-4 rounded-2xl rounded-br-md shadow-md"><p class="text-sm leading-relaxed">{msg["content"]}</p><p class="text-xs opacity-60 text-right mt-2">{msg.get("time", "")}</p></div><div class="w-9 h-9 rounded-full bg-[#FF922B] flex items-center justify-center text-white flex-shrink-0">👤</div></div></div>'
        else:
            messages_html += f'<div class="flex justify-start fade-in"><div class="flex items-end gap-2 max-w-[70%]"><div class="w-9 h-9 rounded-full bg-[#FFE4CC] flex items-center justify-center flex-shrink-0">🧸</div><div class="bg-white border border-[#FFE4CC] px-5 py-4 rounded-2xl rounded-bl-md shadow-md"><p class="text-sm leading-relaxed text-[#2D1B00]">{msg["content"]}</p><p class="text-xs text-[#8B6914] mt-2">{msg.get("time", "")}</p></div></div></div>'

    lead_html = ""
    if show_lead:
        lead_html = '<div id="lead-capture" class="bg-gradient-to-br from-[#FFF0E0] to-[#FFE4CC] border-2 border-[#FFD5A5] rounded-2xl p-5 mb-4 fade-in shadow-md"><div class="flex items-center gap-2 mb-3"><span class="text-2xl">🎁</span><h3 class="font-bold text-[#2D1B00]">Join the VIP Cuddlers Club!</h3></div><p class="text-sm text-[#5A3A1B] mb-4">Get <strong>10% OFF</strong> your first order!</p><form hx-post="/lead" hx-target="#lead-capture" hx-swap="outerHTML" class="space-y-3"><input type="text" name="lead_name" placeholder="Your Name" class="w-full px-4 py-3 rounded-xl border border-[#FFD5A5] bg-white focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-[#2D1B00]"><input type="email" name="lead_email" placeholder="your@email.com" required class="w-full px-4 py-3 rounded-xl border border-[#FFD5A5] bg-white focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-[#2D1B00]"><button type="submit" class="w-full py-3 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42] text-white font-bold shadow-md hover:shadow-lg transition-all">🧸 Claim My Voucher</button></form></div>'

    content = f'<div class="min-h-screen flex flex-col"><div class="teddy-gradient text-white py-5 px-4 text-center shadow-md sticky top-0 z-10"><div class="text-4xl mb-2 float-anim">🧸</div><h1 class="text-2xl font-bold">TedPro</h1><p class="text-sm opacity-90">Your Plushie Marketing Assistant</p><p class="text-xs mt-1 opacity-75">🕒 {get_teddy_time()}</p></div><div class="flex-1 px-4 py-4"><div class="max-w-3xl mx-auto"><div class="text-center mb-6"><div class="inline-block bg-white/80 backdrop-blur-sm rounded-2xl px-6 py-4 shadow-md border border-[#FFE4CC]"><p class="text-[#5A3A1B] text-sm">👋 Hi! I'm <strong>Teddy</strong>, your plushie marketing assistant! Ask me about our products, pricing, or how to grow your plushie business! 🧸</p></div></div><div id="chat-messages" class="chat-wrapper space-y-4 mb-4">{messages_html}</div>{lead_html}<div class="sticky bottom-4 bg-white/90 backdrop-blur-md rounded-2xl p-3 shadow-lg border border-[#FFE4CC]"><form hx-post="/chat" hx-target="#chat-messages" hx-swap="beforeend" class="flex gap-2"><input type="text" name="prompt" placeholder="Ask Teddy anything..." required class="flex-1 px-4 py-3 rounded-xl border border-[#FFD5A5] bg-[#FFF9F4] focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-[#2D1B00]"><button type="submit" class="px-6 py-3 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42] text-white font-bold shadow-md hover:shadow-lg transition-all">🧸 Send</button></form></div><div class="mt-3 text-center"><form action="/chat/clear" method="post"><button type="submit" class="text-xs text-[#8B6914] hover:text-[#FF922B] transition-colors">🗑️ Clear Chat</button></form></div></div></div></div>'

    return HTMLResponse(content=render_base("TedPro Assistant 🧸", content))

@app.post("/chat", response_class=HTMLResponse)
async def chat_message(request: Request, prompt: str = Form(...)):
    init_session(request)
    chat_history = request.session.get("chat_history", [])
    chat_history.append({"role": "user", "content": prompt, "time": get_teddy_time()})
    request.session["chat_history"] = chat_history
    request.session["last_query"] = prompt

    user_msg = f'<div class="flex justify-end fade-in"><div class="flex items-end gap-2 max-w-[70%]"><div class="bg-gradient-to-br from-[#FF922B] to-[#FF8C42] text-white px-5 py-4 rounded-2xl rounded-br-md shadow-md"><p class="text-sm leading-relaxed">{prompt}</p><p class="text-xs opacity-60 text-right mt-2">{get_teddy_time()}</p></div><div class="w-9 h-9 rounded-full bg-[#FF922B] flex items-center justify-center text-white flex-shrink-0">👤</div></div></div><div id="bot-response" hx-ext="sse" sse-connect="/chat/stream" sse-swap="message" class="flex justify-start"><div class="flex items-end gap-2 max-w-[70%]"><div class="w-9 h-9 rounded-full bg-[#FFE4CC] flex items-center justify-center flex-shrink-0">🧸</div><div class="bg-white border border-[#FFE4CC] px-5 py-4 rounded-2xl rounded-bl-md shadow-md"><div class="flex items-center gap-1.5"><div class="w-2 h-2 bg-[#FF922B] rounded-full animate-bounce"></div><div class="w-2 h-2 bg-[#FF922B] rounded-full animate-bounce" style="animation-delay:0.1s"></div><div class="w-2 h-2 bg-[#FF922B] rounded-full animate-bounce" style="animation-delay:0.2s"></div><span class="text-sm text-[#8B6914] italic ml-2">Teddy is thinking...</span></div></div></div></div><script>document.body.addEventListener("htmx:sseClose", function(evt) {{ setTimeout(() => window.location.reload(), 300); }});</script>'

    return HTMLResponse(content=user_msg)

@app.get("/chat/stream")
async def chat_stream(request: Request):
    init_session(request)
    query = request.session.get("last_query", "")

    async def generate():
        try:
            product_keywords = ['have', 'stock', 'buy', 'price', 'cost', 'plushie', 'teddy', 'bear', 'unicorn', 'dinosaur', 'bunny', 'custom', 'order', 'catalog', 'shop', 'available']
            is_product_query = any(kw in query.lower() for kw in product_keywords)
            enhanced_query = query
            if is_product_query:
                products = get_engine().search_products(query, max_results=5)
                if products:
                    product_context = "\n\n[PRODUCT INFO]\n" + get_engine().format_product_response(products)
                    enhanced_query = query + "\n\n" + product_context

            full_response = ""
            for chunk in get_engine().stream_answer(enhanced_query):
                full_response += chunk
                safe_chunk = chunk.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                yield f"event: message\ndata: {safe_chunk}\n\n"

            final = apply_teddy_vibes(full_response)
            chat_history = request.session.get("chat_history", [])
            chat_history.append({"role": "assistant", "content": final, "time": get_teddy_time()})
            request.session["chat_history"] = chat_history

            yield f"event: message\ndata: <script>setTimeout(()=>window.location.reload(),300)</script>\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"event: message\ndata: I'm having trouble connecting right now. Please try again! 🧸\n\n"
            yield f"event: message\ndata: <script>setTimeout(()=>window.location.reload(),500)</script>\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

@app.post("/lead", response_class=HTMLResponse)
async def capture_lead(request: Request, lead_name: str = Form(""), lead_email: str = Form("")):
    init_session(request)
    if not lead_email or "@" not in lead_email:
        return HTMLResponse("<p class='text-red-500'>Please enter a valid email address.</p>")
    try:
        result = get_engine().add_lead(lead_name, lead_email, context="main_chat_v5")
        if result:
            request.session["lead_captured"] = True
            email_sent = send_welcome_email(lead_name, lead_email)
            if email_sent:
                return HTMLResponse("<p class='text-green-600'>✅ Welcome to the VIP Cuddlers club! Check your inbox! 🎁</p>")
            else:
                return HTMLResponse("<p class='text-yellow-600'>✅ Lead saved, but email couldn't be sent.</p>")
        else:
            return HTMLResponse("<p class='text-red-500'>❌ Couldn't save your info. The email might already be registered.</p>")
    except Exception as e:
        return HTMLResponse(f"<p class='text-red-500'>❌ Error: {str(e)}</p>")

@app.post("/chat/clear")
async def clear_chat(request: Request):
    request.session["chat_history"] = []
    return RedirectResponse(url="/", status_code=303)

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    if not request.session.get("admin_authenticated"):
        content = '<div class="min-h-screen flex items-center justify-center bg-[#FFF9F4]"><div class="bg-white p-8 rounded-2xl shadow-lg border border-[#FFE4CC] max-w-md w-full"><div class="text-center mb-6"><div class="text-4xl mb-2">🔒</div><h1 class="text-2xl font-bold text-[#2D1B00]">Admin Access</h1></div><form method="post" action="/admin/login" class="space-y-4"><input type="password" name="password" placeholder="Admin Password" required class="w-full px-4 py-3 rounded-xl border border-[#FFD5A5] bg-[#FFF9F4] focus:outline-none focus:ring-2 focus:ring-[#FF922B]"><button type="submit" class="w-full py-3 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42] text-white font-bold shadow-md">Login</button></form></div></div>'
        return HTMLResponse(content=render_base("Admin Login", content))
    return await admin_dashboard(request)

@app.post("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["admin_authenticated"] = True
        return await admin_dashboard(request)
    return HTMLResponse("<p class='text-red-500'>Incorrect password.</p>", status_code=401)

@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.pop("admin_authenticated", None)
    return RedirectResponse(url="/admin", status_code=303)

async def admin_dashboard(request: Request):
    try:
        from supabase import create_client
        sb_url = os.environ.get("SUPABASE_URL")
        sb_key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(sb_url, sb_key)

        leads_count = len(supabase.table('leads').select('id', count='exact').execute().data)
        conv_count = len(supabase.table('conversations').select('id', count='exact').execute().data)
        cache_count = len(supabase.table('qa_cache').select('id', count='exact').execute().data)
        products_count = len(supabase.table('products').select('id', count='exact').execute().data)
        today = datetime.now().date().isoformat()
        today_leads = len(supabase.table('leads').select('id').gte('timestamp', today).execute().data)

        leads = supabase.table('leads').select('*').order('timestamp', desc=True).limit(50).execute()
        leads_data = leads.data if leads.data else []

        convs = supabase.table('conversations').select('*').order('created_at', desc=True).limit(50).execute()
        convs_data = convs.data if convs.data else []

        products = supabase.table('products').select('*').order('name').execute()
        products_data = products.data if products.data else []

        cache = supabase.table('qa_cache').select('*').order('hit_count', desc=True).limit(20).execute()
        cache_data = cache.data if cache.data else []

        # Build tables HTML
        leads_rows = ""
        for lead in leads_data:
            leads_rows += f'<tr class="border-b border-[#FFE4CC]"><td class="px-4 py-2 text-sm">{lead.get("name", "")}</td><td class="px-4 py-2 text-sm">{lead.get("email", "")}</td><td class="px-4 py-2 text-sm">{lead.get("timestamp", "")[:10]}</td></tr>'

        content = f'<div class="min-h-screen bg-[#FFF9F4] p-4"><div class="max-w-6xl mx-auto"><div class="flex justify-between items-center mb-6"><h1 class="text-3xl font-bold text-[#2D1B00]">📊 Admin Dashboard</h1><a href="/admin/logout" class="text-sm text-[#8B6914] hover:text-[#FF922B]">Logout</a></div><div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6"><div class="bg-white p-4 rounded-xl shadow-md border border-[#FFE4CC]"><p class="text-sm text-[#8B6914]">Total Leads</p><p class="text-2xl font-bold text-[#2D1B00]">{leads_count}</p></div><div class="bg-white p-4 rounded-xl shadow-md border border-[#FFE4CC]"><p class="text-sm text-[#8B6914]">Today</p><p class="text-2xl font-bold text-[#2D1B00]">{today_leads}</p></div><div class="bg-white p-4 rounded-xl shadow-md border border-[#FFE4CC]"><p class="text-sm text-[#8B6914]">Conversations</p><p class="text-2xl font-bold text-[#2D1B00]">{conv_count}</p></div><div class="bg-white p-4 rounded-xl shadow-md border border-[#FFE4CC]"><p class="text-sm text-[#8B6914]">Products</p><p class="text-2xl font-bold text-[#2D1B00]">{products_count}</p></div></div><div class="bg-white rounded-xl shadow-md border border-[#FFE4CC] overflow-hidden"><div class="p-4 border-b border-[#FFE4CC]"><h2 class="font-bold text-[#2D1B00]">Recent Leads</h2></div><table class="w-full"><thead class="bg-[#FFF9F4]"><tr><th class="px-4 py-2 text-left text-sm text-[#8B6914]">Name</th><th class="px-4 py-2 text-left text-sm text-[#8B6914]">Email</th><th class="px-4 py-2 text-left text-sm text-[#8B6914]">Date</th></tr></thead><tbody>{leads_rows}</tbody></table></div></div></div>'

        return HTMLResponse(content=render_base("Admin Dashboard", content))
    except Exception as e:
        return HTMLResponse(f"<p class='text-red-500'>Error loading dashboard: {e}</p>")

@app.get("/dev", response_class=HTMLResponse)
async def dev_page(request: Request):
    if not request.session.get("dev_authenticated"):
        content = '<div class="min-h-screen flex items-center justify-center bg-[#FFF9F4]"><div class="bg-white p-8 rounded-2xl shadow-lg border border-[#FFE4CC] max-w-md w-full"><div class="text-center mb-6"><div class="text-4xl mb-2">🔧</div><h1 class="text-2xl font-bold text-[#2D1B00]">Dev Tools</h1></div><form method="post" action="/dev/login" class="space-y-4"><input type="password" name="password" placeholder="Dev Password" required class="w-full px-4 py-3 rounded-xl border border-[#FFD5A5] bg-[#FFF9F4] focus:outline-none focus:ring-2 focus:ring-[#FF922B]"><button type="submit" class="w-full py-3 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42] text-white font-bold shadow-md">Login</button></form></div></div>'
        return HTMLResponse(content=render_base("Dev Login", content))
    return await dev_dashboard(request)

@app.post("/dev/login", response_class=HTMLResponse)
async def dev_login(request: Request, password: str = Form(...)):
    if password == DEV_PASSWORD:
        request.session["dev_authenticated"] = True
        return await dev_dashboard(request)
    return HTMLResponse("<p class='text-red-500'>Incorrect password.</p>", status_code=401)

@app.get("/dev/logout")
async def dev_logout(request: Request):
    request.session.pop("dev_authenticated", None)
    return RedirectResponse(url="/dev", status_code=303)

async def dev_dashboard(request: Request):
    env_vars = {
        "OPENROUTER_API_KEY": "SET ✓" if os.environ.get("OPENROUTER_API_KEY") else "NOT SET",
        "SUPABASE_URL": os.environ.get("SUPABASE_URL", "NOT SET"),
        "SUPABASE_KEY": "SET ✓" if os.environ.get("SUPABASE_KEY") else "NOT SET",
        "GMAIL_USER": os.environ.get("GMAIL_USER", "NOT SET"),
        "GMAIL_APP_PASSWORD": "SET ✓" if os.environ.get("GMAIL_APP_PASSWORD") else "NOT SET",
    }
    env_rows = ""
    for key, val in env_vars.items():
        env_rows += f'<tr class="border-b border-[#FFE4CC]"><td class="px-4 py-2 text-sm font-mono">{key}</td><td class="px-4 py-2 text-sm">{val}</td></tr>'

    content = f'<div class="min-h-screen bg-[#FFF9F4] p-4"><div class="max-w-4xl mx-auto"><div class="flex justify-between items-center mb-6"><h1 class="text-3xl font-bold text-[#2D1B00]">🔧 Dev Tools</h1><a href="/dev/logout" class="text-sm text-[#8B6914] hover:text-[#FF922B]">Logout</a></div><div class="bg-white rounded-xl shadow-md border border-[#FFE4CC] overflow-hidden mb-6"><div class="p-4 border-b border-[#FFE4CC]"><h2 class="font-bold text-[#2D1B00]">Environment Variables</h2></div><table class="w-full"><thead class="bg-[#FFF9F4]"><tr><th class="px-4 py-2 text-left text-sm text-[#8B6914]">Variable</th><th class="px-4 py-2 text-left text-sm text-[#8B6914]">Status</th></tr></thead><tbody>{env_rows}</tbody></table></div></div></div>'

    return HTMLResponse(content=render_base("Dev Tools", content))
