import os
import uuid
import time
import smtplib
import logging
import hashlib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.exception_handlers import http_exception_handler
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from hybrid_engine import HybridEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="TedPro Assistant", version="2.1.0")
app.state.limiter = limiter
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "tedpro-fallback-secret"),
    same_site="none",
    https_only=True,
)

# Static files served via route — no folder needed

# ---------------------------------------------------------------------------
# Engine — lazy init
# ---------------------------------------------------------------------------
_engine = None
_response_store: dict = {}

def get_engine():
    global _engine
    if _engine is None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        sb_url  = os.environ.get("SUPABASE_URL")
        sb_key  = os.environ.get("SUPABASE_KEY")
        missing = [k for k, v in {"OPENROUTER_API_KEY": api_key, "SUPABASE_URL": sb_url, "SUPABASE_KEY": sb_key}.items() if not v]
        if missing:
            raise RuntimeError(f"Missing env vars: {', '.join(missing)}")
        _engine = HybridEngine(api_key=api_key, supabase_url=sb_url, supabase_key=sb_key, client_id=CLIENT_ID)
    return _engine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
LOCAL_OFFSET_HOURS = 2

def get_teddy_time():
    return (datetime.now() + timedelta(hours=LOCAL_OFFSET_HOURS)).strftime("%H:%M")

SHOP_URL      = "https://cuddleheros.co.za"
WHATSAPP_URL  = "https://wa.me/27836205614?text=Hi%20CuddleHeros%2C%20I%20need%20some%20help%20with%20an%20order%20%F0%9F%A7%B8"

# Triggers that suggest customer needs human help
HANDOFF_KEYWORDS = [
    "speak to someone", "talk to someone", "real person", "human",
    "want a human", "want to speak", "want to talk", "get a human",
    "speak to a person", "contact you", "call you", "whatsapp",
    "not sure", "complicated", "complex", "confused",
    "custom order", "bulk order", "corporate", "wedding", "event",
    "complaint", "problem", "wrong", "damaged", "broken",
    "refund", "return", "exchange", "urgent",
]

BUY_KEYWORDS = [
    "how do i order", "how to order", "want to buy", "want to order",
    "how to buy", "where can i buy", "where do i buy", "place an order",
    "how do i purchase", "ready to order", "i'll take",
    "purchase", "checkout", "buy now", "order now",
    "add to cart", "how do i pay", "how to pay",
]

def _strip_urls(text: str) -> str:
    import re as _re2
    text = _re2.sub(r"\[([^\]]+)\]\(https?://[^\)]+\)", r"\1", text)
    text = _re2.sub(r"https?://\S+", "", text)
    return text.strip()


def apply_teddy_vibes(text: str) -> str:
    """Strip AI-generated closers and return clean response. No sign-offs added."""
    import re as _re
    lines = text.strip().split("\n")
    # Remove trailing lines that are sign-offs or filler
    closer_pattern = _re.compile(
        r"(paws|hugs|cozy|happy.shop|feel free|let me know|"
        r"here to help|always here|ready to|excited to|"
        r"stay cozy|waiting for|teddy out|snuggle|"
        r"don.t hesitate|any other|anything else|hope that help)",
        _re.IGNORECASE
    )
    while lines and closer_pattern.search(lines[-1]) and len(lines[-1]) < 80:
        lines.pop()
    text = "\n".join(lines).strip()
    if not text:
        text = "Let me know what you need."
    return text

def maybe_add_shop_cta(query: str, response: str) -> str:
    """Append a shop CTA if the customer is showing buying intent."""
    q = query.lower()
    if any(kw in q for kw in BUY_KEYWORDS):
        cta = (
            "\n\n---\n"
            "\U0001f6d2 **Ready to grab yours?** Head over to "
            f"[cuddleheros.co.za]({SHOP_URL}) to place your order \u2014 "
            "use code **TEDDY10** for 10% off your first order! \U0001f9f8"
        )
        return response + cta
    return response

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
<a href="https://cuddleheros.co.za" style="display:inline-block;background:#FF922B;color:white;padding:16px 40px;border-radius:30px;text-decoration:none;font-weight:600;">Shop the Catalog</a>
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

def _get_supabase():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

def load_history(session_id: str) -> list:
    try:
        sb = _get_supabase()
        rows = (
            sb.table("conversations")
            .select("user_message, bot_response, created_at")
            .eq("session_id", session_id)
            .eq("client_id", CLIENT_ID)
            .order("created_at", desc=False)
            .limit(50)
            .execute()
            .data or []
        )
        history = []
        for r in rows:
            history.append({"role": "user",     "content": r["user_message"], "time": ""})
            history.append({"role": "assistant", "content": r["bot_response"], "time": ""})
        return history
    except Exception as e:
        logger.error(f"load_history error: {e}")
        return []

def save_history_row(session_id: str, user_msg: str, bot_msg: str):
    try:
        sb = _get_supabase()
        sb.table("conversations").insert({
            "session_id":   session_id,
            "user_message": user_msg,
            "bot_response": bot_msg[:2000],
            "created_at":   datetime.now().isoformat(),
            "client_id":    CLIENT_ID,
        }).execute()
    except Exception as e:
        logger.error(f"save_history_row error: {e}")

def init_session(request: Request):
    if "session_id"    not in request.session:
        request.session["session_id"]    = str(uuid.uuid4())
    if "lead_captured" not in request.session:
        request.session["lead_captured"] = False

def _safe_password(env_key: str) -> str:
    val = os.environ.get(env_key)
    if not val:
        logger.warning(f"{env_key} not set — access disabled")
        return "__DISABLED__" + os.urandom(16).hex()
    return val

ADMIN_PASSWORD = _safe_password("ADMIN_PASSWORD")
DEV_PASSWORD   = _safe_password("DEV_PASSWORD")
CLIENT_ID      = os.environ.get("CLIENT_ID", "tedpro_client")

def _esc_html(s) -> str:
    """Escape HTML special chars so content can't break the page structure."""
    return (str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            .replace('"','&quot;'))

def _admin_verified(request: Request) -> bool:
    """Returns True if admin has re-verified password for this sensitive action."""
    return bool(request.session.get("admin_verified"))


# ---------------------------------------------------------------------------
# Stock lookup — used by Teddy to answer "is X in stock?" reliably
# ---------------------------------------------------------------------------
SCARCITY_THRESHOLD = 10  # Teddy mentions qty only when stock is this low or below

def lookup_stock(query: str) -> str | None:
    """
    Direct Supabase product lookup for stock queries.
    Scarcity rule: only reveal quantity to Teddy when <= SCARCITY_THRESHOLD units remain.
    """
    try:
        sb = _get_supabase()
        all_products = sb.table("products").select(
            "name, in_stock, stock_quantity, price, currency, category, size_cm, material, sku"
        ).eq("client_id", CLIENT_ID).execute().data or []

        q = query.lower()
        matches = [
            p for p in all_products
            if any(word in p.get("name", "").lower() for word in q.split() if len(word) > 2)
        ]
        if not matches:
            return None

        lines = []
        for p in matches[:5]:
            in_stk = p.get("in_stock", True)
            qty    = p.get("stock_quantity") or 0

            if not in_stk:
                stock_str = ("Out of stock \u274c — do NOT promise availability, "
                             "suggest the customer check back soon or ask about similar items")
            elif qty > 0 and qty <= SCARCITY_THRESHOLD:
                stock_str = (f"In stock \u2705 — only {qty} left, "
                             "mention this casually to create urgency without being pushy")
            else:
                stock_str = "In stock \u2705 — available, do NOT mention quantity"

            lines.append(
                f"**{p['name']}** ({p.get('category','')}) — "
                f"{p.get('currency','ZAR')} {float(p.get('price',0)):.2f} — {stock_str} — "
                f"Size: {p.get('size_cm','')}cm — {p.get('material','')}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"lookup_stock error: {e}")
        return None

# ---------------------------------------------------------------------------
# FAQ lookup — checks faqs table directly, single source of truth
# qa_cache is bypassed for FAQ answers, faqs table owns them
# ---------------------------------------------------------------------------
def lookup_faq(query: str) -> str | None:
    """
    Check the faqs table for an answer before hitting the AI.
    Only returns active FAQs. Fuzzy-matches on question text.
    Returns the answer string or None if no match.
    """
    try:
        sb = _get_supabase()
        faqs = sb.table("faqs").select("question, answer").eq("client_id", CLIENT_ID).eq("active", True).execute().data or []
        if not faqs:
            return None

        q = query.lower().strip()
        if len(q) < 3:
            return None

        # Exact or near-exact match first
        for faq in faqs:
            fq = faq["question"].lower().strip()
            if fq == q or fq in q or q in fq:
                logger.info(f"FAQ hit: '{faq['question']}'")
                return faq["answer"]

        # Word overlap match — if 60%+ of meaningful words match
        q_words = set(w for w in q.split() if len(w) > 3)
        if q_words:
            best_score = 0
            best_answer = None
            for faq in faqs:
                fq_words = set(w for w in faq["question"].lower().split() if len(w) > 3)
                if not fq_words:
                    continue
                overlap = len(q_words & fq_words) / max(len(q_words), len(fq_words))
                if overlap > best_score:
                    best_score = overlap
                    best_answer = faq["answer"]
            if best_score >= 0.6 and best_answer:
                logger.info(f"FAQ fuzzy hit (score={best_score:.2f})")
                return best_answer

        return None
    except Exception as e:
        logger.error(f"lookup_faq error: {e}")
        return None


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
# Admin JS lives outside BASE_HTML so it is NOT processed by .format()
# and curly braces in the JS are preserved exactly as written.
ADMIN_JS = '<script src="/js/admin"></script>'

BASE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#129528;</text></svg>">
<script src="https://unpkg.com/htmx.org@1.9.12"></script>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
body {{ font-family: 'Quicksand', sans-serif; background: #FFF9F4; }}
@keyframes fadeIn {{ from {{ opacity:0; transform:translateY(8px); }} to {{ opacity:1; transform:translateY(0); }} }}
.fade-in {{ animation: fadeIn 0.3s ease-in; }}
@keyframes float {{ 0%,100% {{ transform:translateY(0); }} 50% {{ transform:translateY(-8px); }} }}
.float-anim {{ animation: float 3s ease-in-out infinite; }}
@keyframes bounce3 {{ 0%,80%,100% {{ transform:translateY(0); }} 40% {{ transform:translateY(-6px); }} }}
.dot1 {{ animation: bounce3 1.2s ease-in-out infinite; }}
.dot2 {{ animation: bounce3 1.2s ease-in-out 0.15s infinite; }}
.dot3 {{ animation: bounce3 1.2s ease-in-out 0.3s infinite; }}
.prose p {{ margin: 0 0 0.5em 0; }}
.prose p:last-child {{ margin-bottom: 0; }}
.prose ul {{ list-style: disc; padding-left: 1.2em; margin: 0.4em 0; }}
.prose ol {{ list-style: decimal; padding-left: 1.2em; margin: 0.4em 0; }}
.prose li {{ margin: 0.2em 0; }}
.prose strong {{ font-weight: 700; color: #2D1B00; }}
.prose em {{ font-style: italic; color: #5A3A1B; }}
.prose code {{ background: #FFF0DB; color: #c7440a; padding: 1px 5px; border-radius: 4px; font-size: 0.85em; }}
.prose h1,.prose h2,.prose h3 {{ font-weight: 700; color: #2D1B00; margin: 0.5em 0 0.25em; }}
.product-row-detail {{ display:none; }}
.product-row-detail.open {{ display:table-row; }}
.stock-toggle {{ cursor:pointer; transition: opacity .15s; }}
.stock-toggle:hover {{ opacity:.75; }}
</style>
<script>
function scrollChat() {{
  var el = document.getElementById('chat-messages');
  if (el) el.scrollTo({{ top: el.scrollHeight, behavior: 'smooth' }});
}}
document.addEventListener('htmx:afterSwap', function(e) {{
  if (e.detail.target && e.detail.target.id === 'chat-messages') {{
    setTimeout(scrollChat, 50);
  }}
}});
document.addEventListener('htmx:afterSettle', function(e) {{
  setTimeout(scrollChat, 100);
}});
</script>
{admin_js}
</head>
<body class="min-h-screen" onload="scrollChat()">
{content}
</body>
</html>"""

def render_page(title: str, content: str, include_admin_js: bool = False) -> str:
    return BASE_HTML.format(
        title=title,
        content=content,
        admin_js=ADMIN_JS if include_admin_js else ""
    )

def error_page(code: int, heading: str, message: str) -> str:
    content = (
        f'<div class="min-h-screen flex items-center justify-center px-4">'
        f'<div class="bg-white rounded-2xl shadow-lg border border-[#FFE4CC] p-10 max-w-md w-full text-center">'
        f'<div class="text-5xl mb-4">\U0001f9f8</div>'
        f'<h1 class="text-2xl font-bold text-[#2D1B00] mb-2">{heading}</h1>'
        f'<p class="text-[#5A3A1B] text-sm mb-6">{message}</p>'
        f'<a href="/" class="inline-block px-6 py-3 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42] '
        f'text-white font-bold shadow-md text-sm hover:shadow-lg transition-all">Back to Teddy</a>'
        f'<p class="text-xs text-[#8B6914] mt-4">Error {code}</p>'
        f'</div></div>'
    )
    return render_page("Oops — TedPro", content)

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return HTMLResponse(
            content=error_page(404, "Page not found", "This page doesn't exist, but Teddy does!"),
            status_code=404
        )
    if exc.status_code == 405:
        return RedirectResponse(url="/", status_code=303)
    return HTMLResponse(
        content=error_page(exc.status_code, "Something went wrong", "An unexpected error occurred. Please try again."),
        status_code=exc.status_code
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}", exc_info=True)
    return HTMLResponse(
        content=error_page(500, "Teddy needs a moment", "Something went wrong on our end. We've been notified and are looking into it."),
        status_code=500
    )

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    if "/chat/response" in str(request.url):
        t = (datetime.now() + timedelta(hours=LOCAL_OFFSET_HOURS)).strftime("%H:%M")
        return HTMLResponse(
            content=bot_bubble(
                "You've been chatting a lot! \U0001f4a4 Teddy can only handle 40 messages per hour to keep things fair. "
                "Take a short break and come back soon! \U0001f9f8",
                t
            ),
            status_code=200
        )
    return HTMLResponse(
        content=error_page(429,
            "Teddy needs a breather \U0001f4a4",
            "You've sent a lot of messages! Teddy is limited to 40 messages per hour. Come back soon!"
        ),
        status_code=429
    )

def user_bubble(text: str, t: str) -> str:
    return (
        f'<div class="flex justify-end fade-in mb-3">'
        f'<div class="flex items-end gap-2 max-w-[85%] md:max-w-[70%]">'
        f'<div class="bg-gradient-to-br from-[#FF922B] to-[#FF8C42] text-white px-4 py-3 rounded-2xl rounded-br-md shadow-md">'
        f'<p class="text-sm leading-relaxed whitespace-pre-wrap">{text}</p>'
        f'<p class="text-xs opacity-60 text-right mt-1">{t}</p>'
        f'</div>'
        f'<div class="w-8 h-8 rounded-full bg-[#FF922B] flex items-center justify-center text-white text-sm flex-shrink-0">\U0001f464</div>'
        f'</div></div>'
    )

def bot_bubble(text: str, t: str) -> str:
    safe_text = text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
    uid = abs(hash(text + t)) % 999999
    return (
        f'<div class="flex justify-start fade-in mb-3">'
        f'<div class="flex items-end gap-2 max-w-[85%] md:max-w-[70%]">'
        f'<div class="w-8 h-8 rounded-full bg-[#FFE4CC] flex items-center justify-center text-sm flex-shrink-0">\U0001f9f8</div>'
        f'<div class="bg-white border border-[#FFE4CC] px-4 py-3 rounded-2xl rounded-bl-md shadow-md">'
        f'<div id="md-{uid}" class="text-sm leading-relaxed text-[#2D1B00] prose prose-sm max-w-none"></div>'
        f'<p class="text-xs text-[#8B6914] mt-1">{t}</p>'
        f'</div></div></div>'
        f'<script>'
        f'(function(){{'
        f'  var el=document.getElementById("md-{uid}");'
        f'  if(el&&window.marked){{'
        f'    el.innerHTML=marked.parse(`{safe_text}`);'
        f'  }} else if(el) {{'
        f'    el.textContent=`{safe_text}`;'
        f'  }}'
        f'  scrollChat();'
        f'}})();'
        f'</script>'
    )

def handoff_bubble() -> str:
    """A WhatsApp CTA bubble injected when human handoff is needed."""
    return (
        '<div class="flex justify-start fade-in mb-3">'
        '<div class="flex items-end gap-2 max-w-[85%] md:max-w-[70%]">'
        '<div class="w-8 h-8 rounded-full bg-[#FFE4CC] flex items-center justify-center text-sm flex-shrink-0">\U0001f9f8</div>'
        '<div class="bg-white border border-[#FFE4CC] px-4 py-3 rounded-2xl rounded-bl-md shadow-md">'
        '<p class="text-sm text-[#2D1B00] mb-3">For this one I\'d love to connect you directly with our team '
        '\U0001f917 They can sort you out properly!</p>'
        '<a href="https://wa.me/27836205614" target="_blank" '
        'class="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl font-bold text-sm text-white shadow-md" '
        'style="background:#25D366">'
        '&#128172; Chat with us on WhatsApp</a>'
        '<p class="text-xs text-[#8B6914] mt-2">Mon\u2013Fri 8am\u20135pm \u2022 Sat 9am\u20131pm</p>'
        '</div></div></div>'
    )


def thinking_bubble() -> str:
    return (
        '<div id="thinking" class="flex justify-start fade-in mb-3">'
        '<div class="flex items-end gap-2">'
        '<div class="w-8 h-8 rounded-full bg-[#FFE4CC] flex items-center justify-center text-sm flex-shrink-0">\U0001f9f8</div>'
        '<div class="bg-white border border-[#FFE4CC] px-4 py-3 rounded-2xl rounded-bl-md shadow-md">'
        '<div class="flex items-center gap-1.5">'
        '<div class="w-2 h-2 bg-[#FF922B] rounded-full dot1"></div>'
        '<div class="w-2 h-2 bg-[#FF922B] rounded-full dot2"></div>'
        '<div class="w-2 h-2 bg-[#FF922B] rounded-full dot3"></div>'
        '<span class="text-xs text-[#8B6914] italic ml-1">Teddy is thinking...</span>'
        '</div></div></div></div>'
        '<div hx-get="/chat/response" hx-trigger="every 1.5s" hx-target="#thinking" hx-swap="outerHTML"></div>'
    )

# ---------------------------------------------------------------------------
# Admin product catalog HTML — expandable rows + live stock toggle
# ---------------------------------------------------------------------------
def _render_product_row(p: dict) -> str:
    pid     = p.get("id", "")
    name    = p.get("name", "")
    cat     = p.get("category", "")
    cur     = p.get("currency", "ZAR")
    price   = float(p.get("price", 0))
    in_stk  = p.get("in_stock", True)
    desc    = p.get("description", "—")
    mat     = p.get("material", "—")
    size    = p.get("size_cm", "—")
    custom  = p.get("customisable", False)
    sku     = p.get("sku", "—")
    qty     = p.get("stock_quantity") or 0

    # Stock badge — HTMX toggle, stopPropagation so it doesn't expand the row
    stk_badge = (
        f'<span id="stk-{pid}" '
        f'hx-post="/admin/products/{pid}/toggle-stock" '
        f'hx-target="#stk-{pid}" '
        f'hx-swap="outerHTML" '
        f'onclick="event.stopPropagation()" '
        f'class="stock-toggle inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold cursor-pointer '
        + (
            'bg-green-100 text-green-700" title="Click to mark out of stock">'
            '\u2705 In stock'
            if in_stk else
            'bg-red-100 text-red-600" title="Click to mark in stock">'
            '\u274c Out of stock'
        )
        + '</span>'
    )

    # Qty — stopPropagation on the whole cell so edit button works independently
    qty_display = (
        f'<span id="qty-display-{pid}" class="font-mono text-sm text-[#2D1B00]">'
        f'{qty} units '
        f'<button onclick="event.stopPropagation();showEditUI(\'{pid}\',{qty})" '
        f'style="font-size:11px;color:#FF922B;text-decoration:underline;background:none;border:none;cursor:pointer">edit</button>'
        f'</span>'
    )

    main_row = (
        f'<tr class="border-b border-[#FFE4CC] hover:bg-[#FFFAF5] cursor-pointer" onclick="toggleRow(\'{pid}\')">'
        f'<td class="px-4 py-3 text-sm font-semibold text-[#2D1B00]">'
        f'<span id="arrow-{pid}" style="display:inline-block;transition:transform .2s;margin-right:6px;font-size:10px;color:#FF922B">&#9654;</span>'
        f'{name}</td>'
        f'<td class="px-4 py-3 text-sm text-[#8B6914]">{cat}</td>'
        f'<td class="px-4 py-3 text-sm text-[#8B6914] font-mono">{sku}</td>'
        f'<td class="px-4 py-3 text-sm font-semibold text-[#FF922B]">{cur} {price:.2f}</td>'
        f'<td class="px-4 py-3 text-sm" onclick="event.stopPropagation()">'
        f'{stk_badge}<br><span class="mt-1 inline-block">{qty_display}</span></td>'
        f'</tr>'
    )

    detail_row = (
        f'<tr id="detail-{pid}" class="product-row-detail bg-[#FFFAF5]">'
        f'<td colspan="5" class="px-6 py-4">'
        f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem">'
        f'<div><p class="text-xs font-semibold text-[#8B6914] uppercase mb-1">Description</p>'
        f'<p class="text-sm text-[#2D1B00]">{desc}</p></div>'
        f'<div><p class="text-xs font-semibold text-[#8B6914] uppercase mb-1">Material</p>'
        f'<p class="text-sm text-[#2D1B00]">{mat}</p>'
        f'<p class="text-xs font-semibold text-[#8B6914] uppercase mb-1 mt-3">Size</p>'
        f'<p class="text-sm text-[#2D1B00]">{size} cm</p></div>'
        f'<div><p class="text-xs font-semibold text-[#8B6914] uppercase mb-1">Customisable</p>'
        f'<p class="text-sm text-[#2D1B00]">{"Yes \U0001f3a8" if custom else "No"}</p>'
        f'<p class="text-xs font-semibold text-[#8B6914] uppercase mb-1 mt-3">SKU</p>'
        f'<p class="text-sm font-mono text-[#2D1B00]">{sku}</p></div>'
        f'</div>'
        f'</td></tr>'
    )

    return main_row + detail_row


# ---------------------------------------------------------------------------
# Upload card — drag-drop CSV uploader
# ---------------------------------------------------------------------------
UPLOAD_CARD = (
    '<div class="bg-white rounded-xl shadow-sm border border-[#FFE4CC] overflow-hidden mb-6">'
    '<div class="px-4 py-3 border-b border-[#FFE4CC] flex justify-between items-center">'
    '<h2 class="font-bold text-[#2D1B00] text-sm">&#128229; Upload Product Catalog</h2>'
    '<a href="/admin/products/template" class="text-xs text-[#FF922B] hover:underline font-semibold">'
    '&#128229; Download CSV Template</a></div>'
    '<div class="p-4">'
    '<div style="display:flex;gap:0;margin-bottom:1rem;border:0.5px solid #FFD5A5;border-radius:10px;overflow:hidden">'
    '<button id="tab-file-btn" onclick="chTab(\'file\')" style="flex:1;padding:8px 12px;font-size:13px;font-weight:600;cursor:pointer;background:#FFF9F4;color:#2D1B00;border:none;font-family:inherit">&#128196; Upload file</button>'
    '<button id="tab-paste-btn" onclick="chTab(\'paste\')" style="flex:1;padding:8px 12px;font-size:13px;font-weight:500;cursor:pointer;background:white;color:#8B6914;border:none;border-left:0.5px solid #FFD5A5;font-family:inherit">&#128203; Paste CSV</button>'
    '</div>'
    '<div id="tab-file-panel">'
    '<div id="cu-drop" onclick="document.getElementById(\'cu-file\').click()" '
    'ondragover="event.preventDefault();this.style.background=\'#FFE4CC\';this.style.borderColor=\'#FF922B\'" '
    'ondragleave="this.style.background=\'#FFF9F4\';this.style.borderColor=\'#FFD5A5\'" '
    'ondrop="cuDrop(event)" '
    'style="border:1.5px dashed #FFD5A5;border-radius:12px;padding:2rem 1.5rem;text-align:center;cursor:pointer;background:#FFF9F4;transition:all .2s">'
    '<div style="font-size:28px;margin-bottom:6px">&#128196;</div>'
    '<div id="cu-dz-title" style="font-size:14px;font-weight:600;color:#2D1B00;margin-bottom:4px">Drop your CSV here, or click to browse</div>'
    '<div id="cu-dz-sub" style="font-size:12px;color:#8B6914">Supports .csv files</div>'
    '</div>'
    '<input type="file" id="cu-file" accept=".csv,text/csv" style="display:none" onchange="if(this.files[0])cuReadFile(this.files[0])">'
    '</div>'
    '<div id="tab-paste-panel" style="display:none">'
    '<p style="font-size:12px;color:#8B6914;margin-bottom:6px">'
    'Required: <code style="background:#FFF0DB;padding:1px 4px;border-radius:4px">name</code>, '
    '<code style="background:#FFF0DB;padding:1px 4px;border-radius:4px">price</code></p>'
    '<textarea id="cu-paste" rows="7" '
    'placeholder="name,category,price,currency,in_stock,description,material,size_cm,customisable,sku" '
    'style="width:100%;padding:10px 12px;border:0.5px solid #FFD5A5;border-radius:10px;background:#FFF9F4;color:#2D1B00;font-family:monospace;font-size:12px;resize:vertical;outline:none"></textarea>'
    '<button onclick="cuParsePaste()" style="margin-top:8px;padding:7px 16px;border-radius:8px;border:0.5px solid #FFD5A5;background:white;color:#2D1B00;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit">&#128202; Preview</button>'
    '</div>'
    '<div id="cu-preview" style="display:none;margin-top:1.25rem">'
    '<div id="cu-stats" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:1rem"></div>'
    '<div id="cu-errors"></div>'
    '<div id="cu-table-wrap" style="border:0.5px solid #FFD5A5;border-radius:10px;overflow:auto;max-height:220px;margin-bottom:1rem"></div>'
    '<div id="cu-confirm" style="display:none">'
    '<div style="background:#FFF0DB;border:0.5px solid #FFD5A5;border-radius:10px;padding:12px 16px;margin-bottom:12px">'
    '<p style="font-size:13px;color:#5A3A1B"><strong style="color:#2D1B00">Replace entire catalog?</strong> '
    'This deletes all existing products and uploads the new ones. Cannot be undone.</p></div>'
    '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
    '<button id="cu-upload-btn" onclick="cuDoUpload()" style="padding:9px 20px;border-radius:8px;background:#FF922B;color:white;border:none;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit">&#9989; Upload &amp; replace catalog</button>'
    '<button onclick="cuReset()" style="padding:9px 16px;border-radius:8px;background:white;color:#2D1B00;border:0.5px solid #FFD5A5;font-size:13px;cursor:pointer;font-family:inherit">Cancel</button>'
    '</div></div>'
    '<div id="cu-progress" style="display:none">'
    '<div style="height:4px;background:#FFE4CC;border-radius:100px;overflow:hidden;margin-bottom:8px">'
    '<div id="cu-bar" style="height:100%;background:#FF922B;border-radius:100px;width:0%;transition:width .3s"></div></div>'
    '<p id="cu-prog-lbl" style="font-size:12px;color:#8B6914">Uploading...</p></div>'
    '<div id="cu-success" style="display:none">'
    '<div style="background:#F0FFF4;border:0.5px solid #86EFAC;border-radius:10px;padding:12px 16px;margin-bottom:8px;display:flex;align-items:center;gap:10px">'
    '<span style="font-size:20px">&#9989;</span>'
    '<p id="cu-success-msg" style="font-size:13px;color:#166534;font-weight:600"></p></div>'
    '<span onclick="cuReset()" style="font-size:12px;color:#8B6914;text-decoration:underline;cursor:pointer">Upload another file</span>'
    '</div>'
    '</div>'
    '</div>'
    '</div>'
    '<script>(function(){'
    'var _csv="",_rows=[];\n'
    'window.chTab=function(t){'
    'var isF=t==="file";'
    'document.getElementById("tab-file-panel").style.display=isF?"":"none";'
    'document.getElementById("tab-paste-panel").style.display=isF?"none":"";'
    'var fb=document.getElementById("tab-file-btn"),pb=document.getElementById("tab-paste-btn");'
    'fb.style.background=isF?"#FFF9F4":"white";fb.style.fontWeight=isF?"600":"500";fb.style.color=isF?"#2D1B00":"#8B6914";'
    'pb.style.background=isF?"white":"#FFF9F4";pb.style.fontWeight=isF?"500":"600";pb.style.color=isF?"#8B6914":"#2D1B00";'
    '};\n'
    'window.cuDrop=function(e){'
    'e.preventDefault();'
    'var dz=document.getElementById("cu-drop");dz.style.background="#FFF9F4";dz.style.borderColor="#FFD5A5";'
    'var f=e.dataTransfer.files[0];if(f)cuReadFile(f);'
    '};\n'
    'window.cuReadFile=function(f){'
    'if(!f.name.match(/\\.csv$/i)){alert("Please upload a .csv file.");return;}'
    'var r=new FileReader();'
    'r.onload=function(e){'
    '_csv=e.target.result;'
    'var dz=document.getElementById("cu-drop");'
    'dz.style.background="#E6FFE6";dz.style.borderColor="#22c55e";dz.style.borderStyle="solid";'
    'document.getElementById("cu-dz-title").textContent=f.name;'
    'document.getElementById("cu-dz-sub").textContent=cuFmtSz(f.size)+" \u2014 ready";'
    'cuParseAndPreview(_csv);'
    '};r.readAsText(f);'
    '};\n'
    'window.cuParsePaste=function(){'
    '_csv=document.getElementById("cu-paste").value.trim();'
    'if(!_csv){alert("Paste some CSV content first.");return;}'
    'cuParseAndPreview(_csv);'
    '};\n'
    'function cuFmtSz(b){return b>1048576?(b/1048576).toFixed(1)+" MB":b>1024?(b/1024).toFixed(0)+" KB":b+" B";}\n'
    'function cuParseCSV(text){'
    'var lines=text.split(/\\r?\\n/).filter(function(l){return l.trim();});'
    'if(!lines.length)return{headers:[],rows:[]};'
    'function spl(l){var r=[],c="",q=false;for(var i=0;i<l.length;i++){if(l[i]==\'"\'){q=!q;}else if(l[i]===","&&!q){r.push(c.trim());c="";}else c+=l[i];}r.push(c.trim());return r;}'
    'var hdrs=spl(lines[0]).map(function(h){return h.replace(/"/g,"").toLowerCase().trim();});'
    'var rows=lines.slice(1).map(function(l){var v=spl(l),o={};hdrs.forEach(function(h,i){o[h]=(v[i]||"").replace(/"/g,"").trim();});return o;});'
    'return{headers:hdrs,rows:rows};'
    '}\n'
    'function cuValidate(rows){'
    'var errs=[],warns=[];'
    'rows.forEach(function(r,i){'
    'var n=i+2;'
    'if(!r.name)errs.push("Row "+n+": missing product name");'
    'if(!r.price||isNaN(parseFloat(r.price)))errs.push("Row "+n+": price missing or not a number"+(r.name?" ("+r.name+")":""));'
    'if(r.price&&parseFloat(r.price)<=0)warns.push("Row "+n+": price is zero or negative"+(r.name?" ("+r.name+")":""));'
    'if(r.size_cm&&isNaN(parseInt(r.size_cm)))warns.push("Row "+n+": size_cm not a number"+(r.name?" ("+r.name+")":""));'
    '});return{errs:errs,warns:warns};'
    '}\n'
    'function cuParseAndPreview(text){'
    'var p=cuParseCSV(text),hdrs=p.headers,rows=p.rows;_rows=rows;'
    'var prev=document.getElementById("cu-preview");prev.style.display="";'
    'document.getElementById("cu-confirm").style.display="none";'
    'document.getElementById("cu-progress").style.display="none";'
    'document.getElementById("cu-success").style.display="none";'
    'if(hdrs.indexOf("name")<0||hdrs.indexOf("price")<0){'
    'document.getElementById("cu-table-wrap").innerHTML=\'<p style="padding:14px;font-size:13px;color:#991b1b">&#9888; CSV must have at minimum a name and price column.</p>\';'
    'document.getElementById("cu-stats").innerHTML="";document.getElementById("cu-errors").innerHTML="";return;'
    '}'
    'var v=cuValidate(rows);'
    'var valid=rows.filter(function(r,i){var n=i+2;return!v.errs.some(function(e){return e.startsWith("Row "+n+":");});});'
    'function sc(num,lbl,col){return\'<div style="background:\'+col+\';border-radius:8px;padding:10px 14px;flex:1;min-width:80px"><div style="font-size:20px;font-weight:600;color:#2D1B00">\'+num+\'</div><div style="font-size:11px;color:#5A3A1B;margin-top:2px">\'+lbl+\'</div></div>\';}'
    'var st=sc(rows.length,"total rows","#FFF0DB")+sc(valid.length,"valid","#E6FFE6");'
    'if(v.errs.length)st+=sc(v.errs.length,"errors","#FEE2E2");'
    'if(v.warns.length)st+=sc(v.warns.length,"warnings","#FEF9C3");'
    'document.getElementById("cu-stats").innerHTML=st;'
    'var el="";'
    'if(v.errs.length||v.warns.length){'
    'el=\'<div style="background:#FEF2F2;border:0.5px solid #FECACA;border-radius:8px;padding:10px 14px;margin-bottom:12px"><ul style="padding-left:14px">\';'
    'v.errs.forEach(function(e){el+=\'<li style="font-size:12px;color:#991b1b;margin-bottom:2px">\'+e+\'</li>\';});'
    'v.warns.forEach(function(w){el+=\'<li style="font-size:12px;color:#92400e;margin-bottom:2px">\'+w+\'</li>\';});'
    'el+="</ul></div>";'
    '}'
    'document.getElementById("cu-errors").innerHTML=el;'
    'var disp=["name","category","price","currency","in_stock","description"];'
    'var cols=disp.filter(function(c){return hdrs.indexOf(c)>-1;});'
    'var cw={name:"28%",category:"16%",price:"13%",currency:"10%",in_stock:"10%",description:"23%"};'
    'var th="<tr>"+cols.map(function(c){return\'<th style="position:sticky;top:0;background:#FFF9F4;padding:7px 10px;text-align:left;font-size:11px;font-weight:600;color:#8B6914;text-transform:uppercase;letter-spacing:.05em;border-bottom:0.5px solid #FFD5A5;white-space:nowrap;width:\'+cw[c]+\'">\'+c+"</th>";}).join("")+"</tr>";'
    'var tb=rows.map(function(r,i){'
    'var n=i+2,hasE=v.errs.some(function(e){return e.startsWith("Row "+n+":");});'
    'return"<tr style=\\"border-bottom:0.5px solid #FFE4CC;"+(hasE?"background:#FEE2E2;":"")+"\\">"+cols.map(function(c){'
    'var val=r[c]||"";'
    'if(c==="in_stock"){var ok=val.toLowerCase()!=="false"&&val!=="0";return\'<td style="padding:7px 10px;font-size:12px"><span style="display:inline-block;padding:2px 7px;border-radius:100px;font-size:10px;font-weight:600;background:\'+(ok?"#DCFCE7":"#FEE2E2")+\';color:\'+(ok?"#166534":"#991b1b")+\'">\'+( ok?"Yes":"No")+"</span></td>";}'
    'if(c==="price"&&val){return\'<td style="padding:7px 10px;font-size:12px;font-weight:600;color:#2D1B00">\'+(r.currency||"ZAR")+" "+parseFloat(val).toFixed(2)+"</td>";}'
    'return\'<td style="padding:7px 10px;font-size:12px;color:#2D1B00;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:0" title="\'+val+\'">\'+val+"</td>";'
    '}).join("")+"</tr>";'
    '}).join("");'
    'document.getElementById("cu-table-wrap").innerHTML=\'<table style="width:100%;border-collapse:collapse;table-layout:fixed"><thead>\'+th+"</thead><tbody>"+tb+"</tbody></table>";'
    'if(valid.length)document.getElementById("cu-confirm").style.display="";'
    '}\n'
    'window.cuDoUpload=function(){'
    'document.getElementById("cu-confirm").style.display="none";'
    'document.getElementById("cu-progress").style.display="";'
    'var bar=document.getElementById("cu-bar"),lbl=document.getElementById("cu-prog-lbl");'
    'lbl.textContent="Uploading "+_rows.length+" products...";bar.style.width="0%";'
    'var prog=0,t=setInterval(function(){prog=Math.min(prog+15,85);bar.style.width=prog+"%";},200);'
    'var fd=new FormData();fd.append("csv_data",_csv);'
    'fetch("/admin/products/upload",{method:"POST",body:fd,credentials:"same-origin"})'
    '.then(function(r){return r.text();})'
    '.then(function(html){'
    'clearInterval(t);bar.style.width="100%";'
    'setTimeout(function(){'
    'document.getElementById("cu-progress").style.display="none";'
    'var isErr=html.indexOf("\\u274c")>-1||html.toLowerCase().indexOf("error")>-1;'
    'if(isErr){document.getElementById("cu-errors").innerHTML=\'<div style="background:#FEF2F2;border:0.5px solid #FECACA;border-radius:8px;padding:10px 14px;margin-bottom:12px"><p style="font-size:12px;color:#991b1b">Server error: \'+html.replace(/<[^>]+>/g,"").trim()+"</p></div>";document.getElementById("cu-confirm").style.display="";}'
    'else{document.getElementById("cu-success").style.display="";document.getElementById("cu-success-msg").textContent=_rows.length+" products uploaded. Refresh to see the updated catalog.";}'
    '},350);'
    '})'
    '.catch(function(e){'
    'clearInterval(t);document.getElementById("cu-progress").style.display="none";'
    'document.getElementById("cu-errors").innerHTML=\'<div style="background:#FEF2F2;border:0.5px solid #FECACA;border-radius:8px;padding:10px 14px;margin-bottom:12px"><p style="font-size:12px;color:#991b1b">Network error: \'+e.message+"</p></div>";'
    'document.getElementById("cu-confirm").style.display="";'
    '});'
    '};\n'
    'window.cuReset=function(){'
    '_csv="";_rows=[];'
    'document.getElementById("cu-preview").style.display="none";'
    'document.getElementById("cu-file").value="";'
    'document.getElementById("cu-paste").value="";'
    'var dz=document.getElementById("cu-drop");'
    'dz.style.background="#FFF9F4";dz.style.borderColor="#FFD5A5";dz.style.borderStyle="dashed";'
    'document.getElementById("cu-dz-title").textContent="Drop your CSV here, or click to browse";'
    'document.getElementById("cu-dz-sub").textContent="Supports .csv files";'
    '};'
    '})();</script>'
)


# ---------------------------------------------------------------------------
# Serve admin JS — avoids needing a static folder entirely
# ---------------------------------------------------------------------------
@app.get("/js/admin")
async def serve_admin_js():
    from fastapi.responses import Response
    js = (
        "function toggleRow(id) {\n"
        "  var el = document.getElementById('detail-' + id);\n"
        "  var arrow = document.getElementById('arrow-' + id);\n"
        "  if (!el) return;\n"
        "  el.classList.toggle('open');\n"
        "  if (arrow) arrow.style.transform = el.classList.contains('open') ? 'rotate(90deg)' : 'rotate(0deg)';\n"
        "}\n"
        "function showEditUI(pid, current) {\n"
        "  var cell = document.getElementById('qty-display-' + pid);\n"
        "  if (!cell) return;\n"
        "  var inp = document.createElement('input');\n"
        "  inp.id = 'qty-input-' + pid;\n"
        "  inp.type = 'number'; inp.min = 0; inp.value = current;\n"
        "  inp.style.cssText = 'width:70px;padding:3px 6px;border:1px solid #FFD5A5;border-radius:6px;font-size:13px';\n"
        "  inp.onclick = function(e){ e.stopPropagation(); };\n"
        "  var saveBtn = document.createElement('button');\n"
        "  saveBtn.textContent = 'Save';\n"
        "  saveBtn.style.cssText = 'margin-left:6px;padding:3px 10px;background:#FF922B;color:white;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer';\n"
        "  saveBtn.onclick = function(e){ e.stopPropagation(); doSave(pid); };\n"
        "  var cancelBtn = document.createElement('button');\n"
        "  cancelBtn.textContent = 'Cancel';\n"
        "  cancelBtn.style.cssText = 'margin-left:4px;padding:3px 8px;background:white;color:#8B6914;border:1px solid #FFD5A5;border-radius:6px;font-size:12px;cursor:pointer';\n"
        "  cancelBtn.onclick = function(e){ e.stopPropagation(); showDisplayUI(pid, current); };\n"
        "  cell.innerHTML = '';\n"
        "  cell.appendChild(inp); cell.appendChild(saveBtn); cell.appendChild(cancelBtn);\n"
        "}\n"
        "function doSave(pid) {\n"
        "  var input = document.getElementById('qty-input-' + pid);\n"
        "  if (!input) return;\n"
        "  var val = parseInt(input.value);\n"
        "  if (isNaN(val) || val < 0) { alert('Please enter a valid number'); return; }\n"
        "  fetch('/admin/products/' + pid + '/update-qty', {\n"
        "    method: 'POST',\n"
        "    headers: {'Content-Type': 'application/x-www-form-urlencoded'},\n"
        "    credentials: 'same-origin',\n"
        "    body: 'qty=' + val\n"
        "  }).then(function(r){ return r.text(); }).then(function(html){\n"
        "    var cell = document.getElementById('qty-display-' + pid);\n"
        "    if (cell) cell.outerHTML = html;\n"
        "  }).catch(function(e){ alert('Save failed: ' + e.message); });\n"
        "}\n"
        "function showDisplayUI(pid, qty) {\n"
        "  var cell = document.getElementById('qty-display-' + pid);\n"
        "  if (!cell) return;\n"
        "  var txt = document.createTextNode(qty + ' units ');\n"
        "  var btn = document.createElement('button');\n"
        "  btn.textContent = 'edit';\n"
        "  btn.style.cssText = 'font-size:11px;color:#FF922B;text-decoration:underline;background:none;border:none;cursor:pointer';\n"
        "  btn.onclick = function(e){ e.stopPropagation(); showEditUI(pid, qty); };\n"
        "  cell.innerHTML = '';\n"
        "  cell.appendChild(txt); cell.appendChild(btn);\n"
        "}\n"
    )
    return Response(content=js, media_type="application/javascript")



# ---------------------------------------------------------------------------
# FAQ CRUD endpoints — Supabase backed, full manager
# ---------------------------------------------------------------------------

def _build_faq_panel() -> str:
    try:
        sb = _get_supabase()
        faqs = sb.table("faqs").select("*").eq("client_id", CLIENT_ID)             .order("category").order("created_at").execute().data or []
    except Exception as e:
        logger.error(f"FAQ fetch error: {e}")
        faqs = []

    def faq_row(f):
        fid    = f.get("id","")
        q      = f.get("question","").replace('"',"&quot;")
        a      = f.get("answer","").replace('"',"&quot;")
        cat    = f.get("category","General") or "General"
        active = f.get("active", True)
        badge  = ('<span style="background:#DCFCE7;color:#166534;padding:2px 8px;border-radius:100px;font-size:10px;font-weight:600">Active</span>'
                  if active else
                  '<span style="background:#FEE2E2;color:#991b1b;padding:2px 8px;border-radius:100px;font-size:10px;font-weight:600">Inactive</span>')
        tlabel = "Deactivate" if active else "Activate"
        return (
            f'<tr id="faq-row-{fid}" class="border-b border-[#FFE4CC] hover:bg-[#FFFAF5]">'
            f'<td class="px-4 py-3 text-xs text-[#8B6914] font-medium whitespace-nowrap">{cat}</td>'
            f'<td class="px-4 py-3 text-sm text-[#2D1B00] font-medium">{_esc_html(f.get("question",""))}</td>'
            f'<td class="px-4 py-3 text-sm text-[#5A3A1B]"><div style="max-height:60px;overflow:hidden">{_esc_html(f.get("answer",""))}</div></td>'
            f'<td class="px-4 py-3">{badge}</td>'
            f'<td class="px-4 py-3"><div style="display:flex;gap:6px;flex-wrap:wrap">'
            f'<button onclick="faqEdit(this)" data-id="{fid}" data-q="{q}" data-a="{a}" data-cat="{cat}" '
            f'style="padding:4px 10px;border-radius:6px;background:#FFF0DB;color:#FF922B;border:none;font-size:11px;font-weight:600;cursor:pointer">Edit</button>'
            f'<button hx-post="/admin/faqs/{fid}/toggle" hx-target="#faq-row-{fid}" hx-swap="outerHTML" '
            f'style="padding:4px 10px;border-radius:6px;background:#F3F4F6;color:#5A3A1B;border:none;font-size:11px;font-weight:600;cursor:pointer">{tlabel}</button>'
            f'<button hx-delete="/admin/faqs/{fid}" hx-target="#faq-row-{fid}" hx-swap="outerHTML" hx-confirm="Delete this FAQ?" '
            f'style="padding:4px 10px;border-radius:6px;background:#FEE2E2;color:#991b1b;border:none;font-size:11px;font-weight:600;cursor:pointer">Delete</button>'
            f'</div></td></tr>'
        )

    rows_html = "".join(faq_row(f) for f in faqs) if faqs else (
        '<tr><td colspan="5" class="px-4 py-8 text-center text-sm text-[#8B6914]">'
        'No FAQs yet — add your first one below &#128071;</td></tr>'
    )
    cat_options = "".join(
        f'<option value="{c}">{c}</option>'
        for c in ["General","Shipping","Payment","Custom Orders","Returns","Safety","Gifting"]
    )
    return (
        '<div class="bg-white rounded-xl shadow-sm border border-[#FFE4CC] overflow-hidden mb-4">'
        '<div class="px-4 py-3 border-b border-[#FFE4CC] flex justify-between items-center">'
        '<h2 class="font-bold text-[#2D1B00] text-sm">&#129504; FAQ Manager '
        f'<span class="ml-2 text-xs font-normal text-[#8B6914]">({len(faqs)} FAQs)</span></h2></div>'
        '<div class="overflow-x-auto"><table class="w-full">'
        '<thead class="bg-[#FFF9F4]"><tr>'
        '<th class="px-4 py-2 text-left text-xs text-[#8B6914] uppercase w-24">Category</th>'
        '<th class="px-4 py-2 text-left text-xs text-[#8B6914] uppercase">Question</th>'
        '<th class="px-4 py-2 text-left text-xs text-[#8B6914] uppercase">Answer</th>'
        '<th class="px-4 py-2 text-left text-xs text-[#8B6914] uppercase w-20">Status</th>'
        '<th class="px-4 py-2 text-left text-xs text-[#8B6914] uppercase w-44">Actions</th>'
        '</tr></thead>'
        f'<tbody id="faq-tbody">{rows_html}</tbody>'
        '</table></div>'
        '<div class="p-4 border-t border-[#FFE4CC] bg-[#FFF9F4]">'
        '<div class="flex justify-between items-center mb-3">'
        '<p class="text-sm font-bold text-[#2D1B00]">&#128229; Bulk Upload FAQs</p>'
        '<a href="/admin/faqs/template" class="text-xs text-[#FF922B] hover:underline font-semibold">&#128229; Download CSV Template</a>'
        '</div>'
        '<p class="text-xs text-[#8B6914] mb-3">CSV format: '
        '<code style="background:#FFF0DB;padding:1px 4px;border-radius:4px">category</code>, '
        '<code style="background:#FFF0DB;padding:1px 4px;border-radius:4px">question</code>, '
        '<code style="background:#FFF0DB;padding:1px 4px;border-radius:4px">answer</code>. '
        'Duplicates skipped automatically.</p>'
        '<div id="faq-bulk-drop" onclick="document.getElementById(\'faq-bulk-file\').click()" '
        'ondragover="event.preventDefault();this.style.background=\'#FFE4CC\'" '
        'ondragleave="this.style.background=\'#FFF9F4\'" '
        'ondrop="faqBulkDrop(event)" '
        'style="border:1.5px dashed #FFD5A5;border-radius:10px;padding:1.5rem;text-align:center;cursor:pointer;background:#FFF9F4;transition:all .2s;margin-bottom:10px">'
        '<div style="font-size:22px;margin-bottom:4px">&#128196;</div>'
        '<div id="faq-bulk-title" style="font-size:13px;font-weight:600;color:#2D1B00">Drop CSV here or click to browse</div>'
        '</div>'
        '<input type="file" id="faq-bulk-file" accept=".csv" style="display:none" onchange="if(this.files[0])faqBulkRead(this.files[0])">'
        '<div id="faq-bulk-result"></div>'
        '</div>'

        '<div class="p-4 border-t border-[#FFE4CC] bg-[#FFFAF5]">'
        '<p id="faq-form-title" class="text-sm font-bold text-[#2D1B00] mb-3">&#10133; Add New FAQ</p>'
        '<input type="hidden" id="faq-edit-id" value="">'
        '<div style="display:grid;grid-template-columns:160px 1fr;gap:12px;margin-bottom:12px">'
        f'<div><label class="text-xs font-semibold text-[#8B6914] uppercase">Category</label>'
        f'<select id="faq-cat" style="width:100%;margin-top:4px;padding:8px 10px;border:0.5px solid #FFD5A5;border-radius:8px;background:white;color:#2D1B00;font-size:13px;font-family:inherit">{cat_options}</select></div>'
        '<div><label class="text-xs font-semibold text-[#8B6914] uppercase">Question</label>'
        '<input id="faq-q" type="text" placeholder="e.g. How long does delivery take?" '
        'style="width:100%;margin-top:4px;padding:8px 10px;border:0.5px solid #FFD5A5;border-radius:8px;background:white;color:#2D1B00;font-size:13px;box-sizing:border-box"></div></div>'
        '<div style="margin-bottom:12px">'
        '<label class="text-xs font-semibold text-[#8B6914] uppercase">Answer</label>'
        '<textarea id="faq-a" rows="3" placeholder="Teddy will use this answer word for word..." '
        'style="width:100%;margin-top:4px;padding:8px 10px;border:0.5px solid #FFD5A5;border-radius:8px;background:white;color:#2D1B00;font-size:13px;resize:vertical;font-family:inherit;box-sizing:border-box"></textarea></div>'
        '<div style="display:flex;gap:8px;align-items:center">'
        '<button onclick="faqSave()" style="padding:9px 20px;border-radius:8px;background:#FF922B;color:white;border:none;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit">Save FAQ</button>'
        '<button onclick="faqClear()" style="padding:9px 16px;border-radius:8px;background:white;color:#2D1B00;border:0.5px solid #FFD5A5;font-size:13px;cursor:pointer;font-family:inherit">Clear</button>'
        '<span id="faq-msg" style="font-size:13px;margin-left:8px"></span></div></div>'
        '<script>'
        'function faqEdit(btn){'
        '  document.getElementById("faq-edit-id").value=btn.dataset.id;'
        '  document.getElementById("faq-q").value=btn.dataset.q;'
        '  document.getElementById("faq-a").value=btn.dataset.a;'
        '  document.getElementById("faq-cat").value=btn.dataset.cat;'
        '  document.getElementById("faq-form-title").innerHTML="&#9998; Edit FAQ";'
        '  document.getElementById("faq-q").scrollIntoView({behavior:"smooth",block:"center"});'
        '}'
        'function faqClear(){'
        '  document.getElementById("faq-edit-id").value="";'
        '  document.getElementById("faq-q").value="";'
        '  document.getElementById("faq-a").value="";'
        '  document.getElementById("faq-form-title").innerHTML="&#10133; Add New FAQ";'
        '  document.getElementById("faq-msg").textContent="";'
        '}'
        'function faqSave(){'
        '  var id=document.getElementById("faq-edit-id").value;'
        '  var q=document.getElementById("faq-q").value.trim();'
        '  var a=document.getElementById("faq-a").value.trim();'
        '  var cat=document.getElementById("faq-cat").value;'
        '  var msg=document.getElementById("faq-msg");'
        '  if(!q||!a){msg.textContent="Question and answer are required.";msg.style.color="#991b1b";return;}'
        '  var url=id?"/admin/faqs/"+id:"/admin/faqs";'
        '  var method=id?"PUT":"POST";'
        '  msg.textContent="Saving...";msg.style.color="#8B6914";'
        '  fetch(url,{method:method,headers:{"Content-Type":"application/x-www-form-urlencoded"},credentials:"same-origin",'
        '  body:"question="+encodeURIComponent(q)+"&answer="+encodeURIComponent(a)+"&category="+encodeURIComponent(cat)})'
        '  .then(function(r){return r.text();}).then(function(html){'
        '    if(id){var row=document.getElementById("faq-row-"+id);if(row)row.outerHTML=html;}'
        '    else{document.getElementById("faq-tbody").insertAdjacentHTML("beforeend",html);}'
        '    msg.textContent="\u2705 Saved!";msg.style.color="#166534";'
        '    faqClear();setTimeout(function(){msg.textContent="";},3000);'
        '  }).catch(function(e){msg.textContent="\u274c "+e.message;msg.style.color="#991b1b";});'
        '}'
        # Re-verify modal + bulk upload JS
        'var _pendingAction=null;'
        'function showVerifyModal(msg,onOk){'
        '  _pendingAction=onOk;'
        '  var d=document.createElement("div");d.id="reverify-modal";'
        '  d.style.cssText="position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999";'
        '  d.innerHTML="<div style=\'background:white;border-radius:16px;padding:28px;max-width:360px;width:90%;text-align:center\'>"'
        '    +"<div style=\'font-size:36px;margin-bottom:8px\'>&#128274;</div>"'
        '    +"<h2 style=\'font-size:16px;font-weight:700;color:#2D1B00;margin-bottom:6px\'>Confirm your identity</h2>"'
        '    +"<p style=\'font-size:13px;color:#5A3A1B;margin-bottom:16px\'>"+msg+"</p>"'
        '    +"<input id=\'verify-pw\' type=\'password\' placeholder=\'Enter admin password\' style=\'width:100%;padding:10px 12px;border:0.5px solid #FFD5A5;border-radius:8px;font-size:13px;box-sizing:border-box;margin-bottom:8px;font-family:inherit\'>"'
        '    +"<div id=\'verify-err\' style=\'font-size:12px;color:#991b1b;margin-bottom:10px;min-height:16px\'></div>"'
        '    +"<div style=\'display:flex;gap:8px;justify-content:center\'>"'
        '    +"<button onclick=\'doVerify()\' style=\'padding:9px 20px;border-radius:8px;background:#FF922B;color:white;border:none;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit\'>Confirm</button>"'
        '    +"<button onclick=\'document.getElementById(\\"reverify-modal\\").remove()\' style=\'padding:9px 16px;border-radius:8px;background:white;color:#2D1B00;border:0.5px solid #FFD5A5;font-size:13px;cursor:pointer;font-family:inherit\'>Cancel</button>"'
        '    +"</div></div>";'
        '  document.body.appendChild(d);'
        '  setTimeout(function(){var i=document.getElementById("verify-pw");if(i){i.focus();i.onkeydown=function(e){if(e.key==="Enter")doVerify();};}},100);'
        '}'
        'function doVerify(){'
        '  var pw=document.getElementById("verify-pw").value;'
        '  fetch("/admin/reverify",{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},credentials:"same-origin",body:"password="+encodeURIComponent(pw)})'
        '  .then(function(r){'
        '    if(r.ok){document.getElementById("reverify-modal").remove();if(_pendingAction)_pendingAction();}'
        '    else{var e=document.getElementById("verify-err");if(e)e.textContent="Incorrect password. Try again.";}'
        '  });'
        '}'
        'var _origFaqSave=faqSave;'
        'faqSave=function(){'
        '  var id=document.getElementById("faq-edit-id").value;'
        '  var lbl=id?"Confirm password to update this FAQ.":"Confirm password to add this FAQ.";'
        '  showVerifyModal(lbl,_origFaqSave);'
        '};'
        'window.faqBulkDrop=function(e){e.preventDefault();var f=e.dataTransfer.files[0];if(f)faqBulkRead(f);};'
        'window.faqBulkRead=function(f){'
        '  if(!f.name.match(/\\.csv$/i)){alert("Please upload a .csv file.");return;}'
        '  var r=new FileReader();'
        '  r.onload=function(ev){'
        '    document.getElementById("faq-bulk-title").textContent=f.name+" \u2014 ready";'
        '    document.getElementById("faq-bulk-drop").style.background="#E6FFE6";'
        '    showVerifyModal("Confirm password to upload "+f.name+".",function(){faqBulkSubmit(ev.target.result);});'
        '  };'
        '  r.readAsText(f);'
        '};'
        'function faqBulkSubmit(csv){'
        '  var res=document.getElementById("faq-bulk-result");'
        '  res.innerHTML="<p style=\'font-size:12px;color:#8B6914\'>Uploading...</p>";'
        '  var fd=new FormData();fd.append("faq_file",csv);'
        '  fetch("/admin/faqs/bulk-upload",{method:"POST",body:fd,credentials:"same-origin"})'
        '  .then(function(r){return r.text();}).then(function(html){res.innerHTML=html;})'
        '  .catch(function(e){res.innerHTML="<p style=\'color:#991b1b;font-size:12px\'>"+e.message+"</p>";});'
        '}'
        '</script>'
        '</div>'
    )


@app.get("/admin/faqs/template")
async def faq_csv_template(request: Request):
    """Download a CSV template for bulk FAQ upload."""
    if not request.session.get("admin_authenticated"):
        return RedirectResponse(url="/admin", status_code=303)
    from fastapi.responses import Response
    csv_content = (
        "category,question,answer\n"
        "Shipping,How long does delivery take?,We deliver nationwide in 3-5 business days. Major cities 2-3 days!\n"
        "Payment,What payment methods do you accept?,We accept EFT credit and debit cards SnapScan and PayFast. All payments secure.\n"
        "Returns,What is your return policy?,Contact us within 48 hours of receiving a damaged item and we arrange a replacement or refund.\n"
        "Safety,Are your plushies safe for kids?,Our plushies are made with non-toxic child-safe materials. Suitable from 12 months and up.\n"
        "General,How do I place an order?,Visit cuddleheros.co.za to browse and order. Use code TEDDY10 for 10 percent off your first order!\n"
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=faqs_template.csv"}
    )


@app.post("/admin/faqs/bulk-upload", response_class=HTMLResponse)
async def bulk_upload_faqs(request: Request, faq_file: str = Form(...)):
    """Accept CSV text with category,question,answer and bulk insert FAQs."""
    if not request.session.get("admin_authenticated"):
        return HTMLResponse("❌ Not authenticated.", status_code=401)
    if not _admin_verified(request):
        return HTMLResponse("❌ Password verification required.", status_code=403)
    try:
        import io, csv as csv_mod
        sb = _get_supabase()
        reader = csv_mod.DictReader(io.StringIO(faq_file.strip()))
        rows   = list(reader)
        if not rows:
            return HTMLResponse("❌ CSV is empty or invalid.")
        headers = {k.lower().strip() for k in rows[0].keys()}
        if "question" not in headers or "answer" not in headers:
            return HTMLResponse("❌ CSV must have at least: question, answer")
        inserted = 0
        skipped  = 0
        for row in rows:
            r   = {k.lower().strip(): v.strip() for k, v in row.items()}
            q   = r.get("question", "").strip()
            a   = r.get("answer",   "").strip()
            cat = r.get("category", "General").strip() or "General"
            if not q or not a:
                skipped += 1
                continue
            existing = sb.table("faqs").select("id").eq("client_id", CLIENT_ID).eq("question", q).execute().data
            if existing:
                skipped += 1
                continue
            sb.table("faqs").insert({
                "client_id": CLIENT_ID,
                "question":  q,
                "answer":    a,
                "category":  cat,
                "active":    True,
            }).execute()
            inserted += 1
        request.session.pop("admin_verified", None)
        skip_msg = f" ({skipped} skipped — duplicates or empty)" if skipped else ""
        return HTMLResponse(
            f'<div style="background:#F0FFF4;border:0.5px solid #86EFAC;border-radius:10px;padding:12px 16px;font-size:13px;color:#166534;font-weight:600">'
            f'✅ {inserted} FAQs uploaded!{skip_msg} '
            f'<a href="/admin" style="color:#FF922B;text-decoration:underline;margin-left:8px">Refresh to see them</a></div>'
        )
    except Exception as e:
        logger.error(f"Bulk FAQ upload error: {e}")
        return HTMLResponse(f"❌ Error: {e}")


@app.post("/admin/faqs", response_class=HTMLResponse)
async def add_faq(request: Request, question: str = Form(...), answer: str = Form(...), category: str = Form("General")):
    if not request.session.get("admin_authenticated"):
        return HTMLResponse("Not authenticated", status_code=401)
    try:
        sb = _get_supabase()
        result = sb.table("faqs").insert({
            "client_id": CLIENT_ID,
            "question":  question.strip(),
            "answer":    answer.strip(),
            "category":  category.strip() or "General",
            "active":    True,
        }).execute()
        fid = result.data[0]["id"]
        q   = question.strip().replace('"', "&quot;")
        a   = answer.strip().replace('"', "&quot;")
        cat = category.strip() or "General"
        request.session.pop("admin_verified", None)
        return HTMLResponse(_faq_row_html(fid, question.strip(), answer.strip(), cat, True))
    except Exception as e:
        logger.error(f"Add FAQ error: {e}")
        return HTMLResponse(f"Error: {e}", status_code=500)


@app.put("/admin/faqs/{faq_id}", response_class=HTMLResponse)
async def update_faq(request: Request, faq_id: str, question: str = Form(...), answer: str = Form(...), category: str = Form("General")):
    if not request.session.get("admin_authenticated"):
        return HTMLResponse("Not authenticated", status_code=401)
    try:
        sb = _get_supabase()
        sb.table("faqs").update({
            "question": question.strip(),
            "answer":   answer.strip(),
            "category": category.strip() or "General",
        }).eq("id", faq_id).execute()
        try:
            get_engine()._save_to_cache(question.strip().lower(), answer.strip())
        except Exception:
            pass
        request.session.pop("admin_verified", None)
        return HTMLResponse(_faq_row_html(faq_id, question.strip(), answer.strip(), category.strip() or "General", True))
    except Exception as e:
        logger.error(f"Update FAQ error: {e}")
        return HTMLResponse(f"Error: {e}", status_code=500)


@app.post("/admin/faqs/{faq_id}/toggle", response_class=HTMLResponse)
async def toggle_faq(request: Request, faq_id: str):
    if not request.session.get("admin_authenticated"):
        return HTMLResponse("Not authenticated", status_code=401)
    try:
        sb  = _get_supabase()
        cur = sb.table("faqs").select("*").eq("id", faq_id).single().execute().data
        if not cur:
            return HTMLResponse("Not found", status_code=404)
        new_active = not cur["active"]
        sb.table("faqs").update({"active": new_active}).eq("id", faq_id).execute()
        return HTMLResponse(_faq_row_html(faq_id, cur["question"], cur["answer"], cur.get("category","General") or "General", new_active))
    except Exception as e:
        logger.error(f"Toggle FAQ error: {e}")
        return HTMLResponse(f"Error: {e}", status_code=500)


@app.delete("/admin/faqs/{faq_id}", response_class=HTMLResponse)
async def delete_faq(request: Request, faq_id: str):
    if not request.session.get("admin_authenticated"):
        return HTMLResponse("Not authenticated", status_code=401)
    try:
        _get_supabase().table("faqs").delete().eq("id", faq_id).execute()
        request.session.pop("admin_verified", None)
        return HTMLResponse("")
    except Exception as e:
        logger.error(f"Delete FAQ error: {e}")
        return HTMLResponse(f"Error: {e}", status_code=500)


def _faq_row_html(fid: str, question: str, answer: str, cat: str, active: bool) -> str:
    q = question.replace('"', "&quot;")
    a = answer.replace('"', "&quot;")
    badge = ('<span style="background:#DCFCE7;color:#166534;padding:2px 8px;border-radius:100px;font-size:10px;font-weight:600">Active</span>'
             if active else
             '<span style="background:#FEE2E2;color:#991b1b;padding:2px 8px;border-radius:100px;font-size:10px;font-weight:600">Inactive</span>')
    tlabel = "Deactivate" if active else "Activate"
    return (
        f'<tr id="faq-row-{fid}" class="border-b border-[#FFE4CC] hover:bg-[#FFFAF5]">'
        f'<td class="px-4 py-3 text-xs text-[#8B6914] font-medium whitespace-nowrap">{cat}</td>'
        f'<td class="px-4 py-3 text-sm text-[#2D1B00] font-medium">{_esc_html(question)}</td>'
        f'<td class="px-4 py-3 text-sm text-[#5A3A1B]"><div style="max-height:60px;overflow:hidden">{_esc_html(answer)}</div></td>'
        f'<td class="px-4 py-3">{badge}</td>'
        f'<td class="px-4 py-3"><div style="display:flex;gap:6px;flex-wrap:wrap">'
        f'<button onclick="faqEdit(this)" data-id="{fid}" data-q="{q}" data-a="{a}" data-cat="{cat}" '
        f'style="padding:4px 10px;border-radius:6px;background:#FFF0DB;color:#FF922B;border:none;font-size:11px;font-weight:600;cursor:pointer">Edit</button>'
        f'<button hx-post="/admin/faqs/{fid}/toggle" hx-target="#faq-row-{fid}" hx-swap="outerHTML" '
        f'style="padding:4px 10px;border-radius:6px;background:#F3F4F6;color:#5A3A1B;border:none;font-size:11px;font-weight:600;cursor:pointer">{tlabel}</button>'
        f'<button hx-delete="/admin/faqs/{fid}" hx-target="#faq-row-{fid}" hx-swap="outerHTML" hx-confirm="Delete this FAQ?" '
        f'style="padding:4px 10px;border-radius:6px;background:#FEE2E2;color:#991b1b;border:none;font-size:11px;font-weight:600;cursor:pointer">Delete</button>'
        f'</div></td></tr>'
    )


# ---------------------------------------------------------------------------
# Chat page — GET /
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def chat_page(request: Request):
    init_session(request)
    session_id    = request.session["session_id"]
    history       = load_history(session_id)
    lead_captured = request.session.get("lead_captured", False)
    # Lead capture — fire when customer has shown real intent:
    # asked about price, product, ordering, or has 4+ exchanges
    LEAD_INTENT_KEYWORDS = [
        'price', 'cost', 'how much', 'order', 'buy', 'purchase',
        'ship', 'deliver', 'custom', 'want', 'get one', 'get it',
        'available', 'stock', 'gift', 'present', 'birthday',
    ]
    has_intent = any(
        any(kw in m.get('content','').lower() for kw in LEAD_INTENT_KEYWORDS)
        for m in history if m.get('role') == 'user'
    )
    show_lead = not lead_captured and (has_intent or len(history) >= 8)

    messages_html = "".join(
        user_bubble(m["content"], m.get("time", "")) if m["role"] == "user"
        else bot_bubble(m["content"], m.get("time", ""))
        for m in history
    )

    lead_html = ""
    if show_lead:
        lead_html = (
            '<div id="lead-capture" class="bg-gradient-to-br from-[#FFF0E0] to-[#FFE4CC] '
            'border-2 border-[#FFD5A5] rounded-2xl p-5 mb-4 fade-in shadow-sm">'
            '<div class="flex items-center gap-2 mb-2">'
            '<span class="text-xl">\U0001f381</span>'
            '<h3 class="font-bold text-[#2D1B00] text-sm">Join the VIP Cuddlers Club!</h3></div>'
            '<p class="text-sm text-[#5A3A1B] mb-3">Get <strong>10% OFF</strong> your first order!</p>'
            '<form hx-post="/lead" hx-target="#lead-capture" hx-swap="outerHTML" class="flex flex-col gap-2">'
            '<input type="text" name="lead_name" placeholder="Your Name" '
            'class="w-full px-3 py-2 rounded-xl border border-[#FFD5A5] bg-white focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-[#2D1B00] text-sm">'
            '<input type="email" name="lead_email" placeholder="your@email.com" required '
            'class="w-full px-3 py-2 rounded-xl border border-[#FFD5A5] bg-white focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-[#2D1B00] text-sm">'
            '<button type="submit" class="w-full py-2 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42] '
            'text-white font-bold shadow-md text-sm">\U0001f9f8 Claim My 10% Voucher</button>'
            '</form>'
            '<div class="mt-3 pt-3 border-t border-[#FFD5A5] text-center">'
            '<p class="text-xs text-[#8B6914] mb-2">Prefer to chat directly?</p>'
            '<a href="https://wa.me/27836205614" target="_blank" '
            'class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white" '
            'style="background:#25D366">&#128172; WhatsApp Us</a>'
            '</div></div>'
        )

    quick_qs = [
        ("Pricing \U0001f4b0", "What are your prices?"),
        ("Shipping \U0001f4e6", "How does shipping work?"),
        ("Custom \U0001f3a8",   "Can I order custom plushies?"),
        ("Safety \u2705",       "Are your plushies safe for kids?"),
    ]
    quick_html = "".join(
        f'<button '
        f'hx-post="/chat" hx-target="#chat-messages" hx-swap="beforeend" '
        f'hx-vals=\'{{"prompt":"{query}"}}\' '
        f'class="px-3 py-2 rounded-full bg-white border-2 border-[#FFE4CC] text-[#5A3A1B] text-xs font-semibold '
        f'hover:bg-[#FF922B] hover:text-white hover:border-[#FF922B] transition-all shadow-sm whitespace-nowrap">'
        f'{label}</button>'
        for label, query in quick_qs
    )

    content = f"""
<div class="min-h-screen flex flex-col max-w-2xl mx-auto">
  <div class="bg-gradient-to-r from-[#FF922B] to-[#FF8C42] text-white py-4 px-4 text-center shadow-md sticky top-0 z-10">
    <div class="text-3xl float-anim">\U0001f9f8</div>
    <h1 class="text-lg font-bold leading-tight">TedPro</h1>
    <p class="text-xs opacity-90">Your CuddleHeros Assistant &#129528;</p>
  </div>
  <div class="flex-1 flex flex-col px-4 pt-4 pb-0 overflow-hidden">
    <div class="text-center mb-3">
      <div class="inline-block bg-white rounded-2xl px-4 py-2 shadow-sm border border-[#FFE4CC]">
        <p class="text-[#5A3A1B] text-xs">\U0001f44b Hi! I'm <strong>Teddy</strong> — ask me anything about CuddleHeros plushies!</p>
      </div>
    </div>
    <div class="flex flex-wrap gap-2 justify-center mb-3">
      {quick_html}
    </div>
    <div id="chat-messages"
         class="flex-1 overflow-y-auto space-y-1 mb-3 pr-1"
         style="max-height: calc(100vh - 320px); scrollbar-width: thin; scrollbar-color: #FFD5A5 transparent;">
      {messages_html}
    </div>
    {lead_html}
    <div class="sticky bottom-0 bg-[#FFF9F4] pt-2 pb-4">
      <div class="bg-white rounded-2xl p-2 shadow-lg border border-[#FFE4CC]">
        <form id="chat-form"
              hx-post="/chat"
              hx-target="#chat-messages"
              hx-swap="beforeend"
              hx-on::after-request="this.reset();"
              class="flex gap-2">
          <input type="text" name="prompt"
                 placeholder="Ask Teddy anything..."
                 required
                 autocomplete="off"
                 class="flex-1 px-4 py-2.5 rounded-xl border border-[#FFD5A5] bg-[#FFF9F4]
                        focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-[#2D1B00] text-sm">
          <button type="submit"
                  class="px-5 py-2.5 rounded-xl bg-gradient-to-r from-[#FF922B] to-[#FF8C42]
                         text-white font-bold shadow-md hover:shadow-lg transition-all text-sm">
            Send
          </button>
        </form>
      </div>
      <div class="text-center mt-2">
        <form action="/chat/clear" method="post" class="inline">
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
# Chat POST
# ---------------------------------------------------------------------------
import re as _re

def _is_gibberish(text: str) -> bool:
    t = text.strip().lower()
    if len(t) < 2:
        return True
    if not any(c.isalpha() for c in t):
        return True
    letters = [c for c in t if c.isalpha()]
    if len(set(letters)) == 1 and len(t) <= 4:
        return True
    vowels = set("aeiouyw")
    if len(letters) >= 5 and not any(v in letters for v in vowels):
        return True
    # Short words with no real question intent
    noise_words = {"ekse", "ey", "yo", "yoh", "eish", "lol", "haha",
                   "hmm", "hm", "ok", "okay", "k", "kk", "sup", "heita",
                   "aweh", "sharp", "sho", "yebo", "nah", "ja", "neh"}
    if t in noise_words:
        return True
    return False

# Expanded stock-aware keywords so Teddy catches more natural queries
PRODUCT_KEYWORDS = [
    "have", "stock", "available", "sold out", "buy", "get", "find",
    "price", "cost", "how much", "cheap", "expensive",
    "plushie", "plush", "teddy", "bear", "unicorn", "dinosaur", "bunny", "dino",
    "custom", "personalise", "personaliz", "order", "catalog", "catalogue", "shop",
    "material", "size", "big", "small", "large", "soft", "safe", "kids", "baby",
    "gift", "present", "birthday",
]

STOCK_KEYWORDS = [
    "in stock", "out of stock", "available", "sold out", "have", "got",
    "still", "stock", "left", "do you sell", "can i get", "can i buy",
]

@app.post("/chat", response_class=HTMLResponse)
async def chat_post(request: Request, prompt: str = Form(...)):
    init_session(request)
    t       = get_teddy_time()
    cleaned = prompt.strip()
    if _is_gibberish(cleaned):
        return HTMLResponse(content=
            user_bubble(cleaned, t) + bot_bubble(
                "Hmm, I didn't quite get that! Try asking me about our plushies, "
                "pricing, shipping, or custom orders. \U0001f9f8",
                t
            )
        )
    session_id = request.session["session_id"]
    _response_store[session_id] = {
        "query":      cleaned,
        "ready":      False,
        "response":   "",
        "time":       t,
        "processing": False,
    }
    return HTMLResponse(content=user_bubble(cleaned, t) + thinking_bubble())


# ---------------------------------------------------------------------------
# Background response — polled every 1.5s
# ---------------------------------------------------------------------------
@app.get("/chat/response", response_class=HTMLResponse)
@limiter.limit("40/hour")
async def chat_response(request: Request):
    init_session(request)
    session_id = request.session["session_id"]
    store = _response_store.get(session_id)

    if not store:
        return HTMLResponse(
            content='<div id="thinking" style="display:none"></div>',
            headers={"HX-Reswap": "delete"}
        )
    if store.get("ready"):
        resp = store["response"]
        t    = store["time"]
        _response_store.pop(session_id, None)
        return HTMLResponse(content=bot_bubble(resp, t))
    if store.get("processing"):
        return HTMLResponse(content="")

    store["processing"] = True
    query = store.get("query", "")
    if not query:
        _response_store.pop(session_id, None)
        return HTMLResponse(
            content='<div id="thinking" style="display:none"></div>',
            headers={"HX-Reswap": "delete"}
        )

    try:
        q_lower = query.lower()
        enhanced_query = query

        # ── 0. Handoff detection — human needed ─────────────────────────
        if any(kw in q_lower for kw in HANDOFF_KEYWORDS):
            faq_ans = lookup_faq(query)  # still check FAQs first
            if not faq_ans:              # no FAQ answer → hand off
                t = get_teddy_time()
                ai_resp = "".join(get_engine().stream_answer(query, chat_history=load_history(session_id)))
                final   = apply_teddy_vibes(ai_resp)
                save_history_row(session_id, query, final)
                store["response"]   = final + "|||HANDOFF|||"
                store["time"]       = t
                store["ready"]      = True
                store["processing"] = False
                return HTMLResponse(content=bot_bubble(final, t) + handoff_bubble())

        # ── 1. FAQ lookup — skip if complaint/context-dependent ───────────
        _SUPPORT = [
            "not working", "doesn't work", "cant", "can't", "wont", "won't",
            "error", "problem", "issue", "broken", "failed", "wrong",
            "didn't", "didnt", "still ", "again", "already", " it ",
            "that ", "this ", "the one", "my order",
        ]
        _skip_faq = any(s in q_lower for s in _SUPPORT)
        faq_answer = None if _skip_faq else lookup_faq(query)
        if faq_answer:
            final  = apply_teddy_vibes(faq_answer)
            t      = get_teddy_time()
            save_history_row(session_id, query, final)
            store["response"]   = final
            store["time"]       = t
            store["ready"]      = True
            store["processing"] = False
            return HTMLResponse(content=bot_bubble(final, t))

        # ── 2. Stock direct lookup ────────────────────────────────────────
        is_stock_query = any(kw in q_lower for kw in STOCK_KEYWORDS)
        if is_stock_query:
            stock_info = lookup_stock(query)
            if stock_info:
                enhanced_query = (
                    query
                    + "\n\n[LIVE STOCK DATA — use this to answer accurately]\n"
                    + stock_info
                )

        # ── 3. Product context for general product queries ────────────────
        elif any(kw in q_lower for kw in PRODUCT_KEYWORDS) or any(
            kw in q_lower for kw in ["rainbow","giant","mini","snuggle","gentle","large","soft"]
        ):
            try:
                sb_p = _get_supabase()
                all_prods = sb_p.table("products").select(
                    "name,price,currency,in_stock,stock_quantity,description,size_cm,material,customisable,category"
                ).eq("client_id", CLIENT_ID).execute().data or []
                terms = set(w.lower() for w in query.split() if len(w) > 2)
                for m in reversed((chat_history or [])[-3:]):
                    if m.get("role") == "user":
                        for w in m.get("content","").split():
                            if len(w) > 2: terms.add(w.lower())
                        break
                matched = [p for p in all_prods if any(
                    t in p.get("name","").lower() or t in p.get("category","").lower() for t in terms
                )]
                if not matched: matched = all_prods
                if matched:
                    lines = []
                    for p in matched[:5]:
                        stk = "In stock" if p.get("in_stock") else "Out of stock"
                        lines.append(
                            f"{p['name']} | ZAR {float(p.get('price') or 0):.2f} | {stk} | "
                            f"Size: {p.get('size_cm','?')}cm | {p.get('material','')}"
                        )
                    enhanced_query = (
                        query
                        + "\n\n[PRODUCT INFO — use ONLY these exact prices, do not invent details]\n"
                        + "\n".join(lines)
                        + "\n[END PRODUCT INFO]"
                    )
            except Exception as _e:
                logger.error(f"Product lookup error: {_e}")

        history_for_context = load_history(session_id)
        history_for_context.append({"role": "user", "content": query})

        full_response = "".join(get_engine().stream_answer(enhanced_query, chat_history=history_for_context))
        full_response = _strip_urls(full_response)
        final = apply_teddy_vibes(full_response)
        t     = get_teddy_time()

        save_history_row(session_id, query, final)

        store["response"]   = final
        store["time"]       = t
        store["ready"]      = True
        store["processing"] = False

        return HTMLResponse(content=bot_bubble(final, t))

    except Exception as e:
        logger.error(f"chat_response error: {e}")
        _response_store.pop(session_id, None)
        t = get_teddy_time()
        return HTMLResponse(content=bot_bubble(
            "I\'m having trouble connecting right now. Please try again! \U0001f9f8", t
        ))


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
                return HTMLResponse(
                    '<p class="text-green-600 font-semibold p-3 text-sm">'
                    '\u2705 Welcome to the VIP Cuddlers club! Check your inbox! \U0001f381</p>'
                )
            return HTMLResponse(
                '<p class="text-yellow-600 p-3 text-sm">'
                '\u2705 You\'re in! Email couldn\'t send — check spam or contact us.</p>'
            )
        return HTMLResponse('<p class="text-red-500 text-sm p-3">\u274c That email might already be registered.</p>')
    except Exception as e:
        logger.error(f"Lead error: {e}")
        return HTMLResponse(f'<p class="text-red-500 text-sm p-3">\u274c Error: {e}</p>')


# ---------------------------------------------------------------------------
# Clear chat
# ---------------------------------------------------------------------------
@app.post("/chat/clear")
async def clear_chat(request: Request):
    session_id = request.session.get("session_id", "")
    if session_id:
        try:
            sb = _get_supabase()
            sb.table("conversations").delete().eq("session_id", session_id).eq("client_id", CLIENT_ID).execute()
        except Exception as e:
            logger.error(f"Clear chat Supabase error: {e}")
    _response_store.pop(session_id, None)
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# Admin — login helpers
# ---------------------------------------------------------------------------
def _login_page(icon: str, title: str, action: str, error: str = "") -> str:
    err_html = f'<p class="text-red-500 text-sm mt-2">{error}</p>' if error else ""
    return (
        '<div class="min-h-screen flex items-center justify-center">'
        '<div class="bg-white p-8 rounded-2xl shadow-lg border border-[#FFE4CC] w-full max-w-sm">'
        f'<div class="text-center mb-6"><div class="text-4xl">{icon}</div>'
        f'<h1 class="text-xl font-bold text-[#2D1B00] mt-2">{title}</h1>{err_html}</div>'
        f'<form method="post" action="{action}" class="space-y-4">'
        '<input type="password" name="password" placeholder="Password" required '
        'class="w-full px-4 py-3 rounded-xl border border-[#FFD5A5] bg-[#FFF9F4] '
        'focus:outline-none focus:ring-2 focus:ring-[#FF922B] text-sm">'
        '<button type="submit" class="w-full py-3 rounded-xl bg-gradient-to-r from-[#FF922B] '
        'to-[#FF8C42] text-white font-bold shadow-md text-sm">Login</button>'
        '</form></div></div>'
    )


# ---------------------------------------------------------------------------
# Admin — update stock quantity inline
# ---------------------------------------------------------------------------
@app.post("/admin/products/{product_id}/update-qty", response_class=HTMLResponse)
async def update_qty(request: Request, product_id: str, qty: int = Form(...)):
    if not request.session.get("admin_authenticated"):
        return HTMLResponse("Not authenticated", status_code=401)
    try:
        sb = _get_supabase()
        sb.table("products").update({"stock_quantity": qty}).eq("id", product_id).execute()
        logger.info(f"Product {product_id} qty updated to {qty}")
        # Return the updated qty display span so HTMX swaps it in place
        return HTMLResponse(
            f'<span id="qty-display-{product_id}" class="font-mono text-sm text-[#2D1B00]">'
            f'{qty} units '
            f'<button onclick="event.stopPropagation();showEditUI(\'{product_id}\',{qty})" '
            f'style="font-size:11px;color:#FF922B;text-decoration:underline;background:none;border:none;cursor:pointer">edit</button>'
            f'</span>'
        )
    except Exception as e:
        logger.error(f"update_qty error: {e}")
        return HTMLResponse(f"Error: {e}", status_code=500)


# ---------------------------------------------------------------------------
# Admin — live stock toggle  (HTMX POSTs here, returns updated badge)
# ---------------------------------------------------------------------------
@app.post("/admin/products/{product_id}/toggle-stock", response_class=HTMLResponse)
async def toggle_stock(request: Request, product_id: str):
    if not request.session.get("admin_authenticated"):
        return HTMLResponse("Not authenticated", status_code=401)
    try:
        sb = _get_supabase()
        current = sb.table("products").select("in_stock").eq("id", product_id).single().execute().data
        if not current:
            return HTMLResponse("Product not found", status_code=404)
        new_val = not current["in_stock"]
        sb.table("products").update({"in_stock": new_val}).eq("id", product_id).execute()
        logger.info(f"Product {product_id} stock toggled to {new_val}")

        # Return just the updated badge — HTMX swaps it in place
        if new_val:
            return HTMLResponse(
                f'<span id="stk-{product_id}" '
                f'hx-post="/admin/products/{product_id}/toggle-stock" '
                f'hx-target="#stk-{product_id}" hx-swap="outerHTML" '
                f'class="stock-toggle inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold '
                f'bg-green-100 text-green-700" title="Click to mark out of stock">'
                f'\u2705 In stock</span>'
            )
        else:
            return HTMLResponse(
                f'<span id="stk-{product_id}" '
                f'hx-post="/admin/products/{product_id}/toggle-stock" '
                f'hx-target="#stk-{product_id}" hx-swap="outerHTML" '
                f'class="stock-toggle inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold '
                f'bg-red-100 text-red-600" title="Click to mark in stock">'
                f'\u274c Out of stock</span>'
            )
    except Exception as e:
        logger.error(f"toggle_stock error: {e}")
        return HTMLResponse(f"Error: {e}", status_code=500)


# ---------------------------------------------------------------------------
# Admin — product upload
# ---------------------------------------------------------------------------
@app.post("/admin/products/upload", response_class=HTMLResponse)
async def upload_products(request: Request, csv_data: str = Form(...)):
    if not request.session.get("admin_authenticated"):
        return HTMLResponse('\u274c Not authenticated.', status_code=401)
    try:
        import io, csv as csv_mod
        sb = _get_supabase()

        reader = csv_mod.DictReader(io.StringIO(csv_data.strip()))
        rows = list(reader)
        if not rows:
            return HTMLResponse('\u274c CSV is empty or invalid.')

        required = {"name", "price"}
        if not required.issubset({c.lower().strip() for c in rows[0].keys()}):
            return HTMLResponse('\u274c CSV must have at least: name, price')

        def sv(val, default=""):
            v = val if val is not None else default
            return str(v).strip() if str(v).strip() != "" else str(default).strip()

        products = []
        for row in rows:
            r = {k.lower().strip(): v for k, v in row.items()}
            try:
                price = float(sv(r.get("price"), "0") or "0")
            except (ValueError, TypeError):
                price = 0.0
            try:
                size_cm = int(float(sv(r.get("size_cm"), "0") or "0"))
            except (ValueError, TypeError):
                size_cm = 0
            in_stock     = sv(r.get("in_stock"),    "true").lower()  not in ("false", "0", "no")
            customisable = sv(r.get("customisable"), "false").lower() in  ("true",  "1", "yes")
            try:
                stock_quantity = int(float(sv(r.get("stock_quantity"), "0") or "0"))
            except (ValueError, TypeError):
                stock_quantity = 0

            products.append({
                "client_id":      CLIENT_ID,
                "name":           sv(r.get("name")),
                "category":       sv(r.get("category")),
                "price":          price,
                "currency":       sv(r.get("currency"), "ZAR"),
                "in_stock":       in_stock,
                "description":    sv(r.get("description")),
                "material":       sv(r.get("material")),
                "size_cm":        size_cm,
                "customisable":   customisable,
                "sku":            sv(r.get("sku")),
                "stock_quantity": stock_quantity,
            })

        # Fetch existing IDs first — insert new, then delete old safely
        existing = sb.table("products").select("id").eq("client_id", CLIENT_ID).execute().data or []
        existing_ids = [row["id"] for row in existing]
        sb.table("products").insert(products).execute()
        if existing_ids:
            sb.table("products").delete().in_("id", existing_ids).execute()

        request.session.pop("admin_verified", None)
        return HTMLResponse(f'\u2705 {len(products)} products uploaded successfully.')
    except Exception as e:
        logger.error(f"Product upload error: {e}")
        return HTMLResponse(f'\u274c Upload error: {e}')


@app.get("/admin/products/template")
async def download_template(request: Request):
    if not request.session.get("admin_authenticated"):
        return RedirectResponse(url="/admin", status_code=303)
    csv_content = (
        "name,category,price,currency,in_stock,stock_quantity,description,material,size_cm,customisable,sku\n"
        "Gentle Giant Teddy,Bears,349.00,ZAR,true,50,Large teddy bear for big hugs,Premium Cotton,50,true,CHB-001\n"
        "Rainbow Unicorn,Unicorns,379.00,ZAR,true,30,Pastel unicorn with shimmering mane,Satin-finish Plush,40,true,CHU-001\n"
    )
    from fastapi.responses import Response
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=products_template.csv"}
    )


# ---------------------------------------------------------------------------
# Admin — dashboard
# ---------------------------------------------------------------------------
@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    if not request.session.get("admin_authenticated"):
        return HTMLResponse(content=render_page("Admin Login", _login_page("\U0001f512", "Admin Access", "/admin/login"), include_admin_js=True))
    return await _admin_dashboard(request)

@app.get("/admin/conversations/rows", response_class=HTMLResponse)
async def conversations_rows(request: Request):
    """Return just the conversation table rows — loaded async so content can't break the page."""
    if not request.session.get("admin_authenticated"):
        return HTMLResponse("Not authenticated", status_code=401)
    try:
        sb = _get_supabase()
        convs = sb.table("conversations").select("*").eq("client_id", CLIENT_ID).order("created_at", desc=True).limit(50).execute().data or []
        if not convs:
            return HTMLResponse('<tr><td colspan="4" class="px-4 py-4 text-sm text-center text-[#8B6914]">No conversations yet</td></tr>')
        parts = []
        for c in convs:
            sid  = str(c.get('session_id',''))[:8].replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            umsg = str(c.get('user_message',''))[:80].replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            bresp = str(c.get('bot_response',''))[:80].replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            cdate = str(c.get('created_at',''))[:10]
            parts.append(
                f'<tr class="border-b border-[#FFE4CC] hover:bg-[#FFFAF5]">'
                f'<td class="px-4 py-3 text-xs font-mono text-[#8B6914]">{sid}</td>'
                f'<td class="px-4 py-3 text-sm text-[#2D1B00]">{umsg}</td>'
                f'<td class="px-4 py-3 text-sm text-[#5A3A1B]">{bresp}...</td>'
                f'<td class="px-4 py-3 text-xs text-[#8B6914] whitespace-nowrap">{cdate}</td></tr>'
            )
        return HTMLResponse("".join(parts))
    except Exception as e:
        logger.error(f"conversations_rows error: {e}")
        return HTMLResponse(f'<tr><td colspan="4" class="px-4 py-4 text-sm text-center text-red-500">Error loading: {e}</td></tr>')


@app.get("/admin/data", response_class=HTMLResponse)
async def admin_data(request: Request):
    """Plain, dependency-free view of leads + conversations. Always works."""
    if not request.session.get("admin_authenticated"):
        return RedirectResponse(url="/admin", status_code=303)
    try:
        sb = _get_supabase()
        E = _esc_html
        leads = sb.table("leads").select("*").order("timestamp", desc=True).limit(100).execute().data or []
        convs = sb.table("conversations").select("*").eq("client_id", CLIENT_ID).order("created_at", desc=True).limit(100).execute().data or []

        h = ["<!DOCTYPE html><html><head><meta charset='utf-8'><title>TedPro Data</title>",
             "<style>body{font-family:sans-serif;background:#FFF9F4;color:#2D1B00;padding:24px}",
             "table{border-collapse:collapse;width:100%;background:white;margin-bottom:32px}",
             "th,td{border:1px solid #FFE4CC;padding:8px 12px;text-align:left;font-size:13px;vertical-align:top}",
             "th{background:#FFF0DB;text-transform:uppercase;font-size:11px;color:#8B6914}",
             "h1{font-size:20px} h2{font-size:16px;color:#8B6914}",
             "a{color:#FF922B}</style></head><body>",
             "<h1>&#129528; TedPro Data <a href='/admin' style='font-size:13px'>back to dashboard</a> ",
             "<a href='/admin/conversations/export' style='font-size:13px'>export CSV</a></h1>"]

        h.append(f"<h2>Leads ({len(leads)})</h2><table><tr><th>Name</th><th>Email</th><th>Date</th></tr>")
        for l in leads:
            h.append("<tr><td>" + E(l.get("name","")) + "</td><td>" + E(l.get("email","")) +
                     "</td><td>" + E(str(l.get("timestamp",""))[:16]) + "</td></tr>")
        h.append("</table>")

        h.append(f"<h2>Conversations ({len(convs)})</h2><table><tr><th>Session</th><th>Customer</th><th>Teddy</th><th>Date</th></tr>")
        for c in convs:
            h.append("<tr><td style='font-family:monospace'>" + E(str(c.get("session_id",""))[:8]) +
                     "</td><td>" + E(str(c.get("user_message",""))[:200]) +
                     "</td><td>" + E(str(c.get("bot_response",""))[:200]) +
                     "</td><td style='white-space:nowrap'>" + E(str(c.get("created_at",""))[:16]) + "</td></tr>")
        h.append("</table></body></html>")
        return HTMLResponse("".join(h))
    except Exception as e:
        return HTMLResponse(f"<pre>data page error: {e}</pre>")


@app.get("/admin/conversation/{session_id}", response_class=HTMLResponse)
async def view_conversation(request: Request, session_id: str):
    """Return full conversation history for a session as HTML panel."""
    if not request.session.get("admin_authenticated"):
        return HTMLResponse("Not authenticated", status_code=401)
    try:
        sb = _get_supabase()
        rows = sb.table("conversations").select("user_message,bot_response,created_at")             .eq("session_id", session_id).eq("client_id", CLIENT_ID)             .order("created_at", desc=False).limit(100).execute().data or []
        E = _esc_html
        bubbles = []
        for r in rows:
            t = str(r.get("created_at",""))[:16].replace("T"," ")
            umsg = E(r.get("user_message",""))
            bresp = E(r.get("bot_response",""))
            bubbles.append(
                f"<div style='margin-bottom:16px'>"
                f"<div style='display:flex;justify-content:flex-end;margin-bottom:6px'>"
                f"<div style='background:#FF922B;color:white;padding:10px 14px;border-radius:16px 16px 4px 16px;max-width:75%;font-size:13px'>"
                f"{umsg}<div style='font-size:10px;opacity:.7;margin-top:4px;text-align:right'>{t}</div></div></div>"
                f"<div style='display:flex;justify-content:flex-start'>"
                f"<div style='background:white;border:1px solid #FFE4CC;padding:10px 14px;border-radius:16px 16px 16px 4px;max-width:75%;font-size:13px;color:#2D1B00'>"
                f"🧸 {bresp}<div style='font-size:10px;color:#8B6914;margin-top:4px'>{t}</div></div></div>"
                f"</div>"
            )
        content = "".join(bubbles) if bubbles else "<p style='color:#8B6914;text-align:center;padding:2rem'>No messages found.</p>"
        sid_short = E(session_id[:8])
        return HTMLResponse(
            f"<div style='padding:16px'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid #FFE4CC'>"
            f"<span style='font-weight:700;color:#2D1B00;font-size:14px'>&#128172; Session {sid_short}...</span>"
            f"<span style='font-size:12px;color:#8B6914'>{len(rows)} messages</span></div>"
            f"{content}</div>"
        )
    except Exception as e:
        return HTMLResponse(f"<p style='color:red;padding:1rem'>Error: {_esc_html(str(e))}</p>")


@app.get("/admin/selftest", response_class=HTMLResponse)
async def admin_selftest(request: Request):
    """Server inspects its own dashboard output — plain-text diagnostic."""
    if not request.session.get("admin_authenticated"):
        return RedirectResponse(url="/admin", status_code=303)
    try:
        resp = await _admin_dashboard(request)
        html = resp.body.decode()
        lines = [f"status: {resp.status_code}", f"total HTML: {len(html)} chars", ""]
        for marker in ["panel-leads", "panel-products", "panel-faqs", "panel-conversations",
                       "function showPanel", "All Leads", "Recent Conversations",
                       "margin-top:1.5rem", "</body>"]:
            pos = html.find(marker)
            lines.append(f"{marker}: {('FOUND at char ' + str(pos)) if pos >= 0 else 'MISSING'}")
        if "panel-conversations" in html:
            seg = html[html.find("panel-conversations"):]
            lines.append(f"rows in conversations panel: {seg[:20000].count('<tr')}")
        if "panel-leads" in html:
            seg = html[html.find("panel-leads"):]
            lines.append(f"rows in leads panel: {seg[:5000].count('<tr')}")
        return HTMLResponse("<pre style='padding:20px;font-size:13px'>" + "\n".join(lines) + "</pre>")
    except Exception as e:
        return HTMLResponse(f"<pre>SELFTEST ERROR: {e}</pre>")


@app.get("/admin/conversations/export")
async def export_conversations(request: Request):
    """Download all conversations as CSV."""
    if not request.session.get("admin_authenticated"):
        return RedirectResponse(url="/admin", status_code=303)
    try:
        import io, csv as csv_mod
        from fastapi.responses import Response
        sb = _get_supabase()
        rows = sb.table("conversations").select("*").eq("client_id", CLIENT_ID)             .order("created_at", desc=True).execute().data or []
        output = io.StringIO()
        writer = csv_mod.writer(output)
        writer.writerow(["date", "session_id", "user_message", "bot_response"])
        for r in rows:
            writer.writerow([
                str(r.get("created_at", ""))[:19],
                str(r.get("session_id", ""))[:8],
                r.get("user_message", ""),
                r.get("bot_response", "")[:200],
            ])
        filename = f"conversations_{datetime.now().strftime('%Y%m%d')}.csv"
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Export error: {e}")
        return HTMLResponse(f"Export failed: {e}", status_code=500)


@app.post("/admin/reverify", response_class=HTMLResponse)
async def admin_reverify(request: Request, password: str = Form(...)):
    """Re-verification for sensitive actions."""
    if not request.session.get("admin_authenticated"):
        return HTMLResponse("Not authenticated", status_code=401)
    if password == ADMIN_PASSWORD:
        request.session["admin_verified"] = True
        return HTMLResponse("OK")
    return HTMLResponse("Wrong password", status_code=403)


@app.post("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["admin_authenticated"] = True
        return RedirectResponse(url="/admin", status_code=303)
    return HTMLResponse(content=render_page("Admin Login",
        _login_page("\U0001f512", "Admin Access", "/admin/login", "Incorrect password."), include_admin_js=True))

@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.pop("admin_authenticated", None)
    return RedirectResponse(url="/admin", status_code=303)

async def _admin_dashboard(request: Request):
    try:
        sb = _get_supabase()

        leads_data    = sb.table("leads").select("*").order("timestamp", desc=True).limit(50).execute().data or []
        convs_data    = sb.table("conversations").select("*").eq("client_id", CLIENT_ID).order("created_at", desc=True).limit(50).execute().data or []
        products_data = sb.table("products").select("*").order("name").execute().data or []
        leads_count    = len(sb.table("leads").select("id").execute().data or [])
        conv_count     = len(sb.table("conversations").select("id").execute().data or [])
        products_count = len(sb.table("products").select("id").execute().data or [])
        faqs_count     = len(sb.table("faqs").select("id").eq("client_id", CLIENT_ID).execute().data or [])
        today          = datetime.now().date().isoformat()
        today_leads    = len(sb.table("leads").select("id").gte("timestamp", today).execute().data or [])

        E = _esc_html

        # ---- leads rows (all content escaped) ----
        leads_rows = "".join(
            "<tr class='border-b border-[#FFE4CC]'>"
            "<td class='px-4 py-2 text-sm text-[#2D1B00]'>" + E(l.get("name", "")) + "</td>"
            "<td class='px-4 py-2 text-sm text-[#2D1B00]'>" + E(l.get("email", "")) + "</td>"
            "<td class='px-4 py-2 text-sm text-[#8B6914]'>" + E(str(l.get("timestamp", ""))[:10]) + "</td></tr>"
            for l in leads_data
        ) or "<tr><td colspan='3' class='px-4 py-4 text-sm text-center text-[#8B6914]'>No leads yet</td></tr>"

        # ---- conversations rows (all content escaped, inlined server-side) ----
        convs_rows = "".join(
            "<tr class='border-b border-[#FFE4CC] hover:bg-[#FFFAF5]'>"
            "<td class='px-4 py-3 text-xs font-mono text-[#8B6914]'>" + E(str(c.get("session_id", ""))[:8]) + "</td>"
            "<td class='px-4 py-3 text-sm text-[#2D1B00]'>" + E(str(c.get("user_message", ""))[:80]) + "</td>"
            "<td class='px-4 py-3 text-sm text-[#5A3A1B]'>" + E(str(c.get("bot_response", ""))[:80]) + "...</td>"
            "<td class='px-4 py-3 text-xs text-[#8B6914] whitespace-nowrap'>" + E(str(c.get("created_at", ""))[:10]) + "</td></tr>"
            for c in convs_data
        ) or "<tr><td colspan='4' class='px-4 py-4 text-sm text-center text-[#8B6914]'>No conversations yet</td></tr>"

        # ---- product rows: escape every string field before rendering ----
        def _safe_product(p):
            return {k: (E(v) if isinstance(v, str) else v) for k, v in p.items()}
        product_rows = "".join(_render_product_row(_safe_product(p)) for p in products_data) or \
            "<tr><td colspan='5' class='px-4 py-4 text-sm text-center text-[#8B6914]'>No products yet — upload a catalog below</td></tr>"

        # ---- reusable panel card ----
        def card(title_html, head_cells, body_html, extra_header=""):
            ths = "".join("<th class='px-4 py-2 text-left text-xs text-[#8B6914] uppercase'>" + h + "</th>" for h in head_cells)
            return (
                "<div class='bg-white rounded-xl shadow-sm border border-[#FFE4CC] overflow-hidden mb-4'>"
                "<div class='px-4 py-3 border-b border-[#FFE4CC] flex justify-between items-center'>"
                "<h2 class='font-bold text-[#2D1B00] text-sm'>" + title_html + "</h2>" + extra_header + "</div>"
                "<div class='overflow-x-auto'><table class='w-full'>"
                "<thead class='bg-[#FFF9F4]'><tr>" + ths + "</tr></thead>"
                "<tbody>" + body_html + "</tbody></table></div></div>"
            )

        leads_panel = card("&#128101; All Leads", ["Name", "Email", "Date"], leads_rows)
        # Make each conversation row clickable
        clickable_rows = ""
        for c in convs_data:
            sid = c.get('session_id','')
            E = _esc_html
            sid_disp = E(sid[:8])
            umsg = E(str(c.get('user_message',''))[:80])
            bresp = E(str(c.get('bot_response',''))[:80])
            cdate = E(str(c.get('created_at',''))[:10])
            clickable_rows += (
                '<tr class="convo-row" data-sid="' + sid + '" '
                'style="border-bottom:1px solid #FFE4CC;cursor:pointer">'
                '<td class="px-4 py-3 text-xs font-mono text-[#8B6914]">' + sid_disp + '</td>'
                '<td class="px-4 py-3 text-sm text-[#2D1B00]">' + umsg + '</td>'
                '<td class="px-4 py-3 text-sm text-[#5A3A1B]">' + bresp + '...</td>'
                '<td class="px-4 py-3 text-xs text-[#8B6914] whitespace-nowrap">' + cdate + '</td></tr>'
            )
        if not clickable_rows:
            clickable_rows = "<tr><td colspan='4' class='px-4 py-4 text-sm text-center text-[#8B6914]'>No conversations yet</td></tr>"

        convo_drawer = (
            "<div id='convo-drawer' style='display:none;position:fixed;top:0;right:0;width:420px;max-width:95vw;"
            "height:100vh;background:white;box-shadow:-4px 0 24px rgba(0,0,0,0.15);z-index:1000;overflow-y:auto;font-family:Quicksand,sans-serif'>"
            "<div style='position:sticky;top:0;background:white;padding:14px 16px;border-bottom:1px solid #FFE4CC;"
            "display:flex;justify-content:space-between;align-items:center;z-index:1'>"
            "<span style='font-weight:700;color:#2D1B00;font-size:15px'>&#128172; Conversation</span>"
            "<button onclick=\"document.getElementById('convo-drawer').style.display='none'\" "
            "style='background:none;border:none;font-size:22px;cursor:pointer;color:#8B6914;line-height:1'>&times;</button></div>"
            "<div id='convo-drawer-body' style='padding:0'>Loading...</div></div>"
            "<div id='convo-overlay' onclick=\"document.getElementById('convo-drawer').style.display='none';"
            "document.getElementById('convo-overlay').style.display='none'\" "
            "style='display:none;position:fixed;inset:0;background:rgba(0,0,0,0.3);z-index:999'></div>"
            "<script>""function openConvo(sid){""  var d=document.getElementById('convo-drawer');""  var b=document.getElementById('convo-drawer-body');""  var o=document.getElementById('convo-overlay');""  b.innerHTML='<div style=\"padding:2rem;text-align:center;color:#8B6914\">Loading...</div>';""  d.style.display='block';o.style.display='block';""  fetch('/admin/conversation/'+encodeURIComponent(sid),{credentials:'same-origin'})""  .then(function(r){return r.text();})""  .then(function(html){b.innerHTML=html;})""  .catch(function(e){b.innerHTML='<p style=\"color:red;padding:1rem\">'+e.message+'</p>';});""}""document.addEventListener('click',function(e){""  var row=e.target.closest('.convo-row');""  if(row){openConvo(row.dataset.sid);}""});""document.querySelectorAll('.convo-row').forEach(function(r){""  r.onmouseover=function(){this.style.background='#FFF0DB';};""  r.onmouseout=function(){this.style.background='';};""});""</script>"
        )

        convs_panel = card(
            "&#128172; Recent Conversations",
            ["Session", "Customer Message", "Teddy Response", "Date"],
            clickable_rows,
            "<a href='/admin/conversations/export' class='text-xs text-[#FF922B] hover:underline font-semibold'>&#128229; Export CSV</a>",
        ) + convo_drawer
        products_panel = card(
            "&#127987; Product Catalog <span class='ml-2 text-xs font-normal text-[#8B6914]'>(" + str(products_count) + " products — click row to expand)</span>",
            ["Name", "Category", "SKU", "Price", "Stock"],
            product_rows,
        ) + UPLOAD_CARD

        # ---- tab buttons: data-tab + onclick, zero quote-escaping needed ----
        def tab_button(tid, label, value, active=False):
            base = "border-radius:12px;padding:16px;text-align:left;cursor:pointer;transition:all .2s;width:100%;font-family:inherit;"
            style = ("background:#FF922B;color:white;border:2px solid #FF922B;" if active
                     else "background:white;color:#5A3A1B;border:2px solid #FFE4CC;") + base
            return (
                "<button id='tab-" + tid + "' data-tab='" + tid + "' onclick='showPanel(this.dataset.tab)' style='" + style + "'>"
                "<p style='font-size:11px;text-transform:uppercase;letter-spacing:.05em;opacity:.85'>" + label + "</p>"
                "<p style='font-size:28px;font-weight:700;margin-top:4px'>" + str(value) + "</p></button>"
            )

        tabs_html = (
            "<div class='grid grid-cols-2 md:grid-cols-5 gap-4 mb-6'>"
            + tab_button("leads", "Total Leads", leads_count, active=True)
            + "<button id='tab-today' data-tab='leads' onclick='showPanel(this.dataset.tab)' "
              "style='background:white;color:#5A3A1B;border:2px solid #FFE4CC;border-radius:12px;padding:16px;"
              "text-align:left;cursor:pointer;transition:all .2s;width:100%;font-family:inherit'>"
              "<p style='font-size:11px;text-transform:uppercase;letter-spacing:.05em'>Today</p>"
              "<p style='font-size:28px;font-weight:700;margin-top:4px'>" + str(today_leads) + "</p></button>"
            + tab_button("products", "Products", products_count)
            + tab_button("faqs", "FAQs", faqs_count)
            + tab_button("conversations", "Conversations", conv_count)
            + "</div>"
        )

        tab_js = (
            "<script>"
            "function showPanel(t){"
            "var names=['leads','products','faqs','conversations'];"
            "for(var i=0;i<names.length;i++){"
            "var id=names[i];"
            "var p=document.getElementById('panel-'+id);"
            "var b=document.getElementById('tab-'+id);"
            "if(p){p.style.display=(id===t)?'block':'none';}"
            "if(b){if(id===t){b.style.background='#FF922B';b.style.color='white';b.style.borderColor='#FF922B';}"
            "else{b.style.background='white';b.style.color='#5A3A1B';b.style.borderColor='#FFE4CC';}}"
            "}}"
            "</script>"
        )

        content = (
            "<div class='min-h-screen bg-[#FFF9F4] p-4'><div class='max-w-5xl mx-auto'>"
            "<div class='flex justify-between items-center mb-6'>"
            "<h1 class='text-2xl font-bold text-[#2D1B00]'>\U0001f4ca Admin Dashboard "
            "<span style='font-size:11px;font-weight:400;color:#8B6914'>v3.1</span></h1>"
            "<a href='/admin/logout' class='text-sm text-[#8B6914] hover:text-[#FF922B]'>Logout</a></div>"
            + tabs_html
            + "<div style='margin-top:1.5rem'>"
            + "<div id='panel-leads' style='display:block'>" + leads_panel + "</div>"
            + "<div id='panel-products' style='display:none'>" + products_panel + "</div>"
            + "<div id='panel-faqs' style='display:none'>" + _build_faq_panel() + "</div>"
            + "<div id='panel-conversations' style='display:none'>" + convs_panel + "</div>"
            + "</div>"
            + tab_js
            + "</div></div>"
        )
        return HTMLResponse(content=render_page("Admin Dashboard", content, include_admin_js=True))
    except Exception as e:
        logger.error(f"Admin error: {e}", exc_info=True)
        return HTMLResponse(f'<div class="p-8 text-red-500">Dashboard error: {e}</div>')


# ---------------------------------------------------------------------------
# Dev tools
# ---------------------------------------------------------------------------
@app.get("/dev", response_class=HTMLResponse)
async def dev_page(request: Request):
    if not request.session.get("dev_authenticated"):
        return HTMLResponse(content=render_page("Dev Login", _login_page("\U0001f527", "Dev Tools", "/dev/login")))
    return await _dev_dashboard(request)

@app.post("/dev/login", response_class=HTMLResponse)
async def dev_login(request: Request, password: str = Form(...)):
    if password == DEV_PASSWORD:
        request.session["dev_authenticated"] = True
        return RedirectResponse(url="/dev", status_code=303)
    return HTMLResponse(content=render_page("Dev Login",
        _login_page("\U0001f527", "Dev Tools", "/dev/login", "Incorrect password.")))

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
        "CLIENT_ID":          os.environ.get("CLIENT_ID"),
        "BUSINESS_NAME":      os.environ.get("BUSINESS_NAME"),
        "BUSINESS_TYPE":      os.environ.get("BUSINESS_TYPE"),
        "SHOP_URL":           os.environ.get("SHOP_URL"),
        "VOUCHER_CODE":       os.environ.get("VOUCHER_CODE"),
    }
    rows = "".join(
        f'<tr class="border-b border-[#FFE4CC]">'
        f'<td class="px-4 py-2 text-sm font-mono text-[#2D1B00]">{k}</td>'
        f'<td class="px-4 py-2 text-sm">{"<span class=\'text-green-600 font-semibold\'>\u2705 Set</span>" if v else "<span class=\'text-red-500\'>\u274c Missing</span>"}</td>'
        f'<td class="px-4 py-2 text-xs text-[#8B6914] font-mono">{"***" + v[-4:] if v and len(v) > 6 else (v or "")}</td></tr>'
        for k, v in checks.items()
    )
    try:
        sb = _get_supabase()
        sb.table("faqs").select("id").limit(1).execute()
        db_status = '<span class="text-green-600 font-semibold">\u2705 Connected</span>'
    except Exception as e:
        db_status = f'<span class="text-red-500">\u274c {e}</span>'

    content = (
        '<div class="min-h-screen bg-[#FFF9F4] p-4"><div class="max-w-3xl mx-auto">'
        '<div class="flex justify-between items-center mb-6">'
        '<h1 class="text-2xl font-bold text-[#2D1B00]">\U0001f527 Dev Tools</h1>'
        '<a href="/dev/logout" class="text-sm text-[#8B6914] hover:text-[#FF922B]">Logout</a></div>'
        f'<div class="bg-white rounded-xl shadow-sm border border-[#FFE4CC] p-4 mb-4">'
        f'<p class="text-sm text-[#5A3A1B]">Supabase: {db_status}</p></div>'
        '<div class="bg-white rounded-xl shadow-sm border border-[#FFE4CC] overflow-hidden">'
        '<div class="px-4 py-3 border-b border-[#FFE4CC]"><h2 class="font-bold text-[#2D1B00] text-sm">Environment Variables</h2></div>'
        '<div class="overflow-x-auto"><table class="w-full">'
        '<thead class="bg-[#FFF9F4]"><tr>'
        '<th class="px-4 py-2 text-left text-xs text-[#8B6914] uppercase">Variable</th>'
        '<th class="px-4 py-2 text-left text-xs text-[#8B6914] uppercase">Status</th>'
        '<th class="px-4 py-2 text-left text-xs text-[#8B6914] uppercase">Preview</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div></div>'
        '</div></div>'
    )
    return HTMLResponse(content=render_page("Dev Tools", content))


# ---------------------------------------------------------------------------
# Embed script — one line of HTML that any website can drop in
# ---------------------------------------------------------------------------
@app.get("/embed.js")
async def embed_script():
    from fastapi.responses import Response
    base = os.environ.get("RENDER_EXTERNAL_URL", "https://ted-pro.onrender.com")
    js = f"""(function(){{
  if(window.__tedpro_loaded)return;
  window.__tedpro_loaded=true;
  var s=document.createElement('style');
  s.textContent='#tedpro-btn{{position:fixed;bottom:24px;right:24px;width:56px;height:56px;border-radius:50%;background:linear-gradient(135deg,#FF922B,#FF8C42);border:none;cursor:pointer;font-size:26px;box-shadow:0 4px 16px rgba(255,146,43,0.5);z-index:99998;transition:transform .2s}}#tedpro-btn:hover{{transform:scale(1.1)}}#tedpro-frame{{display:none;position:fixed;bottom:92px;right:24px;width:380px;height:580px;border:none;border-radius:20px;box-shadow:0 8px 40px rgba(0,0,0,0.18);z-index:99999}}@media(max-width:480px){{#tedpro-frame{{width:calc(100vw - 16px);height:calc(100vh - 100px);bottom:92px;right:8px}}}}';
  document.head.appendChild(s);
  var btn=document.createElement('button');
  btn.id='tedpro-btn';btn.innerHTML='🧸';btn.title='Chat with us';
  var frame=document.createElement('iframe');
  frame.id='tedpro-frame';frame.src='{base}/chat-widget';frame.allow='microphone';
  var open=false;
  btn.onclick=function(){{
    open=!open;
    frame.style.display=open?'block':'none';
    btn.innerHTML=open?'✕':'🧸';
    if(open&&!frame._loaded){{frame._loaded=true;}}
  }};
  document.body.appendChild(btn);
  document.body.appendChild(frame);
}})();"""
    return Response(content=js, media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=3600"})



@app.get("/chat-widget", response_class=HTMLResponse)
async def chat_widget(request: Request):
    """Cookieless widget — session via localStorage, works on every site/browser/security setting."""
    sid = request.query_params.get("sid", "")
    if not sid:
        return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="utf-8"><script>
var s=localStorage.getItem('tpro_sid');
if(!s){s='w'+Math.random().toString(36).slice(2)+Math.random().toString(36).slice(2);localStorage.setItem('tpro_sid',s);}
location.replace('/chat-widget?sid='+encodeURIComponent(s));
</script></head><body></body></html>""")

    try:
        sb = _get_supabase()
        rows = sb.table("conversations").select("user_message,bot_response") \
            .eq("session_id", sid).eq("client_id", CLIENT_ID) \
            .order("created_at", desc=False).limit(50).execute().data or []
    except Exception:
        rows = []

    history_html = ""
    for r in rows:
        u = _esc_html(r.get("user_message", ""))
        b = _esc_html(r.get("bot_response", ""))
        history_html += (
            "<div style='display:flex;justify-content:flex-end;margin-bottom:8px'>"
            "<div style='background:#FF922B;color:white;padding:10px 14px;"
            "border-radius:16px 16px 4px 16px;max-width:78%;font-size:13px'>"
            + u + "</div></div>"
            "<div style='display:flex;justify-content:flex-start;margin-bottom:8px'>"
            "<div style='background:white;border:1px solid #FFE4CC;padding:10px 14px;"
            "border-radius:16px 16px 16px 4px;max-width:78%;font-size:13px;color:#2D1B00'>"
            "&#129528; " + b + "</div></div>"
        )

    if not history_html:
        history_html = (
            "<div style='text-align:center;padding:20px;color:#8B6914;font-size:13px'>"
            "&#128075; Hi! Ask me anything about CuddleHeros plushies!</div>"
        )

    sid_js = sid.replace("'", "\\'")

    page = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<link href='https://fonts.googleapis.com/css2?family=Quicksand:wght@400;600;700&display=swap' rel='stylesheet'>"
        "<script src='https://cdn.jsdelivr.net/npm/marked/marked.min.js'></script>"
        "<style>"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{font-family:'Quicksand',sans-serif;background:#FFF9F4;height:100vh;display:flex;flex-direction:column;overflow:hidden}"
        "#msgs{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:2px}"
        "#footer{padding:10px;background:#FFF9F4;border-top:1px solid #FFE4CC;flex-shrink:0}"
        "#row{display:flex;gap:8px}"
        "#inp{flex:1;padding:10px 14px;border-radius:20px;border:1.5px solid #FFD5A5;background:white;font-size:13px;outline:none;font-family:inherit}"
        "#btn{padding:10px 18px;border-radius:20px;background:#FF922B;color:white;border:none;font-weight:700;font-size:13px;cursor:pointer;font-family:inherit}"
        "#btn:disabled{opacity:.6;cursor:default}"
        "</style></head><body>"
        "<div style='background:linear-gradient(135deg,#FF922B,#FF8C42);color:white;padding:12px 16px;text-align:center;flex-shrink:0'>"
        "<div style='font-size:20px'>&#129528;</div>"
        "<div style='font-weight:700;font-size:14px'>Teddy</div>"
        "<div style='font-size:11px;opacity:.85'>Your CuddleHeros Assistant</div></div>"
        "<div id='msgs'>" + history_html + "</div>"
        "<div id='footer'><div id='row'>"
        "<input id='inp' type='text' placeholder='Ask Teddy...' autocomplete='off'>"
        "<button id='btn' onclick='send()'>Send</button>"
        "</div></div>"
        "<script>"
        "var SID='" + sid_js + "';"
        "function scroll(){var m=document.getElementById('msgs');m.scrollTop=m.scrollHeight;}"
        "scroll();"
        "function send(){"
        "  var inp=document.getElementById('inp');"
        "  var btn=document.getElementById('btn');"
        "  var txt=inp.value.trim();if(!txt)return;"
        "  inp.value='';btn.disabled=true;"
        "  var msgs=document.getElementById('msgs');"
        "  var ub=document.createElement('div');"
        "  ub.style.cssText='display:flex;justify-content:flex-end;margin-bottom:8px';"
        "  ub.innerHTML='<div style=\"background:#FF922B;color:white;padding:10px 14px;border-radius:16px 16px 4px 16px;max-width:78%;font-size:13px\">'+txt+'</div>';"
        "  msgs.appendChild(ub);scroll();"
        "  var tb=document.createElement('div');"
        "  tb.style.cssText='display:flex;justify-content:flex-start;margin-bottom:8px';"
        "  tb.innerHTML='<div style=\"background:white;border:1px solid #FFE4CC;padding:10px 14px;border-radius:16px 16px 16px 4px;max-width:78%;font-size:13px;color:#2D1B00\">&#129528; ...</div>';"
        "  msgs.appendChild(tb);scroll();"
        "  fetch('/widget-chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:txt,sid:SID})})"
        "  .then(function(r){return r.json();})"
        "  .then(function(d){"
        "    var inner=tb.querySelector('div');"
        "    inner.innerHTML='&#129528; '+(window.marked?marked.parse(d.response):d.response);"
        "    if(d.handoff&&d.whatsapp&&!window._tedHandoffShown){"
        "      window._tedHandoffShown=true;"
        "      var wb=document.createElement('div');"
        "      wb.style.cssText='display:flex;justify-content:flex-start;margin-bottom:8px';"
        "      var wa=document.createElement('div');"
        "      wa.style.cssText='background:white;border:1px solid #FFE4CC;padding:10px 14px;border-radius:16px;max-width:78%;font-size:13px';"
        "      wa.innerHTML='<p style=\"margin-bottom:8px;color:#2D1B00\">I can connect you with our team!</p>'"
        "        +'<a href=\"'+d.whatsapp+'\" target=\"_blank\" style=\"display:inline-flex;align-items:center;gap:6px;padding:8px 14px;background:#25D366;color:white;border-radius:8px;font-weight:700;font-size:12px;text-decoration:none\">&#128172; Chat on WhatsApp</a>'"
        "        +'<p style=\"font-size:10px;color:#8B6914;margin-top:6px\">Mon-Fri 8am-5pm &bull; Sat 9am-1pm</p>';"
        "      wb.appendChild(wa);msgs.appendChild(wb);scroll();"
        "    }"
        "    btn.disabled=false;scroll();"
        "  })"
        "  .catch(function(){"
        "    tb.querySelector('div').textContent='&#129528; Connection issue, try again!';"
        "    btn.disabled=false;"
        "  });"
        "}"
        "document.getElementById('inp').onkeydown=function(e){if(e.key==='Enter')send();};"
        "function submitWidgetLead(){"
        "  var name=document.getElementById('wl-name').value.trim();"
        "  var email=document.getElementById('wl-email').value.trim();"
        "  var msg=document.getElementById('wl-msg');"
        "  if(!email||email.indexOf('@')<0){msg.textContent='Please enter a valid email.';return;}"
        "  fetch('/widget-lead',{method:'POST',"
        "    headers:{'Content-Type':'application/json'},"
        "    body:JSON.stringify({name:name,email:email,sid:SID})})"
        "  .then(function(r){return r.json();})"
        "  .then(function(d){"
        "    var lf=document.getElementById('widget-lead-form');"
        "    if(lf)lf.innerHTML='<p style=color:#166534;font-weight:700;font-size:13px;text-align:center>&#9989; You are in! Check your inbox for TEDDY10.</p>';"
        "  }).catch(function(){msg.textContent='Something went wrong.';});"
        "}"
        "</script></body></html>"
    )
    return HTMLResponse(content=page)


@app.post("/widget-chat")
async def widget_chat(request: Request):
    """Cookieless JSON chat endpoint for the embed widget."""
    try:
        body = await request.json()
        prompt = str(body.get("prompt", "")).strip()
        sid = str(body.get("sid", "")).strip()
        if not prompt or not sid:
            return JSONResponse({"response": "Something went wrong. Try again!"})

        if _is_gibberish(prompt):
            return JSONResponse({"response": "Hmm, I didn't quite catch that! Try asking me about our plushies, pricing, shipping, or custom orders. \U0001f9f8"})

        q_lower = prompt.lower()

        # 1. FAQ lookup — skip for support/context messages
        _SUPPORT = [
            "not working", "doesn't work", "cant", "can't", "wont", "won't",
            "error", "problem", "issue", "broken", "failed", "wrong",
            "didn't", "didnt", "still ", "again", "already", " it ",
            "that ", "this ", "the one", "my order",
        ]
        _skip_faq = any(s in q_lower for s in _SUPPORT)
        faq_answer = None if _skip_faq else lookup_faq(prompt)
        if faq_answer:
            save_history_row(sid, prompt, faq_answer)
            return JSONResponse({"response": faq_answer})

        # 2. Handoff — clean message only, no AI
        if any(kw in q_lower for kw in HANDOFF_KEYWORDS):
            handoff_msg = "I'll connect you with our team right away!"
            save_history_row(sid, prompt, handoff_msg)
            return JSONResponse({
                "response": handoff_msg,
                "handoff": True,
                "whatsapp": "https://wa.me/27836205614?text=Hi%20CuddleHeros%2C%20I%20need%20help%20%F0%9F%A7%B8"
            })

        # 3. Lead capture check
        LEAD_INTENT = [
            "price", "cost", "how much", "order", "buy", "purchase",
            "ship", "deliver", "custom", "gift", "birthday",
            "available", "stock", "checkout", "add to cart",
        ]
        history = load_history(sid)
        has_intent = any(kw in q_lower for kw in LEAD_INTENT)
        msg_count = len(history)
        try:
            sb2 = _get_supabase()
            existing_lead = sb2.table("leads").select("id").eq("context", f"widget_{sid}").execute().data
            lead_captured = bool(existing_lead)
        except Exception:
            lead_captured = False
        show_lead = not lead_captured and (has_intent or msg_count >= 8)

        # 4. Build enhanced prompt with product data — fetch ALL locally, filter by keywords
        enhanced = prompt
        PROD_TRIGGERS = list(PRODUCT_KEYWORDS) + ["rainbow", "giant", "mini", "snuggle", "gentle", "large", "soft"]
        if any(kw in q_lower for kw in PROD_TRIGGERS) or any(kw in q_lower for kw in STOCK_KEYWORDS):
            try:
                sb3 = _get_supabase()
                all_prods = sb3.table("products").select(
                    "name,price,currency,in_stock,stock_quantity,description,size_cm,material,customisable,category"
                ).eq("client_id", CLIENT_ID).execute().data or []

                search_terms = set(w.lower() for w in prompt.split() if len(w) > 2)
                for msg in reversed(history[-3:]):
                    if msg.get("role") == "user":
                        for w in msg.get("content", "").split():
                            if len(w) > 2:
                                search_terms.add(w.lower())
                        break

                matched = [
                    p for p in all_prods
                    if any(
                        t in p.get("name", "").lower() or t in p.get("category", "").lower()
                        for t in search_terms
                    )
                ]
                if not matched:
                    matched = all_prods

                if matched:
                    lines = []
                    for p in matched[:5]:
                        stock_status = "In stock" if p.get("in_stock") else "Out of stock"
                        lines.append(
                            f"{p['name']} | ZAR {float(p.get('price') or 0):.2f} | {stock_status} | "
                            f"Size: {p.get('size_cm', '?')}cm | {p.get('material', '')}"
                        )
                    enhanced = (
                        prompt
                        + "\n\n[PRODUCT INFO — use ONLY these exact prices and details, do not invent anything]\n"
                        + "\n".join(lines)
                        + "\n[END PRODUCT INFO]"
                    )
            except Exception as prod_err:
                logger.error(f"Product lookup error: {prod_err}")

        # 5. AI response
        history.append({"role": "user", "content": prompt})
        full = "".join(get_engine().stream_answer(enhanced, chat_history=history))
        full = _strip_urls(full)
        save_history_row(sid, prompt, full)
        resp = {"response": full}
        if show_lead:
            resp["show_lead"] = True
        return JSONResponse(resp)
    except Exception as e:
        logger.error(f"widget_chat error: {e}")
        return JSONResponse({"response": "I'm having a moment! Try again. \U0001f9f8"})


@app.post("/widget-lead")
async def widget_lead(request: Request):
    """Capture lead from the embed widget."""
    try:
        body = await request.json()
        name  = str(body.get("name", "")).strip()
        email = str(body.get("email", "")).strip()
        sid   = str(body.get("sid", "")).strip()
        if not email or "@" not in email:
            return JSONResponse({"ok": False, "error": "Invalid email"})
        saved = get_engine().add_lead(name, email, context=f"widget_{sid}")
        if saved:
            send_welcome_email(name, email)
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"widget_lead error: {e}")
        return JSONResponse({"ok": False, "error": str(e)})
