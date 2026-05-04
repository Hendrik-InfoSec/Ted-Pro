import streamlit as st
from hybrid_engine import HybridEngine
from datetime import datetime, timedelta
import uuid, time, hashlib, re, os, logging
from typing import List, Dict, Optional
from supabase import create_client, Client
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- 1. CONFIG & API SETUP ---

# --- EXPLICIT PAGE NAVIGATION (Fix for Render deployment) ---
dashboard_page = st.Page("pages/Dashboard.py", title="Dashboard", icon="📊")
dev_tools_page = st.Page("pages/Dev_Tools.py", title="Dev Tools", icon="🔧")
chat_page = st.Page("main.py", title="TedPro Assistant", icon="🧸", default=True)

pg = st.navigation([chat_page, dashboard_page, dev_tools_page])
pg.run()

# --- END NAVIGATION ---

st.set_page_config(
    page_title="TedPro Marketing Assistant 🧸",
    page_icon="🧸",
    layout="wide",
    initial_sidebar_state="collapsed"  # Start collapsed to maximize chat space
)

# Timezone Fix
LOCAL_OFFSET_HOURS = 2

def get_teddy_time():
    utc_now = datetime.now()
    local_now = utc_now + timedelta(hours=LOCAL_OFFSET_HOURS)
    return local_now.strftime("%H:%M")

# --- 2. PROFESSIONAL UI DESIGN ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Quicksand', sans-serif; }

    .stApp { 
        background: linear-gradient(135deg, #FFF9F4 0%, #FFEDD2 100%);
    }

    /* Hide Streamlit branding */
    header { visibility: hidden; }
    footer { visibility: hidden; }
    .stDeployButton { display: none; }

    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #2D1B00 0%, #432818 100%);
        border-right: none;
    }
    [data-testid="stSidebar"] .stMarkdown {
        color: #FFEDD2;
    }

    /* Main container */
    .main-container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 0 20px;
    }

    /* Chat container */
    .chat-wrapper {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 20px 0;
        max-height: calc(100vh - 300px);
        overflow-y: auto;
    }

    /* Message bubbles */
    .message-row {
        display: flex;
        width: 100%;
        animation: fadeIn 0.3s ease-in;
    }

    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }

    .user-row {
        justify-content: flex-end;
    }

    .bot-row {
        justify-content: flex-start;
    }

    .message-bubble {
        max-width: 70%;
        padding: 16px 20px;
        border-radius: 20px;
        font-size: 15px;
        line-height: 1.5;
        position: relative;
        box-shadow: 0 2px 12px rgba(45, 27, 0, 0.08);
    }

    .user-bubble {
        background: linear-gradient(135deg, #FF922B 0%, #FF8C42 100%);
        color: white;
        border-bottom-right-radius: 4px;
        margin-left: auto;
    }

    .bot-bubble {
        background: white;
        color: #2D1B00;
        border: 1px solid #FFE4CC;
        border-bottom-left-radius: 4px;
    }

    .message-meta {
        font-size: 0.75em;
        opacity: 0.6;
        margin-top: 6px;
        text-align: right;
    }

    .bot-bubble .message-meta {
        text-align: left;
        color: #8B6914;
    }

    .user-bubble .message-meta {
        color: rgba(255,255,255,0.8);
    }

    /* Avatar circles */
    .avatar {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
        margin: 0 8px;
        flex-shrink: 0;
    }

    .user-avatar {
        background: #FF922B;
        order: 2;
    }

    .bot-avatar {
        background: #FFE4CC;
        order: 0;
    }

    /* Typing animation */
    .typing-indicator {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 16px 20px;
        background: white;
        border-radius: 20px;
        border-bottom-left-radius: 4px;
        border: 1px solid #FFE4CC;
        box-shadow: 0 2px 12px rgba(45, 27, 0, 0.08);
        width: fit-content;
        margin: 10px 0;
    }

    .typing-dot {
        width: 8px;
        height: 8px;
        background: #FF922B;
        border-radius: 50%;
        animation: typingBounce 1.4s infinite ease-in-out;
    }

    .typing-dot:nth-child(1) { animation-delay: 0s; }
    .typing-dot:nth-child(2) { animation-delay: 0.2s; }
    .typing-dot:nth-child(3) { animation-delay: 0.4s; }

    @keyframes typingBounce {
        0%, 80%, 100% { transform: translateY(0); }
        40% { transform: translateY(-10px); }
    }

    .typing-text {
        font-size: 14px;
        color: #8B6914;
        margin-left: 8px;
        font-style: italic;
    }

    /* Quick questions */
    .quick-questions {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        justify-content: center;
        margin: 20px 0;
    }

    .quick-btn {
        background: white;
        border: 2px solid #FFE4CC;
        border-radius: 25px;
        padding: 10px 20px;
        color: #5A3A1B;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }

    .quick-btn:hover {
        background: #FF922B;
        color: white;
        border-color: #FF922B;
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(255, 146, 43, 0.3);
    }

    /* Lead capture modal */
    .lead-banner {
        background: linear-gradient(135deg, #FF922B 0%, #FF8C42 100%);
        color: white;
        padding: 20px;
        border-radius: 16px;
        margin: 20px 0;
        text-align: center;
        box-shadow: 0 4px 16px rgba(255, 146, 43, 0.2);
    }

    .lead-banner h3 {
        margin: 0 0 10px 0;
        font-size: 1.3em;
    }

    .lead-banner p {
        margin: 0 0 15px 0;
        opacity: 0.95;
    }

    /* Welcome state */
    .welcome-container {
        text-align: center;
        padding: 60px 20px;
        color: #5A3A1B;
    }

    .welcome-container h1 {
        font-size: 2.5em;
        margin-bottom: 10px;
        color: #2D1B00;
    }

    .teddy-welcome {
        font-size: 80px;
        margin-bottom: 20px;
        animation: float 3s ease-in-out infinite;
    }

    @keyframes float {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-10px); }
    }

    /* Scrollbar styling */
    ::-webkit-scrollbar {
        width: 8px;
    }

    ::-webkit-scrollbar-track {
        background: transparent;
    }

    ::-webkit-scrollbar-thumb {
        background: #FFD5A5;
        border-radius: 4px;
    }

    ::-webkit-scrollbar-thumb:hover {
        background: #FF922B;
    }

    /* Mobile responsive */
    @media (max-width: 768px) {
        .message-bubble {
            max-width: 85%;
        }
        .welcome-container h1 {
            font-size: 1.8em;
        }
    }
</style>
""", unsafe_allow_html=True)

# --- 3. BACKEND INITIALIZATION ---
@st.cache_resource
def init_engine():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    sb_url = os.environ.get("SUPABASE_URL")
    sb_key = os.environ.get("SUPABASE_KEY")
    if not all([api_key, sb_url, sb_key]):
        st.error("Missing API Keys in Environment Variables! Check Render dashboard.")
        st.stop()
    return HybridEngine(api_key=api_key, supabase_url=sb_url, supabase_key=sb_key, client_id="tedpro_client")

try:
    engine = init_engine()
except Exception as e:
    st.error(f"Failed to initialize engine: {e}")
    st.stop()

# TEMPORARY DEBUG - Remove after fixing
try:
    test = engine.supabase.table('leads').select('id').limit(1).execute()
    st.sidebar.success("✅ Supabase connected")
except Exception as e:
    st.sidebar.error(f"❌ Supabase error: {str(e)}")

# Initialize session state
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.chat_history = []
    st.session_state.lead_captured = False
    st.session_state.show_lead_modal = False
    st.session_state.typing = False
    st.session_state.test_mode = False

# --- 4. TEDDY'S PERSONALITY FILTER ---
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

# --- 5. SIDEBAR (Clean & Minimal) ---
with st.sidebar:
    st.markdown("# 🧸 TedPro")
    st.caption("Professional Plushie Assistant")
    st.markdown("---")

    # Dev toggle for testing
    with st.expander("🔧 Dev Tools"):
        st.session_state.test_mode = st.toggle("Test Mode", value=st.session_state.test_mode)
        if st.session_state.test_mode:
            st.info("Lead capture form will stay visible after submission")
            if st.button("Reset Lead Status"):
                st.session_state.lead_captured = False
                st.rerun()

        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.chat_history = []
            st.rerun()

    st.markdown("---")
    st.caption("© 2024 CuddleHeros")

# --- 6a. EMAIL SENDING (Gmail SMTP) ---
def send_welcome_email(name: str, email: str) -> bool:
    """Send welcome email with voucher via Gmail SMTP"""
    try:
        gmail_user = os.environ.get("GMAIL_USER")
        gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

        if not gmail_user or not gmail_password:
            logging.error("Gmail credentials not found in environment variables")
            return False

        greeting_name = name if name and name.strip() else "Friend"

        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = "Welcome to the CuddleHeros VIP Club! 🧸"
        msg['From'] = f"Teddy at CuddleHeros <{gmail_user}>"
        msg['To'] = email

        # HTML content
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to CuddleHeros</title>
    <style>
        body {{ font-family: 'Quicksand', 'Helvetica Neue', Arial, sans-serif; background-color: #FFF9F4; margin: 0; padding: 0; color: #2D1B00; }}
        .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 20px; overflow: hidden; box-shadow: 0 10px 40px rgba(45, 27, 0, 0.1); }}
        .header {{ background: linear-gradient(135deg, #FF922B 0%, #FF8C42 100%); padding: 40px 30px; text-align: center; }}
        .header h1 {{ color: white; margin: 0; font-size: 28px; font-weight: 700; }}
        .teddy-emoji {{ font-size: 60px; margin-bottom: 10px; }}
        .content {{ padding: 40px 30px; }}
        .greeting {{ font-size: 22px; font-weight: 600; margin-bottom: 20px; color: #2D1B00; }}
        .message {{ font-size: 16px; line-height: 1.6; color: #5A3A1B; margin-bottom: 30px; }}
        .voucher-box {{ background: linear-gradient(135deg, #FFF0DB 0%, #FFE4CC 100%); border: 2px dashed #FF922B; border-radius: 16px; padding: 30px; text-align: center; margin: 30px 0; }}
        .voucher-label {{ font-size: 14px; text-transform: uppercase; letter-spacing: 2px; color: #8B6914; margin-bottom: 10px; }}
        .voucher-code {{ font-size: 36px; font-weight: 700; color: #FF922B; letter-spacing: 3px; margin: 10px 0; }}
        .voucher-note {{ font-size: 13px; color: #8B6914; margin-top: 10px; }}
        .cta-button {{ display: inline-block; background: linear-gradient(135deg, #FF922B 0%, #FF8C42 100%); color: white; text-decoration: none; padding: 16px 40px; border-radius: 30px; font-weight: 600; font-size: 16px; margin: 20px 0; box-shadow: 0 4px 15px rgba(255, 146, 43, 0.3); }}
        .footer {{ background: #FFF9F4; padding: 30px; text-align: center; font-size: 14px; color: #8B6914; }}
        .social {{ margin-top: 15px; font-size: 24px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="teddy-emoji">🧸</div>
            <h1>Welcome to CuddleHeros!</h1>
        </div>
        <div class="content">
            <div class="greeting">Hi {greeting_name}! 👋</div>
            <div class="message">
                Thanks for joining the Honey-Pot! We're so excited to help you find your perfect plushie companion.<br><br>
                As a warm welcome, here's an exclusive voucher just for you:
            </div>
            <div class="voucher-box">
                <div class="voucher-label">Your Exclusive Voucher</div>
                <div class="voucher-code">TEDDY10</div>
                <div class="voucher-note">10% off your first order • Valid for 30 days</div>
            </div>
            <div style="text-align: center;">
                <a href="https://cuddleheros.com/shop" class="cta-button">Shop the Catalog 🛍️</a>
            </div>
            <div class="message" style="margin-top: 30px;">
                Have questions? Just reply to this email or chat with me anytime on our website. I'm always here to help!<br><br>
                Paws and hugs,<br><strong>Teddy 🧸</strong>
            </div>
        </div>
        <div class="footer">
            <div>© 2024 CuddleHeros. All rights reserved.</div>
            <div class="social">🧸 🍯 ✨</div>
            <div style="margin-top: 15px; font-size: 12px;">You're receiving this because you signed up for the CuddleHeros VIP list.</div>
        </div>
    </div>
</body>
</html>"""

        # Attach HTML
        msg.attach(MIMEText(html_content, 'html'))

        # Send via Gmail SMTP
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, email, msg.as_string())

        logging.info(f"Welcome email sent to {email} via Gmail SMTP")
        return True

    except Exception as e:
        logging.error(f"Email send failed for {email}: {e}")
        return False


# --- 6. LEAD CAPTURE COMPONENT ---
def render_lead_capture():
    """Render lead capture banner - can be placed anywhere"""
    if not st.session_state.lead_captured or st.session_state.test_mode:
        with st.container():
            st.markdown("""
                <div class="lead-banner">
                    <h3>🍯 Join the Honey-Pot</h3>
                    <p>Get our secret catalog and 10% off your first order!</p>
                </div>
            """, unsafe_allow_html=True)

            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                l_name = st.text_input("Name", placeholder="Your name", key="lead_name", label_visibility="collapsed")
            with col2:
                l_email = st.text_input("Email", placeholder="hello@friend.com", key="lead_email", label_visibility="collapsed")
            with col3:
                submit = st.button("Get 10% Off 🎁", use_container_width=True, type="primary")

            if submit and l_email and "@" in l_email:
                with st.spinner("Saving your info..."):
                    try:
                        result = engine.add_lead(l_name, l_email, context="main_chat_v4")
                        if result:
                            st.session_state.lead_captured = True
                            # Send welcome email with voucher via Gmail
                            email_sent = send_welcome_email(l_name, l_email)
                            if email_sent:
                                st.success("✅ Welcome to the VIP Cuddlers club! Check your inbox for your voucher! 🎁")
                            else:
                                st.warning("✅ Lead saved, but email couldn't be sent. Please check your spam folder or contact support.")
                        else:
                            st.error("❌ Couldn't save your info. The email might already be registered.")
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")
            elif submit:
                st.warning("Please enter a valid email address 📧")
    else:
        st.success("✅ You're a VIP Cuddler! Check your email for the secret catalog.")

# --- 7. MAIN CHAT INTERFACE ---
st.markdown("<div class='main-container'>", unsafe_allow_html=True)

# Header
st.markdown("""
    <div style="text-align: center; padding: 20px 0;">
        <h1 style="color: #2D1B00; margin: 0; font-size: 2em;">TedPro Assistant</h1>
        <p style="color: #8B6914; margin: 5px 0 0 0;">Your friendly plushie expert 🧸</p>
    </div>
""", unsafe_allow_html=True)

# Quick Questions
st.markdown("<div class='quick-questions'>", unsafe_allow_html=True)
quick_qs = [
    ("Pricing 💰", "What are your prices?"),
    ("Shipping 📦", "How does shipping work?"),
    ("Custom Work 🎨", "Can I order custom plushies?"),
    ("Safety ✅", "Are your plushies safe for kids?")
]

q_cols = st.columns(4)
for i, (label, query) in enumerate(quick_qs):
    if q_cols[i].button(label, use_container_width=True, key=f"qq_{i}"):
        st.session_state.chat_history.append({
            "role": "user", 
            "content": query, 
            "time": get_teddy_time()
        })
        st.session_state.typing = True
        st.rerun()

st.markdown("</div>", unsafe_allow_html=True)

# Chat display area
chat_container = st.container()

with chat_container:
    if not st.session_state.chat_history:
        # Welcome state
        st.markdown("""
            <div class="welcome-container">
                <div class="teddy-welcome">🧸</div>
                <h1>Hi! I'm Teddy</h1>
                <p>Ask me anything about CuddleHeros plushies!<br>
                I can help with pricing, shipping, custom orders, and more.</p>
            </div>
        """, unsafe_allow_html=True)
    else:
        # Messages
        st.markdown("<div class='chat-wrapper'>", unsafe_allow_html=True)

        for msg in st.session_state.chat_history:
            is_user = msg["role"] == "user"
            row_class = "user-row" if is_user else "bot-row"
            bubble_class = "user-bubble" if is_user else "bot-bubble"
            avatar_class = "user-avatar" if is_user else "bot-avatar"
            avatar_emoji = "👤" if is_user else "🧸"

            st.markdown(f"""
                <div class="message-row {row_class}">
                    <div class="avatar {avatar_class}">{avatar_emoji}</div>
                    <div class="message-bubble {bubble_class}">
                        {msg['content']}
                        <div class="message-meta">{msg['time']}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

        # Typing indicator
        if st.session_state.typing:
            st.markdown("""
                <div class="message-row bot-row">
                    <div class="avatar bot-avatar">🧸</div>
                    <div class="typing-indicator">
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                        <span class="typing-text">Teddy is thinking...</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

# Lead capture (shown after first message or can be triggered)
if len(st.session_state.chat_history) >= 2 and not st.session_state.lead_captured:
    st.markdown("---")
    render_lead_capture()

st.markdown("</div>", unsafe_allow_html=True)

# --- 8. CHAT INPUT & PROCESSING ---
if prompt := st.chat_input("Ask me anything about CuddleHeros...", key="chat_input"):
    # Add user message
    t = get_teddy_time()
    st.session_state.chat_history.append({"role": "user", "content": prompt, "time": t})
    st.session_state.typing = True
    st.rerun()

# Process bot response (runs after rerun when typing is True)
if st.session_state.typing and st.session_state.chat_history:
    last_msg = st.session_state.chat_history[-1]

    if last_msg["role"] == "user":
        # Small delay to show typing animation
        time.sleep(0.5)

        try:
            user_query = last_msg["content"]

            # Check if query is product-related
            product_keywords = ['have', 'stock', 'buy', 'price', 'cost', 'plushie', 'teddy', 'bear', 'unicorn', 
                              'dinosaur', 'bunny', 'custom', 'order', 'catalog', 'shop', 'available']
            is_product_query = any(kw in user_query.lower() for kw in product_keywords)

            product_context = ""
            if is_product_query:
                # Search products
                products = engine.search_products(user_query, max_results=5)
                if products:
                    product_context = "\n\n[PRODUCT INFO]\n" + engine.format_product_response(products)
                    product_context += "\nUse this product information to help the customer. Mention specific items, prices, and features."

            # Build enhanced query with product context
            enhanced_query = user_query
            if product_context:
                enhanced_query = user_query + "\n\n" + product_context

            with st.spinner(""):
                raw_response = "".join([chunk for chunk in engine.stream_answer(enhanced_query)])
                final_response = apply_teddy_vibes(raw_response)

            st.session_state.chat_history.append({
                "role": "assistant", 
                "content": final_response, 
                "time": get_teddy_time()
            })
        except Exception as e:
            
            st.session_state.chat_history.append({
                "role": "assistant", 
                "content": "I'm having trouble connecting right now. Please try again! 🧸", 
                "time": get_teddy_time()
            })
            logging.error(f"Chat error: {e}")

        st.session_state.typing = False
        st.rerun()
