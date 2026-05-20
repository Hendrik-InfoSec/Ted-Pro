import os
import uuid
import time
import smtplib
import logging
import hashlib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from hybrid_engine import HybridEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="TedPro Assistant", version="2.0.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "tedpro-fallback-secret")
)

# Auto-create static folder so StaticFiles doesn't crash on fresh deploy
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------------------------------------------------------------
# Engine (lazy init — connects on first request, not at startup)
# ---------------------------------------------------------------------------
_engine = None

def get_engine():
    global _engine
    if _engine is None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        sb_url  = os.environ.get("SUPABASE_URL")
        sb_key  = os.environ.get("SUPABASE_KEY")
        missing = [k for k, v in {"OPENROUTER_API_KEY": api_key, "SUPABASE_URL": sb_url, "SUPABASE_KEY": sb_key}.items() if not v]
        if missing:
            raise RuntimeError(f"Missing env vars: {', '.join(missing)}")
        _engine = HybridEngine(api_key=api_key, supabase_url=sb_url, supabase_key=sb_key, client_id="tedpro_client")
    return _engine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
LOCAL_OFFSET_HOURS = 2

def get_teddy_time():
    return (datetime.now() + timedelta(hours=LOCAL_OFFSET_HOURS)).strftime("%H:%M")

def apply_teddy_vibes(text: str) -> str:
    closers = ["Paws and hugs, Teddy \U0001f9f8", "Stay cozy! \U0001f36f", "Waiting for your next question! \u2728", "Teddy out! \U0001f43e"]
    if "price" in text.lower() or "cost" in text.lower():
        text = "I've sniffed out the best value for you! " + text
    return f"{text}\n\n*{closers[int(time.time()) % len(closers)]}*"

def send_welcome_email(name: str, email: str) -> bool:
    try:
        gmail_user     = os.environ.get("GMAIL_USER")
        gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
        if not gmail_user or not gmail_password:
            logger.error("Missing Gmail credentials")
            return False
        greeting = name if name and name.strip() else "Friend"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Welcome to the CuddleHeros VIP Club \U0001f9f8"
        msg["From"]    = f"Teddy at CuddleHeros <{gmail_user}>"
        msg["To"]      = email
        html = f"""<html><body style="font-family:sans-serif;background:#FFF9F4;padding:20px;">
<div style="max-width:600px;margin:0 auto;background:white;padding:30px;border-radius:20px;">
<div style="text-align:center;font-size:60px;">\U0001f9f8</div>
<h1 style="color:#2D1B00;">Welcome {greeting}!</h1>
<p style="color:#5A3A1B;">Thanks for joining the Honey-Pot!</p>
<div style="background:#FFE4CC;padding:20px;border-radius:12px;text-align:center;margin:20px 0;">
<p style="color:#8B6914;text-transform:uppercase;letter-spacing:2px;">Your Exclusive Voucher</p>
<h2 style="color:#FF922B;font-size:36px;">TEDDY10</h2>
<p style="color:#8B6914;">10% OFF your first order \u2022 Valid 30 days</p>
</div>
<a href="https://cuddleheros.com/shop" style="display:inline-block;background:#FF922B;color:white;padding:16px 40px;border-radius:30px;text-decoration:none;font-weight:600;">Shop the Catalog</a>
<p style="margin-top:30px;color:#8B6914;">Paws and hugs,<br><strong>Teddy \U0001f9f8</strong></p>
</div></body></html>"""
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, email, msg.as_string())
        logger.info(f"Welcome email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return False

def init_session(request: Request):
    if "session_id"    not in request.session: request.session["session_id"]    = str(uuid.uuid4())
    if "chat_history"  not in request.session: request.session["chat_history"]  = []
    if "lead_captured" not in request.session: request.session["lead_captured"] = False

# ---------------------------------------------------------------------------
# Auth passwords (no hardcoded defaults — disabled if env var missing)
# ---------------------------------------------------------------------------
def _safe_password(env_key: str) -> str:
    val = os.environ.get(env_key)
    if not val:
        logger.warning(f"{env_key} not set — access disabled")
        return "__DISABLED__" + os.urandom(16).hex()
    return val

ADMIN_PASSWORD = _safe_password("ADMIN_PASSWORD")
DEV_PASSWORD   = _safe_password("DEV_PASSWORD")

# ---------------------------------------------------------------------------
# Base HTML template (inline, no Jinja2)
# ---------------------------------------------------------------------------
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
@keyframes fadeIn {{ from {{ opacity:0; transform:translateY(10px); }} to {{ opacity:1; transform:translateY(0); }} }}
.fade-in {{ animation: fadeIn 0.3s ease-in; }}
@keyframes float {{ 0%,100% {{ transform:translateY(0); }} 50% {{ transform:translateY(-10px); }} }}
.float-anim {{ animation: float 3s ease-in-out infinite; }}
.chat-wrapper {{ max-height: calc(100vh - 280px); overflow-y: auto; scrollbar-width: thin; scrollbar-color: #FFD5A5 transparent; }}
.chat-wrapper::-webkit-scrollbar {{ width:6px; }}
.chat-wrapper::-webkit-scrollbar-thumb {{ background:#FFD5A5; border-radius:3px; }}
</style>
</head>
<body class="min-h-screen">
{content}
</body>
</html>"""

def render_page(title: str, content: str) -> str:
    return BASE_HTML.format(title=title, content=content)

# ---------------------------------------------------------------------------
# Chat page
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def chat_page(request: Request):
    init_session(request)
    history      = request.session.get("chat_history", [])
    lead_captured = request.session.get("lead_captured", False)
    show_lead    = len(history) >= 2 and not lead_captured

    messages_html = ""
    for msg in history:
        if msg["role"] == "user":
            messages_html += (
                f'<div class="flex justify-end fade-in mb-3">'
                f'<div class="flex items-end gap-2 max-w-[80%] md:max-w-[70%]">'
                f'<div class="bg-gradient-to-br from-[#FF922B] to-[#FF8C42] text-white px-5 py-3 rounded-2xl rounded-br-md shadow-md">'
                f'<p class="text-sm leading-relaxed">{msg["content"]}</p>'
                f'<p class="text-xs opacity-60 text-right mt-1">{msg.get("time","")}</p>'
                f'</div>'
                f'<div class="w-8 h-8 rounded-full bg-[#FF922B] flex items-center justify-center text-white text-sm flex-shrink-0">\U0001f464</div>'
                f'</div></div>'
            )
        else:
            messages_html += (
                f'<div class="flex justify-start fade-in mb-3">'
                f'<div class="flex items-end gap-2 max-w-[80%] md:max-w-[70%]">'
                f'<div class="w-8 h-8 rounded-full bg-[#FFE4CC] flex items-center justify-center text-sm flex-shrink-0">\U0001f9f8</div>'
                f'<div class="bg-white border border-[#FFE4CC] px-5 py-3 rounded-2xl rounded-bl-md shadow-md">'
                f'<p class="text-sm leading-relaxed text-[#2D1B00]">{msg["content"]}</p>'
                f'<p class="text-xs text-[#8B6914] mt-1">{msg.get("time","")}</p>'
                f'</div></div></div>'
            )

    lead_html = ""
    if show_lead:
        lead_html = (
            '<div id="lead-capture" class="bg-gradient-to-br from-[#FFF0E0] to-[#FFE4CC] border-2 border-[#FFD5A5] rounded-2xl p-5 mb-4 fade-in shadow-md">'
            '<div class="flex items-center gap-2 mb-2"><span class="text-xl">\U0001f381</span>'
            '<h3 class="font-bold text-[#2D1B00]">Join the VIP Cuddlers Club!</h3></div>'
            '<p class="text-sm text-[#5A3A1B] mb-4">Get <strong>10% OFF</strong> your first order!</p>'
            '<form hx-post="/lead" hx-target="#lead-capture" hx-swap="outerHTML" class="flex flex-col gap-3">'
            '<input type="text" name="lead_name" placeholder="Your Name" class="w-full px-4 py-3 rounded-xl border border-[#FFD5A5] bg-white focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-[#2D1B00] text-sm">'
            '<input type="email" name="lead_email" placeholder="your@email.com" required class="w-full px-4 py-3 rounded-xl border border-[#FFD5A5] bg-white focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-[#2D1B00] text-sm">'
            '<button type="submit" class="w-full py-3 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42] text-white font-bold shadow-md hover:shadow-lg transition-all text-sm">'
            '\U0001f9f8 Claim My 10% Voucher</button></form></div>'
        )

    quick_qs = [
        ("Pricing \U0001f4b0", "What are your prices?"),
        ("Shipping \U0001f4e6", "How does shipping work?"),
        ("Custom Work \U0001f3a8", "Can I order custom plushies?"),
        ("Safety \u2705", "Are your plushies safe for kids?"),
    ]
    quick_html = ""
    for label, query in quick_qs:
        quick_html += (
            f'<button hx-post="/chat" hx-target="#chat-messages" hx-swap="beforeend" '
            f'hx-vals=\'{{"prompt":"{query}"}}\' '
            f'class="px-4 py-2 rounded-full bg-white border-2 border-[#FFE4CC] text-[#5A3A1B] text-sm font-semibold '
            f'hover:bg-[#FF922B] hover:text-white hover:border-[#FF922B] transition-all shadow-sm">'
            f'{label}</button>'
        )

    content = f"""
<div class="min-h-screen flex flex-col">
  <!-- Header -->
  <div class="bg-gradient-to-r from-[#FF922B] to-[#FF8C42] text-white py-4 px-4 text-center shadow-md sticky top-0 z-10">
    <div class="text-3xl float-anim">\U0001f9f8</div>
    <h1 class="text-xl font-bold">TedPro</h1>
    <p class="text-xs opacity-90">Your Plushie Marketing Assistant</p>
  </div>

  <!-- Main -->
  <div class="flex-1 px-4 py-4 overflow-hidden">
    <div class="max-w-2xl mx-auto flex flex-col h-full">

      <!-- Welcome message -->
      <div class="text-center mb-4">
        <div class="inline-block bg-white rounded-2xl px-5 py-3 shadow-sm border border-[#FFE4CC]">
          <p class="text-[#5A3A1B] text-sm">\U0001f44b Hi! I'm <strong>Teddy</strong> — ask me anything about CuddleHeros plushies!</p>
        </div>
      </div>

      <!-- Quick questions -->
      <div class="flex flex-wrap gap-2 justify-center mb-4">
        {quick_html}
      </div>

      <!-- Chat messages -->
      <div id="chat-messages" class="chat-wrapper flex-1 space-y-1 mb-4">
        {messages_html}
      </div>

      <!-- Lead capture -->
      {lead_html}

      <!-- Input bar -->
      <div class="bg-white rounded-2xl p-3 shadow-lg border border-[#FFE4CC]">
        <form hx-post="/chat" hx-target="#chat-messages" hx-swap="beforeend" class="flex gap-2">
          <input type="text" name="prompt" placeholder="Ask Teddy anything..." required
            class="flex-1 px-4 py-3 rounded-xl border border-[#FFD5A5] bg-[#FFF9F4] focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-[#2D1B00] text-sm">
          <button type="submit"
            class="px-5 py-3 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42] text-white font-bold shadow-md hover:shadow-lg transition-all text-sm">
            Send
          </button>
        </form>
      </div>

      <!-- Clear chat -->
      <div class="text-center mt-2">
        <form action="/chat/clear" method="post">
          <button type="submit" class="text-xs text-[#8B6914] hover:text-[#FF922B] transition-colors">
            \U0001f5d1 Clear Chat
          </button>
        </form>
      </div>

    </div>
  </div>
</div>
"""
    return HTMLResponse(content=render_page("TedPro Assistant", content))


# ---------------------------------------------------------------------------
# Chat POST — returns the user bubble + streaming bot placeholder
# ---------------------------------------------------------------------------
@app.post("/chat", response_class=HTMLResponse)
async def chat_message(request: Request, prompt: str = Form(...)):
    init_session(request)
    history = request.session.get("chat_history", [])
    history.append({"role": "user", "content": prompt, "time": get_teddy_time()})
    request.session["chat_history"] = history
    request.session["last_query"]   = prompt

    user_bubble = (
        f'<div class="flex justify-end fade-in mb-3">'
        f'<div class="flex items-end gap-2 max-w-[80%] md:max-w-[70%]">'
        f'<div class="bg-gradient-to-br from-[#FF922B] to-[#FF8C42] text-white px-5 py-3 rounded-2xl rounded-br-md shadow-md">'
        f'<p class="text-sm leading-relaxed">{prompt}</p>'
        f'<p class="text-xs opacity-60 text-right mt-1">{get_teddy_time()}</p>'
        f'</div>'
        f'<div class="w-8 h-8 rounded-full bg-[#FF922B] flex items-center justify-center text-white text-sm flex-shrink-0">\U0001f464</div>'
        f'</div></div>'
    )

    # Typing indicator + SSE connection
    bot_placeholder = (
        '<div id="bot-response" hx-ext="sse" sse-connect="/chat/stream" sse-swap="message" '
        'class="flex justify-start fade-in mb-3">'
        '<div class="flex items-end gap-2 max-w-[80%] md:max-w-[70%]">'
        '<div class="w-8 h-8 rounded-full bg-[#FFE4CC] flex items-center justify-center text-sm flex-shrink-0">\U0001f9f8</div>'
        '<div class="bg-white border border-[#FFE4CC] px-5 py-3 rounded-2xl rounded-bl-md shadow-md">'
        '<div class="flex items-center gap-1.5">'
        '<div class="w-2 h-2 bg-[#FF922B] rounded-full animate-bounce"></div>'
        '<div class="w-2 h-2 bg-[#FF922B] rounded-full animate-bounce" style="animation-delay:0.15s"></div>'
        '<div class="w-2 h-2 bg-[#FF922B] rounded-full animate-bounce" style="animation-delay:0.3s"></div>'
        '<span class="text-sm text-[#8B6914] italic ml-2">Teddy is thinking...</span>'
        '</div></div></div></div>'
        '<script>document.body.addEventListener("htmx:sseClose",function(){setTimeout(()=>window.location.reload(),400);});</script>'
    )

    return HTMLResponse(content=user_bubble + bot_placeholder)


# ---------------------------------------------------------------------------
# SSE stream — generates Teddy's response token by token
# ---------------------------------------------------------------------------
@app.get("/chat/stream")
async def chat_stream(request: Request):
    init_session(request)
    query = request.session.get("last_query", "")

    async def generate():
        try:
            product_keywords = [
                "have","stock","buy","price","cost","plushie","teddy","bear",
                "unicorn","dinosaur","bunny","custom","order","catalog","shop","available"
            ]
            enhanced_query = query
            if any(kw in query.lower() for kw in product_keywords):
                products = get_engine().search_products(query, max_results=5)
                if products:
                    enhanced_query = query + "\n\n[PRODUCT INFO]\n" + get_engine().format_product_response(products)

            full_response = ""
            for chunk in get_engine().stream_answer(enhanced_query):
                full_response += chunk
                safe = chunk.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                yield f"event: message\ndata: {safe}\n\n"

            final = apply_teddy_vibes(full_response)
            history = request.session.get("chat_history", [])
            history.append({"role": "assistant", "content": final, "time": get_teddy_time()})
            request.session["chat_history"] = history

            # Signal page reload to show saved message
            yield "event: message\ndata: <script>setTimeout(()=>window.location.reload(),400)</script>\n\n"

        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield "event: message\ndata: I'm having trouble connecting right now. Please try again! \U0001f9f8\n\n"
            yield "event: message\ndata: <script>setTimeout(()=>window.location.reload(),600)</script>\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","Connection":"keep-alive","X-Accel-Buffering":"no"}
    )


# ---------------------------------------------------------------------------
# Lead capture
# ---------------------------------------------------------------------------
@app.post("/lead", response_class=HTMLResponse)
async def capture_lead(request: Request, lead_name: str = Form(""), lead_email: str = Form("")):
    init_session(request)
    if not lead_email or "@" not in lead_email:
        return HTMLResponse('<p class="text-red-500 text-sm p-3">Please enter a valid email address.</p>')
    try:
        saved = get_engine().add_lead(lead_name, lead_email, context="main_chat_v5")
        if saved:
            request.session["lead_captured"] = True
            email_ok = send_welcome_email(lead_name, lead_email)
            if email_ok:
                return HTMLResponse('<p class="text-green-600 font-semibold p-3">\u2705 Welcome to the VIP Cuddlers club! Check your inbox! \U0001f381</p>')
            else:
                return HTMLResponse('<p class="text-yellow-600 p-3">\u2705 You\'re in! Email couldn\'t send — check spam or contact us.</p>')
        else:
            return HTMLResponse('<p class="text-red-500 text-sm p-3">\u274c That email might already be registered.</p>')
    except Exception as e:
        logger.error(f"Lead error: {e}")
        return HTMLResponse(f'<p class="text-red-500 text-sm p-3">\u274c Error: {e}</p>')


# ---------------------------------------------------------------------------
# Clear chat
# ---------------------------------------------------------------------------
@app.post("/chat/clear")
async def clear_chat(request: Request):
    request.session["chat_history"] = []
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    if not request.session.get("admin_authenticated"):
        content = (
            '<div class="min-h-screen flex items-center justify-center">'
            '<div class="bg-white p-8 rounded-2xl shadow-lg border border-[#FFE4CC] w-full max-w-sm">'
            '<div class="text-center mb-6"><div class="text-4xl">\U0001f512</div>'
            '<h1 class="text-xl font-bold text-[#2D1B00] mt-2">Admin Access</h1></div>'
            '<form method="post" action="/admin/login" class="space-y-4">'
            '<input type="password" name="password" placeholder="Admin Password" required '
            'class="w-full px-4 py-3 rounded-xl border border-[#FFD5A5] bg-[#FFF9F4] focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-sm">'
            '<button type="submit" class="w-full py-3 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42] text-white font-bold shadow-md text-sm">Login</button>'
            '</form></div></div>'
        )
        return HTMLResponse(content=render_page("Admin Login", content))
    return await _admin_dashboard(request)

@app.post("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["admin_authenticated"] = True
        return RedirectResponse(url="/admin", status_code=303)
    content = (
        '<div class="min-h-screen flex items-center justify-center">'
        '<div class="bg-white p-8 rounded-2xl shadow-lg border border-[#FFE4CC] w-full max-w-sm">'
        '<div class="text-center mb-4"><div class="text-4xl">\U0001f512</div>'
        '<h1 class="text-xl font-bold text-[#2D1B00] mt-2">Admin Access</h1>'
        '<p class="text-red-500 text-sm mt-2">Incorrect password.</p></div>'
        '<form method="post" action="/admin/login" class="space-y-4">'
        '<input type="password" name="password" placeholder="Admin Password" required '
        'class="w-full px-4 py-3 rounded-xl border border-[#FFD5A5] bg-[#FFF9F4] focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-sm">'
        '<button type="submit" class="w-full py-3 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42] text-white font-bold shadow-md text-sm">Try Again</button>'
        '</form></div></div>'
    )
    return HTMLResponse(content=render_page("Admin Login", content))

@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.pop("admin_authenticated", None)
    return RedirectResponse(url="/admin", status_code=303)

async def _admin_dashboard(request: Request):
    try:
        from supabase import create_client
        supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

        leads_count    = len(supabase.table("leads").select("id", count="exact").execute().data)
        conv_count     = len(supabase.table("conversations").select("id", count="exact").execute().data)
        products_count = len(supabase.table("products").select("id", count="exact").execute().data)
        today          = datetime.now().date().isoformat()
        today_leads    = len(supabase.table("leads").select("id").gte("timestamp", today).execute().data)

        leads_data    = supabase.table("leads").select("*").order("timestamp", desc=True).limit(50).execute().data or []
        convs_data    = supabase.table("conversations").select("*").order("created_at", desc=True).limit(20).execute().data or []
        products_data = supabase.table("products").select("*").order("name").execute().data or []

        leads_rows = "".join(
            f'<tr class="border-b border-[#FFE4CC]">'
            f'<td class="px-4 py-2 text-sm text-[#2D1B00]">{l.get("name","")}</td>'
            f'<td class="px-4 py-2 text-sm text-[#2D1B00]">{l.get("email","")}</td>'
            f'<td class="px-4 py-2 text-sm text-[#8B6914]">{str(l.get("timestamp",""))[:10]}</td>'
            f'</tr>'
            for l in leads_data
        )

        convs_rows = "".join(
            f'<tr class="border-b border-[#FFE4CC]">'
            f'<td class="px-4 py-2 text-sm text-[#2D1B00]">{str(c.get("user_message",""))[:60]}...</td>'
            f'<td class="px-4 py-2 text-sm text-[#8B6914]">{str(c.get("created_at",""))[:10]}</td>'
            f'</tr>'
            for c in convs_data
        )

        products_rows = "".join(
            f'<tr class="border-b border-[#FFE4CC]">'
            f'<td class="px-4 py-2 text-sm text-[#2D1B00]">{p.get("name","")}</td>'
            f'<td class="px-4 py-2 text-sm text-[#8B6914]">{p.get("category","")}</td>'
            f'<td class="px-4 py-2 text-sm font-semibold text-[#FF922B]">{p.get("currency","ZAR")} {p.get("price",0):.2f}</td>'
            f'<td class="px-4 py-2 text-sm">{"\u2705" if p.get("in_stock") else "\u274c"}</td>'
            f'</tr>'
            for p in products_data
        )

        def metric(label, value):
            return (
                f'<div class="bg-white p-4 rounded-xl shadow-sm border border-[#FFE4CC]">'
                f'<p class="text-xs text-[#8B6914] uppercase tracking-wide">{label}</p>'
                f'<p class="text-2xl font-bold text-[#FF922B] mt-1">{value}</p>'
                f'</div>'
            )

        def table_section(title, headers, rows):
            ths = "".join(f'<th class="px-4 py-2 text-left text-xs text-[#8B6914] uppercase tracking-wide">{h}</th>' for h in headers)
            return (
                f'<div class="bg-white rounded-xl shadow-sm border border-[#FFE4CC] overflow-hidden mb-6">'
                f'<div class="px-4 py-3 border-b border-[#FFE4CC]"><h2 class="font-bold text-[#2D1B00]">{title}</h2></div>'
                f'<div class="overflow-x-auto"><table class="w-full"><thead class="bg-[#FFF9F4]"><tr>{ths}</tr></thead>'
                f'<tbody>{rows if rows else "<tr><td colspan=\'99\' class=\'px-4 py-4 text-sm text-[#8B6914] text-center\'>No data yet</td></tr>"}</tbody>'
                f'</table></div></div>'
            )

        content = (
            '<div class="min-h-screen bg-[#FFF9F4] p-4">'
            '<div class="max-w-5xl mx-auto">'
            '<div class="flex justify-between items-center mb-6">'
            '<h1 class="text-2xl font-bold text-[#2D1B00]">\U0001f4ca Admin Dashboard</h1>'
            '<a href="/admin/logout" class="text-sm text-[#8B6914] hover:text-[#FF922B] transition-colors">Logout</a>'
            '</div>'
            f'<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">'
            f'{metric("Total Leads", leads_count)}'
            f'{metric("Today\'s Leads", today_leads)}'
            f'{metric("Conversations", conv_count)}'
            f'{metric("Products", products_count)}'
            f'</div>'
            + table_section("Recent Leads", ["Name","Email","Date"], leads_rows)
            + table_section("Recent Conversations", ["Message","Date"], convs_rows)
            + table_section("Products", ["Name","Category","Price","In Stock"], products_rows)
            + '</div></div>'
        )
        return HTMLResponse(content=render_page("Admin Dashboard", content))

    except Exception as e:
        logger.error(f"Admin dashboard error: {e}")
        return HTMLResponse(f'<div class="p-8 text-red-500">Dashboard error: {e}</div>')


# ---------------------------------------------------------------------------
# Dev tools
# ---------------------------------------------------------------------------
@app.get("/dev", response_class=HTMLResponse)
async def dev_page(request: Request):
    if not request.session.get("dev_authenticated"):
        content = (
            '<div class="min-h-screen flex items-center justify-center">'
            '<div class="bg-white p-8 rounded-2xl shadow-lg border border-[#FFE4CC] w-full max-w-sm">'
            '<div class="text-center mb-6"><div class="text-4xl">\U0001f527</div>'
            '<h1 class="text-xl font-bold text-[#2D1B00] mt-2">Dev Tools</h1></div>'
            '<form method="post" action="/dev/login" class="space-y-4">'
            '<input type="password" name="password" placeholder="Dev Password" required '
            'class="w-full px-4 py-3 rounded-xl border border-[#FFD5A5] bg-[#FFF9F4] focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-sm">'
            '<button type="submit" class="w-full py-3 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42] text-white font-bold shadow-md text-sm">Login</button>'
            '</form></div></div>'
        )
        return HTMLResponse(content=render_page("Dev Login", content))
    return await _dev_dashboard(request)

@app.post("/dev/login", response_class=HTMLResponse)
async def dev_login(request: Request, password: str = Form(...)):
    if password == DEV_PASSWORD:
        request.session["dev_authenticated"] = True
        return RedirectResponse(url="/dev", status_code=303)
    content = (
        '<div class="min-h-screen flex items-center justify-center">'
        '<div class="bg-white p-8 rounded-2xl shadow-lg border border-[#FFE4CC] w-full max-w-sm">'
        '<div class="text-center mb-4"><div class="text-4xl">\U0001f527</div>'
        '<h1 class="text-xl font-bold text-[#2D1B00] mt-2">Dev Tools</h1>'
        '<p class="text-red-500 text-sm mt-2">Incorrect password.</p></div>'
        '<form method="post" action="/dev/login" class="space-y-4">'
        '<input type="password" name="password" placeholder="Dev Password" required '
        'class="w-full px-4 py-3 rounded-xl border border-[#FFD5A5] bg-[#FFF9F4] focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-sm">'
        '<button type="submit" class="w-full py-3 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42] text-white font-bold shadow-md text-sm">Try Again</button>'
        '</form></div></div>'
    )
    return HTMLResponse(content=render_page("Dev Login", content))

@app.get("/dev/logout")
async def dev_logout(request: Request):
    request.session.pop("dev_authenticated", None)
    return RedirectResponse(url="/dev", status_code=303)

async def _dev_dashboard(request: Request):
    checks = {
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY"),
        "SUPABASE_URL":       os.environ.get("SUPABASE_URL"),
        "SUPABASE_KEY":       os.environ.get("SUPABASE_KEY"),
        "GMAIL_USER":         os.environ.get("GMAIL_USER"),
        "GMAIL_APP_PASSWORD": os.environ.get("GMAIL_APP_PASSWORD"),
        "ADMIN_PASSWORD":     os.environ.get("ADMIN_PASSWORD"),
        "DEV_PASSWORD":       os.environ.get("DEV_PASSWORD"),
        "SECRET_KEY":         os.environ.get("SECRET_KEY"),
    }
    rows = "".join(
        f'<tr class="border-b border-[#FFE4CC]">'
        f'<td class="px-4 py-2 text-sm font-mono text-[#2D1B00]">{k}</td>'
        f'<td class="px-4 py-2 text-sm">'
        f'{"<span class=\'text-green-600 font-semibold\'>\u2705 Set</span>" if v else "<span class=\'text-red-500 font-semibold\'>\u274c Missing</span>"}'
        f'</td>'
        f'<td class="px-4 py-2 text-xs text-[#8B6914] font-mono">'
        f'{"***" + v[-4:] if v and len(v) > 6 else (v or "")}'
        f'</td>'
        f'</tr>'
        for k, v in checks.items()
    )

    # Supabase connection test
    try:
        from supabase import create_client
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        sb.table("qa_cache").select("id").limit(1).execute()
        db_status = '<span class="text-green-600 font-semibold">\u2705 Connected</span>'
    except Exception as e:
        db_status = f'<span class="text-red-500">\u274c {e}</span>'

    content = (
        '<div class="min-h-screen bg-[#FFF9F4] p-4">'
        '<div class="max-w-3xl mx-auto">'
        '<div class="flex justify-between items-center mb-6">'
        '<h1 class="text-2xl font-bold text-[#2D1B00]">\U0001f527 Dev Tools</h1>'
        '<a href="/dev/logout" class="text-sm text-[#8B6914] hover:text-[#FF922B] transition-colors">Logout</a>'
        '</div>'
        f'<div class="bg-white rounded-xl shadow-sm border border-[#FFE4CC] p-4 mb-4">'
        f'<p class="text-sm text-[#5A3A1B]">Supabase: {db_status}</p>'
        f'</div>'
        '<div class="bg-white rounded-xl shadow-sm border border-[#FFE4CC] overflow-hidden">'
        '<div class="px-4 py-3 border-b border-[#FFE4CC]"><h2 class="font-bold text-[#2D1B00]">Environment Variables</h2></div>'
        '<div class="overflow-x-auto"><table class="w-full">'
        '<thead class="bg-[#FFF9F4]"><tr>'
        '<th class="px-4 py-2 text-left text-xs text-[#8B6914] uppercase">Variable</th>'
        '<th class="px-4 py-2 text-left text-xs text-[#8B6914] uppercase">Status</th>'
        '<th class="px-4 py-2 text-left text-xs text-[#8B6914] uppercase">Preview</th>'
        '</tr></thead>'
        f'<tbody>{rows}</tbody></table></div></div>'
        '</div></div>'
    )
    return HTMLResponse(content=render_page("Dev Tools", content))
