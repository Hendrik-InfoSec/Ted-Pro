import streamlit as st
from hybrid_engine import HybridEngine
from datetime import datetime
from pathlib import Path
import json, os, re, time, uuid, logging
from typing import List, Dict, Optional
import hashlib, traceback
from rich.logging import RichHandler
from rich.traceback import install as install_rich_traceback
import pandas as pd
from supabase import create_client, Client

# Install rich traceback for better error formatting
install_rich_traceback()

# Setup & Configuration
st.set_page_config(
    page_title="TedPro Marketing Assistant",
    page_icon="",
    layout="centered",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://cuddleheroes.example.com/support',
        'Report a bug': 'https://cuddleheroes.example.com/bugs',
        'About': 'TedPro: Your friendly plushie assistant by CuddleHeros!'
    }
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("TedPro")
client_id = "tedpro_client"

# Supabase Connection
@st.cache_resource
def get_supabase_client() -> Client:
    """Get cached Supabase client"""
    try:
        supabase_url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL"))
        supabase_key = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY"))
       
        if not supabase_url or not supabase_key:
            raise ValueError("Supabase credentials not found!")
       
        client = create_client(supabase_url, supabase_key)
        logger.info("Supabase client created")
        return client
    except Exception as e:
        logger.error(f"Supabase client creation failed: {e}")
        raise

# Core Functions
def get_key(name: str) -> Optional[str]:
    """Get API key with fallback"""
    return st.secrets.get(name, os.getenv(name))

def extract_email(text: str) -> Optional[str]:
    """Robust email validation"""
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    words = text.split()
    for word in words:
        match = re.fullmatch(email_pattern, word.strip())
        if match:
            return match.group(0)
    return None

def extract_name(text: str) -> str:
    """Simple name extraction"""
    words = text.split()
    for word in words:
        if (word.istitle() and len(word) > 1 and
            '@' not in word and '.' not in word and
            not any(char.isdigit() for char in word)):
            return word
    return "Friend"

def format_timestamp(timestamp_str: str) -> str:
    """Reliable timestamp formatting"""
    try:
        if isinstance(timestamp_str, str):
            return datetime.fromisoformat(timestamp_str).strftime("%H:%M")
        else:
            return datetime.now().strftime("%H:%M")
    except (ValueError, TypeError):
        return datetime.now().strftime("%H:%M")

# Database Operations
def append_to_conversation(role: str, content: str, session_id: str):
    """Append message to Supabase"""
    try:
        supabase = get_supabase_client()
        supabase.table('conversations').insert({
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'session_id': session_id,
            'client_id': client_id
        }).execute()
        logger.debug(f"Saved message: {role} - {content[:50]}...")
    except Exception as e:
        logger.error(f"Database save error: {e}", exc_info=True)

def load_recent_conversation(session_id: str, limit: int = 50) -> List[Dict]:
    """Load recent conversation from Supabase"""
    try:
        supabase = get_supabase_client()
        result = supabase.table('conversations').select(
            'role, content, timestamp'
        ).eq('session_id', session_id).order('timestamp', desc=True).limit(limit).execute()
       
        messages = result.data if result.data else []
        return [{"role": msg['role'], "content": msg['content'], "timestamp": msg['timestamp']} for msg in reversed(messages)]
    except Exception as e:
        logger.error(f"Database load error: {e}", exc_info=True)
        return []

def get_leads_df() -> pd.DataFrame:
    """Get leads as DataFrame"""
    try:
        supabase = get_supabase_client()
        result = supabase.table('leads').select(
            'name, email, context, timestamp, consent'
        ).eq('client_id', client_id).execute()
       
        if result.data:
            return pd.DataFrame(result.data)
        return pd.DataFrame(columns=["name", "email", "context", "timestamp", "consent"])
    except Exception as e:
        logger.error(f"Lead export error: {e}", exc_info=True)
        return pd.DataFrame(columns=["name", "email", "context", "timestamp", "consent"])

def get_analytics_df() -> pd.DataFrame:
    """Get analytics as DataFrame"""
    try:
        supabase = get_supabase_client()
        result = supabase.table('analytics').select(
            'key, value, updated_at'
        ).eq('client_id', client_id).execute()
       
        if result.data:
            return pd.DataFrame(result.data)
        return pd.DataFrame(columns=["key", "value", "updated_at"])
    except Exception as e:
        logger.error(f"Analytics export error: {e}", exc_info=True)
        return pd.DataFrame(columns=["key", "value", "updated_at"])

# Analytics Functions
def get_analytics() -> Dict[str, int]:
    """Get analytics from database"""
    default = {
        "total_messages": 0, "faq_questions": 0, "lead_captures": 0,
        "sales_related": 0, "order_tracking": 0, "total_sessions": 0,
        "affiliate_clicks": 0
    }
    try:
        supabase = get_supabase_client()
        result = supabase.table('analytics').select('key, value').eq('client_id', client_id).execute()
       
        if result.data:
            db_analytics = {row['key']: row['value'] for row in result.data}
            return {**default, **db_analytics}
        return default
    except Exception as e:
        logger.error(f"Analytics load error: {e}", exc_info=True)
        return default

def update_analytics(updates: Dict[str, int]):
    """Update analytics immediately"""
    try:
        supabase = get_supabase_client()
       
        for key, increment in updates.items():
            existing = supabase.table('analytics').select('value').eq('key', key).eq('client_id', client_id).execute()
           
            if existing.data and len(existing.data) > 0:
                new_value = existing.data[0]['value'] + increment
                supabase.table('analytics').update({
                    'value': new_value,
                    'updated_at': datetime.now().isoformat()
                }).eq('key', key).eq('client_id', client_id).execute()
            else:
                supabase.table('analytics').insert({
                    'key': key,
                    'value': increment,
                    'updated_at': datetime.now().isoformat(),
                    'client_id': client_id
                }).execute()
       
        if "analytics" in st.session_state:
            for key, increment in updates.items():
                st.session_state.analytics[key] = st.session_state.analytics.get(key, 0) + increment
       
        logger.info(f"Analytics updated: {updates}")
        return True
    except Exception as e:
        logger.error(f"Analytics update error: {e}", exc_info=True)
        return False

# Email Notifications
def send_lead_notification(lead_name: str, lead_email: str, context: str) -> bool:
    """Send email notification for new lead"""
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
       
        sender_email = get_key("NOTIFICATION_EMAIL")
        sender_password = get_key("NOTIFICATION_PASSWORD")
        recipient_email = get_key("BUSINESS_EMAIL") or sender_email
       
        if not sender_password:
            logger.warning("No email password configured - skipping notification")
            return False
       
        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = recipient_email
        message["Subject"] = f"New Lead: {lead_name}"
       
        body = f"""
New lead captured via TedPro!
Name: {lead_name}
Email: {lead_email}
Source: {context}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Login to your dashboard to see full details.
        """
       
        message.attach(MIMEText(body, "plain"))
       
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(message)
       
        logger.info(f"Lead notification sent to {recipient_email}")
        return True
       
    except Exception as e:
        logger.error(f"Email notification error: {e}", exc_info=True)
        return False

# Admin Authentication
def check_admin_auth() -> bool:
    """Check if user is authenticated as admin"""
    if 'admin_authenticated' not in st.session_state:
        st.session_state.admin_authenticated = False
   
    if not st.session_state.admin_authenticated:
        st.markdown("### Admin Access Required")
        st.info("Admin dashboard requires authentication")
       
        col1, col2 = st.columns([2, 1])
        with col1:
            password = st.text_input(
                "Enter admin password:",
                type="password",
                key="admin_password_input",
                help="Get password from app admin"
            )
       
        with col2:
            st.write(""); st.write("")  # Spacing
            login_btn = st.button("Login", use_container_width=True)
       
        if login_btn:
            correct_password = get_key("ADMIN_PASSWORD") or "tedpro2025"
           
            if password == correct_password:
                st.session_state.admin_authenticated = True
                st.success("Access granted! Redirecting...")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Incorrect password")
                logger.warning("Failed admin login attempt")
       
        if get_key("ADMIN_PASSWORD") == "tedpro2025" or not get_key("ADMIN_PASSWORD"):
            st.warning("Default password active. Set ADMIN_PASSWORD in secrets for production.")
       
        st.stop()
   
    return True

# Admin Dashboard
def render_admin_dashboard():
    """Render admin dashboard with authentication"""
    check_admin_auth()
   
    col1, col2 = st.columns([4, 1])
    with col1:
        st.header("TedPro Admin Dashboard")
    with col2:
        if st.button("Logout"):
            st.session_state.admin_authenticated = False
            st.rerun()
   
    st.markdown("Manage leads and analytics for CuddleHeros")
   
    st.subheader("Leads")
    leads_df = get_leads_df()
    if not leads_df.empty:
        leads_df['est_value'] = leads_df['context'].apply(lambda x: 5 if 'sidebar' in x else 2)
       
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Leads", len(leads_df))
        with col2:
            st.metric("Est. Value", f"${leads_df['est_value'].sum()}")
        with col3:
            st.metric("Unique Contacts", leads_df['email'].nunique())
       
        st.dataframe(leads_df, use_container_width=True)
       
        csv = leads_df.to_csv(index=False)
        st.download_button(
            label="Download Leads CSV",
            data=csv,
            file_name=f"cuddleheroes_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    else:
        st.info("No leads captured yet.")
   
    st.markdown("---")
   
    st.subheader("Analytics")
    analytics_df = get_analytics_df()
    if not analytics_df.empty:
        cols = st.columns(3)
        for idx, row in analytics_df.iterrows():
            with cols[idx % 3]:
                st.metric(row['key'].replace('_', ' ').title(), row['value'])
       
        st.markdown("---")
        st.dataframe(analytics_df, use_container_width=True)
       
        csv = analytics_df.to_csv(index=False)
        st.download_button(
            label="Download Analytics CSV",
            data=csv,
            file_name=f"cuddleheroes_analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    else:
        st.info("No analytics data yet.")

# Debug Panel
def show_debug_panel():
    """Show debug information"""
    with st.sidebar.expander("Debug Panel", expanded=False):
        st.write("**Status:**")
       
        api_key = get_key("OPENROUTER_API_KEY")
        if api_key:
            masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
            st.success(f"API Key: {masked}")
        else:
            st.error("API Key: MISSING")
       
        try:
            get_supabase_client()
            st.success("Supabase: Connected")
        except:
            st.error("Supabase: Not connected")
       
        st.success("Engine: Initialized") if 'engine' in st.session_state else st.error("Engine: Not initialized")
       
        st.write("**Session:**")
        st.write(f"ID: {st.session_state.get('session_id', 'None')[:8]}...")
        st.write(f"Messages: {len(st.session_state.get('chat_history', []))}")
       
        st.success("Admin: Authenticated") if st.session_state.get('admin_authenticated', False) else st.info("Admin: Not authenticated")
       
        if st.button("Clear Cache"):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()

# Teddy Personality Filter
def teddy_filter(user_message: str, raw_answer: str, is_first_message: bool, lead_captured: bool) -> tuple:
    """Apply teddy personality with proper greeting logic"""
    greeting_added = False
   
    if is_first_message and not st.session_state.get("has_greeted", False):
        friendly_prefix = "Hi there, friend! "
        greeting_added = True
    else:
        friendly_prefix = ""
   
    sales_tail = ""
    if not lead_captured:
        um = user_message.lower()
        if any(k in um for k in ["gift", "present", "birthday", "anniversary"]):
            sales_tail = " If this is a gift, I can suggest sizes or add a sweet note."
        elif any(k in um for k in ["price", "how much", "cost", "buy"]):
            sales_tail = " I can also compare sizes to help you get the best value."
        elif any(k in um for k in ["custom", "personalize", "embroidery"]):
            sales_tail = " Tell me your idea—I'll check feasibility, timeline, and a fair quote."
   
    filtered = f"{friendly_prefix}{raw_answer}{sales_tail}"
    return filtered, greeting_added

# Initialize Engine
logger.info("Starting TedPro initialization...")
api_key = get_key("OPENROUTER_API_KEY")
if not api_key:
    st.error("""
    **API Key Missing!**
   
    Add to Streamlit Secrets:
    - `OPENROUTER_API_KEY = "your-key-here"`
   
    Get one at: https://openrouter.ai/keys
    """)
    st.stop()

supabase_url = get_key("SUPABASE_URL")
supabase_key = get_key("SUPABASE_KEY")
if not supabase_url or not supabase_key:
    st.error("""
    **Supabase Credentials Missing!**
   
    Add to Streamlit Secrets:
    - `SUPABASE_URL = "https://xxx.supabase.co"`
    - `SUPABASE_KEY = "your-anon-key"`
    """)
    st.stop()

try:
    if 'engine' not in st.session_state:
        engine = HybridEngine(
            api_key=api_key,
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            client_id=client_id
        )
        st.session_state.engine = engine
    else:
        engine = st.session_state.engine
    logger.info("Engine initialized")
except Exception as e:
    logger.error(f"Engine initialization failed: {e}", exc_info=True)
    st.error(f"Engine initialization failed: {e}")
    st.stop()

# === HIDDEN ADMIN ACCESS: ONLY VIA ?admin=true ===
try:
    query_params = st.query_params
    admin_mode = query_params.get("admin", "false") == "true"
except:
    admin_mode = False

pages = {"Chat": lambda: None}

if admin_mode:
    pages["Admin Dashboard"] = render_admin_dashboard
    logger.info("Admin mode activated via URL")
else:
    logger.info("Customer mode — admin hidden")

if admin_mode and len(pages) > 1:
    page = st.sidebar.selectbox("Page", options=list(pages.keys()), key="page_nav")
else:
    page = "Chat"

if page != "Chat":
    pages[page]()
    st.stop()

# UI Styling
st.markdown("""
<style>
body { background: linear-gradient(180deg, #FFD5A5, #FFEDD2); font-family: 'Arial', sans-serif; }
.user-msg { background-color: #FFE1B3; border-radius:10px; padding:10px; margin-bottom:8px;
    border:1px solid #FFC085; word-wrap: break-word; color: #2D1B00; }
.bot-msg { background-color: #FFF9F4; border-left:5px solid #FFA94D; border-radius:10px;
    padding:10px; margin-bottom:8px; border:1px solid #FFE4CC; word-wrap: break-word; color: #2D1B00; }
.conversation-scroll { max-height:400px; overflow-y:auto; padding:10px; border:1px solid #FFE4CC;
    border-radius:10px; background-color:#FFFCF9; scroll-behavior:smooth; }
.typing-indicator { display: flex; align-items: center; padding: 12px 16px; background: #FFF9F4;
    border-left: 5px solid #FFA94D; border-radius: 10px; margin-bottom: 8px; border: 1px solid #FFE4CC;
    font-style: italic; color: #5A3A1B; animation: fadeIn 0.3s ease-in; }
.typing-dots { display: inline-flex; margin-left: 8px; }
.typing-dot { width: 6px; height: 6px; border-radius: 50%; background-color: #FF922B; margin: 0 2px;
    animation: typingAnimation 1.4s infinite ease-in-out; }
.typing-dot:nth-child(1) { animation-delay: -0.32s; }
.typing-dot:nth-child(2) { animation-delay: -0.16s; }
@keyframes typingAnimation { 0%, 80%, 100% { transform: scale(0.8); opacity: 0.5; } 40% { transform: scale(1); opacity: 1; } }
@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
.lead-banner { background: linear-gradient(135deg,#FFE8D6,#FFD8B5); padding:15px; border-radius:10px;
    margin:10px 0; text-align:center; border:1px solid #FFD7A5; }
@media (max-width: 768px) {
    .conversation-scroll { max-height: 350px; padding: 8px; }
    .user-msg, .bot-msg { padding: 8px; font-size: 14px; }
}
</style>
""", unsafe_allow_html=True)

# Session State Initialization
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    update_analytics({"total_sessions": 1})
    logger.info(f"New session: {st.session_state.session_id}")

default_states = {
    "chat_history": [],
    "show_history": False,
    "lead_captured": False,
    "lead_consent": False,
    "consent_prompt_shown": False,
    "captured_emails": set(),
    "selected_quick_question": None,
    "show_quick_questions": False,
    "analytics": get_analytics(),
    "processing_active": False,
    "last_processed_time": 0,
    "user_message_count": 0,
    "last_lead_banner_shown": 0,
    "last_error": None,
    "affiliate_tag": get_key("AMAZON_TAG") or "yourid-20",
    "has_greeted": False,
}

for key, default_value in default_states.items():
    if key not in st.session_state:
        if key == "chat_history":
            recent_messages = load_recent_conversation(st.session_state.session_id, 50)
            st.session_state.chat_history = []
            for msg in recent_messages:
                if msg["role"] == "user":
                    st.session_state.chat_history.append({"user": msg["content"], "timestamp": msg["timestamp"]})
                else:
                    st.session_state.chat_history.append({"bot": msg["content"], "timestamp": msg["timestamp"]})
        else:
            st.session_state[key] = default_value

# === Sidebar: Public + Admin-Only ===
st.sidebar.markdown("### TedPro Assistant")
st.sidebar.markdown("Your friendly plushie expert!")

# Lead Capture Sidebar
st.sidebar.markdown("### Get Product Updates")
name_input = st.sidebar.text_input("Your Name", key="sidebar_name")
email_input = st.sidebar.text_input("Your Email", key="sidebar_email")
subscribe_disabled = st.session_state.lead_captured

if st.sidebar.button(
    "Subscribed!" if subscribe_disabled else "Get Catalog",
    disabled=subscribe_disabled,
    key="sidebar_subscribe"
):
    if name_input and email_input:
        extracted_email = extract_email(email_input)
        if extracted_email:
            try:
                hashed_email = hashlib.sha256(extracted_email.encode()).hexdigest()
                if hashed_email not in st.session_state.captured_emails:
                    engine.add_lead(name_input, extracted_email, context="sidebar_signup")
                    st.session_state.captured_emails.add(hashed_email)
                    update_analytics({"lead_captures": 1})
                    st.session_state.lead_captured = True
                    st.sidebar.success("Thanks! We'll send updates soon.")
                    send_lead_notification(name_input, extracted_email, "sidebar_signup")
                    logger.info(f"Lead captured: {name_input} <{extracted_email}>")
                    st.rerun()
                else:
                    st.sidebar.info("You're already subscribed!")
            except Exception as e:
                logger.error(f"Lead capture error: {e}", exc_info=True)
                st.sidebar.error("Failed to save.")
        else:
            st.sidebar.warning("Please enter a valid email.")
    else:
        st.sidebar.warning("Please enter both name and email.")

# Admin-Only Sidebar Content
if admin_mode and st.session_state.get("admin_authenticated", False):
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Live Analytics")
    cols = st.sidebar.columns(2)
    with cols[0]:
        st.metric("Messages", st.session_state.analytics.get("total_messages", 0))
    with cols[1]:
        st.metric("Leads", st.session_state.analytics.get("lead_captures", 0))
    
    with st.sidebar.expander("Detailed Metrics"):
        for k, v in st.session_state.analytics.items():
            st.metric(k.replace("_", " ").title(), v)

if admin_mode:
    show_debug_panel()

# === Main Chat Interface ===
col1, col2, col3 = st.columns([3, 1, 1])
with col1:
    st.markdown('<h1 style="color:#FF922B;">TedPro Marketing Assistant</h1>', unsafe_allow_html=True)
with col2:
    if st.button("History", key="header_history_toggle"):
        st.session_state.show_history = not st.session_state.show_history
with col3:
    toggle_label = "Hide" if st.session_state.show_quick_questions else "Quick Q's"
    if st.button(toggle_label, key="quick_questions_toggle"):
        st.session_state.show_quick_questions = not st.session_state.show_quick_questions

st.markdown('<p style="color:#5A3A1B;">Here to help with products, shipping, or special offers!</p>', unsafe_allow_html=True)

# Quick Questions
should_show_quick_questions = (
    st.session_state.show_quick_questions or
    len(st.session_state.chat_history) == 0
)
if should_show_quick_questions and not st.session_state.processing_active:
    st.markdown("### Quick Questions")
    quick_questions = [
        "What's your pricing?", "Do you ship internationally?",
        "Can I customize plushies?", "What's your return policy?",
        "How long does shipping take?", "Do you have gift options?",
        "What materials are used?", "Can I track my order?",
        "Do you offer discounts?", "What sizes are available?"
    ]
   
    with st.form("quick_questions_form"):
        selected_question = st.radio(
            "Choose a question:",
            quick_questions,
            key="quick_questions_radio",
            label_visibility="collapsed"
        )
        submitted = st.form_submit_button("Ask this question")
        if?submitted and selected_question:
            st.session_state.selected_quick_question = selected_question
            logger.info(f"Quick question: {selected_question}")

# Lead Banner
def should_show_lead_banner() -> bool:
    if st.session_state.lead_captured:
        return False
    user_count = st.session_state.user_message_count
    last_shown = st.session_state.last_lead_banner_shown
    return (user_count == 0 or (user_count >= 3 and user_count - last_shown >= 3))

if should_show_lead_banner():
    st.markdown("""
    <div class='lead-banner'>
    <h4 style='color:#E65C00;margin:0'>Want Product Updates?</h4>
    <p style='margin:8px 0;font-size:14px;color:#5A3A1B;'>Get our catalog and exclusive offers - add your email in the sidebar →</p>
    </div>
    """, unsafe_allow_html=True)
    st.session_state.last_lead_banner_shown = st.session_state.user_message_count

# Chat Display
def display_chat():
    st.markdown('<div class="conversation-scroll">', unsafe_allow_html=True)

    for msg in st.session_state.chat_history:
        if "user" in msg:
            user_msg = msg["user"]
            timestamp = format_timestamp(msg["timestamp"])
            st.markdown(
                f'<div class="user-msg"><strong>You ({timestamp}):</strong> {user_msg}</div>',
                unsafe_allow_html=True
            )
        elif "bot" in msg:
            bot_msg = msg["bot"]
            timestamp = format_timestamp(msg["timestamp"])
            st.markdown(
                f'<div class="bot-msg"><strong>TedPro ({timestamp}):</strong> {bot_msg}</div>',
                unsafe_allow_html=True
            )

    if st.session_state.processing_active:
        st.markdown("""
        <div class="typing-indicator">
            TedPro is thinking
            <div class="typing-dots">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

display_chat()

# Chat Input
with st.form(key="chat_form", clear_on_submit=True):
    user_input = st.text_input(
        "Ask me anything about plushies, shipping, or gifts!",
        placeholder="Type your message...",
        key="user_input",
        label_visibility="collapsed"
    )
    col_send, col_clear = st.columns([1, 4])
    with col_send:
        submit_btn = st.form_submit_button("Send")
    with col_clear:
        clear_btn = st.form_submit_button("Clear Chat")

if clear_btn:
    st.session_state.chat_history = []
    st.session_state.user_message_count = 0
    st.session_state.last_lead_banner_shown = 0
    st.session_state.has_greeted = False
    st.rerun()

# Handle Quick Question
if 'selected_quick_question' in st.session_state and st.session_state.selected_quick_question:
    user_input = st.session_state.selected_quick_question
    st.session_state.selected_quick_question = None
    submit_btn = True
else:
    submit_btn = submit_btn and user_input.strip()

# Process Message
if submit_btn and user_input.strip() and not st.session_state.processing_active:
    st.session_state.processing_active = True
    st.session_state.user_message_count += 1

    user_msg_obj = {"user": user_input, "timestamp": datetime.now().isoformat()}
    st.session_state.chat_history.append(user_msg_obj)
    append_to_conversation("user", user_input, st.session_state.session_id)

    is_first_message = len([m for m in st.session_state.chat_history if "user" in m]) == 1

    try:
        raw_response = engine.get_response(user_input)
        filtered_response, greeted = teddy_filter(
            user_input, raw_response, is_first_message, st.session_state.lead_captured
        )
        if greeted:
            st.session_state.has_greeted = True

        bot_msg_obj = {"bot": filtered_response, "timestamp": datetime.now().isoformat()}
        st.session_state.chat_history.append(bot_msg_obj)
        append_to_conversation("assistant", filtered_response, st.session_state.session_id)

        update_analytics({"total_messages": 1})

        if not st.session_state.lead_captured:
            email = extract_email(user_input)
            name = extract_name(user_input)
            if email and name:
                hashed = hashlib.sha256(email.encode()).hexdigest()
                if hashed not in st.session_state.captured_emails:
                    engine.add_lead(name, email, context="chat_auto")
                    st.session_state.captured_emails.add(hashed)
                    st.session_state.lead_captured = True
                    update_analytics({"lead_captures": 1})
                    send_lead_notification(name, email, "chat_auto")
                    logger.info(f"Auto-captured lead: {name} <{email}>")

    except Exception as e:
        error_msg = "Sorry, I'm having a little teddy tantrum right now. Try again soon!"
        st.session_state.chat_history.append({"bot": error_msg, "timestamp": datetime.now().isoformat()})
        append_to_conversation("assistant", error_msg, st.session_state.session_id)
        logger.error(f"Response error: {e}", exc_info=True)

    finally:
        st.session_state.processing_active = False
        st.rerun()

# Auto-scroll
st.markdown("""
<script>
    const scrollDiv = parent.document.querySelector('.conversation-scroll');
    if (scrollDiv) {
        scrollDiv.scrollTop = scrollDiv.scrollHeight;
    }
</script>
""", unsafe_allow_html=True)
