import os
import uuid
import time
import smtplib
import logging
from functools import lru_cache
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import pandas as pd

from hybrid_engine import HybridEngine

# ---------------------------------------------------
# LOGGING
# ---------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------
# APP SETUP
# ---------------------------------------------------
app = FastAPI(title="TedPro Assistant", version="2.0.0")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "tedpro-secret-key-change-in-production")
)

templates = Jinja2Templates(directory="templates")

# Auto-create static directory if missing
os.makedirs("static", exist_ok=True)

# ---------------------------------------------------
# ENGINE INITIALIZATION (lazy - prevents startup crash)
# ---------------------------------------------------
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
        _engine = HybridEngine(
            api_key=api_key,
            supabase_url=sb_url,
            supabase_key=sb_key,
            client_id="tedpro_client"
        )
    return _engine

# ---------------------------------------------------
# HELPERS
# ---------------------------------------------------
LOCAL_OFFSET_HOURS = 2

def get_teddy_time():
    utc_now = datetime.now()
    local_now = utc_now + timedelta(hours=LOCAL_OFFSET_HOURS)
    return local_now.strftime("%H:%M")

def apply_teddy_vibes(text: str) -> str:
    warm_closers = [
        "Paws and hugs, Teddy 🧸",
        "Stay cozy! 🍯",
        "Waiting for your next question! ✨",
        "Teddy out! 🐾"
    ]
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
        <html>
        <body style="font-family:sans-serif;background:#FFF9F4;padding:20px;">
            <div style="max-width:600px;margin:0 auto;background:white;padding:30px;border-radius:20px;">
                <div style="text-align:center;font-size:60px;">🧸</div>
                <h1 style="color:#2D1B00;">Welcome {greeting_name}!</h1>
                <p style="color:#5A3A1B;">Thanks for joining the Honey-Pot! We're excited to help you find your perfect plushie.</p>
                <div style="background:#FFE4CC;padding:20px;border-radius:12px;text-align:center;margin:20px 0;">
                    <p style="color:#8B6914;text-transform:uppercase;letter-spacing:2px;">Your Exclusive Voucher</p>
                    <h2 style="color:#FF922B;font-size:36px;">TEDDY10</h2>
                    <p style="color:#8B6914;">10% OFF your first order</p>
                </div>
                <a href="https://cuddleheros.com/shop" style="display:inline-block;background:#FF922B;color:white;padding:16px 40px;border-radius:30px;text-decoration:none;font-weight:600;">Shop the Catalog 🛍️</a>
                <p style="margin-top:30px;color:#8B6914;">Paws and hugs,<br><strong>Teddy 🧸</strong></p>
            </div>
        </body>
        </html>
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

# ---------------------------------------------------
# SESSION INITIALIZATION
# ---------------------------------------------------
def init_session(request: Request):
    if "session_id" not in request.session:
        request.session["session_id"] = str(uuid.uuid4())
    if "chat_history" not in request.session:
        request.session["chat_history"] = []
    if "lead_captured" not in request.session:
        request.session["lead_captured"] = False

# ---------------------------------------------------
# AUTH
# ---------------------------------------------------
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    logger.warning("ADMIN_PASSWORD not set - admin access disabled")
    ADMIN_PASSWORD = "__DISABLED__" + os.urandom(16).hex()
DEV_PASSWORD = os.environ.get("DEV_PASSWORD")
if not DEV_PASSWORD:
    logger.warning("DEV_PASSWORD not set - dev access disabled")
    DEV_PASSWORD = "__DISABLED__" + os.urandom(16).hex()

# ---------------------------------------------------
# ROUTES - MAIN CHAT
# ---------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def chat_page(request: Request):
    init_session(request)
    chat_history = request.session.get("chat_history", [])
    lead_captured = request.session.get("lead_captured", False)
    show_lead = len(chat_history) >= 2 and not lead_captured
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "chat_history": chat_history,
        "lead_captured": lead_captured,
        "show_lead": show_lead
    })

@app.post("/chat", response_class=HTMLResponse)
async def chat_message(request: Request, prompt: str = Form(...)):
    init_session(request)

    chat_history = request.session.get("chat_history", [])
    chat_history.append({
        "role": "user",
        "content": prompt,
        "time": get_teddy_time()
    })
    request.session["chat_history"] = chat_history
    request.session["last_query"] = prompt

    return templates.TemplateResponse("chat_messages.html", {
        "request": request,
        "chat_history": chat_history,
        "streaming": True
    })

@app.get("/chat/stream")
async def chat_stream(request: Request):
    """SSE endpoint for streaming bot response"""
    init_session(request)
    query = request.session.get("last_query", "")

    async def generate():
        try:
            product_keywords = ['have', 'stock', 'buy', 'price', 'cost', 'plushie', 'teddy', 
                              'bear', 'unicorn', 'dinosaur', 'bunny', 'custom', 'order', 
                              'catalog', 'shop', 'available']
            is_product_query = any(kw in query.lower() for kw in product_keywords)

            enhanced_query = query
            if is_product_query:
                products = get_engine().search_products(query, max_results=5)
                if products:
                    product_context = "\n\n[PRODUCT INFO]\n" + get_engine().format_product_response(products)
                    enhanced_query = query + "\n\n" + product_context

            full_response = ""
            first_chunk = True

            for chunk in get_engine().stream_answer(enhanced_query):
                full_response += chunk
                safe_chunk = chunk.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")

                if first_chunk:
                    # First chunk: open the bot message bubble
                    html = (
                        '<div class="flex justify-start fade-in">'
                        '<div class="flex items-end gap-2 max-w-[70%]">'
                        '<div class="w-9 h-9 rounded-full bg-[#FFE4CC] flex items-center justify-center flex-shrink-0">🧸</div>'
                        '<div class="bg-white border border-[#FFE4CC] px-5 py-4 rounded-2xl rounded-bl-md shadow-md">'
                        f'<p class="text-sm leading-relaxed text-[#2D1B00]">{safe_chunk}</p>'
                    )
                    yield f"event: message\ndata: {html}\n\n"
                    first_chunk = False
                else:
                    # Append to the paragraph
                    yield f"event: message\ndata: {safe_chunk}\n\n"

            # Close the bubble and save
            final = apply_teddy_vibes(full_response)
            final_escaped = final.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            
            close_html = f'<p class="text-xs text-[#8B6914] mt-2">{get_teddy_time()}</p></div></div></div>'
            yield f"event: message\ndata: {close_html}\n\n"

            # Save to session
            chat_history = request.session.get("chat_history", [])
            chat_history.append({
                "role": "assistant",
                "content": final,
                "time": get_teddy_time()
            })
            request.session["chat_history"] = chat_history

            # Close the SSE connection
            yield f"event: message\ndata: <script>setTimeout(()=>window.location.reload(),300)</script>\n\n"

        except Exception as e:
            logger.error(f"Stream error: {e}")
            error_html = (
                '<div class="flex justify-start fade-in">'
                '<div class="flex items-end gap-2 max-w-[70%]">'
                '<div class="w-9 h-9 rounded-full bg-[#FFE4CC] flex items-center justify-center flex-shrink-0">🧸</div>'
                '<div class="bg-white border border-[#FFE4CC] px-5 py-4 rounded-2xl rounded-bl-md shadow-md">'
                '<p class="text-sm text-red-500">I\'m having trouble connecting right now. Please try again! 🧸</p>'
                f'<p class="text-xs text-[#8B6914] mt-2">{get_teddy_time()}</p>'
                '</div></div></div>'
            )
            yield f"event: message\ndata: {error_html}\n\n"
            yield f"event: message\ndata: <script>setTimeout(()=>window.location.reload(),300)</script>\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/lead", response_class=HTMLResponse)
async def capture_lead(
    request: Request,
    lead_name: str = Form(""),
    lead_email: str = Form("")
):
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

# ---------------------------------------------------
# ROUTES - ADMIN
# ---------------------------------------------------
@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    if not request.session.get("admin_authenticated"):
        return templates.TemplateResponse("admin_login.html", {"request": request})
    return await admin_dashboard(request)

@app.post("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["admin_authenticated"] = True
        return await admin_dashboard(request)
    return HTMLResponse("<p class='text-red-500 text-center mt-3'>Incorrect password. Please try again.</p>", status_code=401)

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

        return templates.TemplateResponse("admin.html", {
            "request": request,
            "leads_count": leads_count,
            "today_leads": today_leads,
            "conv_count": conv_count,
            "cache_count": cache_count,
            "products_count": products_count,
            "leads": leads_data,
            "conversations": convs_data,
            "products": products_data,
            "cache": cache_data,
            "now": datetime.now().strftime('%Y-%m-%d %H:%M')
        })
    except Exception as e:
        return HTMLResponse(f"<p class='text-red-500'>Error loading dashboard: {e}</p>")

@app.post("/admin/products/upload")
async def admin_upload_products(request: Request, file: UploadFile = File(...)):
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401)
    try:
        from supabase import create_client
        df = pd.read_csv(file.file)
        sb_url = os.environ.get("SUPABASE_URL")
        sb_key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(sb_url, sb_key)

        supabase.table('products').delete().eq('client_id', 'tedpro_client').execute()

        products = []
        for _, row in df.iterrows():
            product = {
                'client_id': 'tedpro_client',
                'name': str(row.get('name', '')),
                'category': str(row.get('category', '')),
                'price': float(row.get('price', 0)) if pd.notna(row.get('price')) else 0,
                'currency': str(row.get('currency', 'ZAR')),
                'in_stock': bool(row.get('in_stock', True)),
                'description': str(row.get('description', '')),
                'material': str(row.get('material', '')),
                'size_cm': int(row.get('size_cm', 0)) if pd.notna(row.get('size_cm')) else 0,
                'customisable': bool(row.get('customisable', False)),
                'sku': str(row.get('sku', '')),
            }
            products.append(product)

        supabase.table('products').insert(products).execute()
        return HTMLResponse(f"<p class='text-green-600'>✅ {len(products)} products saved!</p>")
    except Exception as e:
        return HTMLResponse(f"<p class='text-red-500'>Error: {e}</p>")

# ---------------------------------------------------
# ROUTES - DEV TOOLS
# ---------------------------------------------------
@app.get("/dev", response_class=HTMLResponse)
async def dev_page(request: Request):
    if not request.session.get("dev_authenticated"):
        return templates.TemplateResponse("dev_login.html", {"request": request})
    return await dev_dashboard(request)

@app.post("/dev/login", response_class=HTMLResponse)
async def dev_login(request: Request, password: str = Form(...)):
    if password == DEV_PASSWORD:
        request.session["dev_authenticated"] = True
        return await dev_dashboard(request)
    return HTMLResponse("<p class='text-red-500 text-center mt-3'>Incorrect password. Please try again.</p>", status_code=401)

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
        "RESEND_API_KEY": "SET ✓" if os.environ.get("RESEND_API_KEY") else "NOT SET",
    }

    return templates.TemplateResponse("dev.html", {
        "request": request,
        "env_vars": env_vars,
        "session_state": dict(request.session)
    })

@app.post("/dev/clear-cache")
async def dev_clear_cache(request: Request):
    if not request.session.get("dev_authenticated"):
        raise HTTPException(status_code=401)
    try:
        from supabase import create_client
        sb_url = os.environ.get("SUPABASE_URL")
        sb_key = os.environ.get("SUPABASE_KEY")
        supabase = create_client(sb_url, sb_key)
        supabase.table('qa_cache').delete().neq('id', '0').execute()
        return HTMLResponse("<p class='text-green-600'>✅ Cache cleared!</p>")
    except Exception as e:
        return HTMLResponse(f"<p class='text-red-500'>Error: {e}</p>")

@app.post("/dev/test-email")
async def dev_test_email(request: Request):
    if not request.session.get("dev_authenticated"):
        raise HTTPException(status_code=401)
    try:
        gmail_user = os.environ.get("GMAIL_USER", "")
        result = send_welcome_email("Test User", gmail_user)
        if result:
            return HTMLResponse("<p class='text-green-600'>✅ Test email sent!</p>")
        return HTMLResponse("<p class='text-red-500'>Failed to send email. Check credentials.</p>")
    except Exception as e:
        return HTMLResponse(f"<p class='text-red-500'>Error: {e}</p>")
