import streamlit as st
from hybrid_engine import HybridEngine
from datetime import datetime
from pathlib import Path
import json, os, re, time, uuid, threading, logging
from typing import List, Dict, Optional
import sqlite3, hashlib, traceback
from rich.logging import RichHandler
from rich.traceback import install as install_rich_traceback
import pandas as pd

# Install rich traceback for better error formatting
install_rich_traceback()

# Setup & Configuration - Streamlit Cloud Compatible
st.set_page_config(
    page_title="TedPro Marketing Assistant 🧸",
    page_icon="🧸",
    layout="centered",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://cuddleheroes.example.com/support',
        'Report a bug': 'https://cuddleheroes.example.com/bugs',
        'About': 'TedPro: Your friendly plushie assistant by CuddleHeros!'
    }
)

# Configure logging with rich - Streamlit Cloud compatible
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("TedPro")
client_id = "tedpro_client"

# Database Setup with Connection Pooling
def get_db_connection():
    """Get SQLite connection with pooling and timeout"""
    db_path = Path(os.getenv("DB_PATH", "/tmp")) / f"{client_id}_chat_data.db"
    if db_path.parent == Path("/tmp"):
        st.warning("DB in /tmp—data may reset on redeploy. Use external DB for prod.")
    for attempt in range(3):
        try:
            conn = sqlite3.connect(db_path, timeout=10)
            return conn
        except sqlite3.OperationalError as e:
            logger.warning(f"DB connection attempt {attempt+1} failed: {e}")
            time.sleep(0.5)
    raise sqlite3.OperationalError("Failed to connect to database after retries")

def init_database():
    """Initialize SQLite database for better performance"""
    logger.info("Initializing database...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    session_id TEXT NOT NULL
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_session_timestamp ON conversations (session_id, timestamp)')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS analytics (
                    key TEXT PRIMARY KEY,
                    value INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    hashed_email TEXT UNIQUE NOT NULL,
                    context TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    consent TEXT
                )
            ''')
            conn.commit()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}", exc_info=True)
        raise

def append_to_conversation_db(role: str, content: str, session_id: str):
    """Append message to database"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO conversations (role, content, timestamp, session_id)
                VALUES (?, ?, ?, ?)
            ''', (role, content, datetime.now().isoformat(), session_id))
            cursor.execute('''
                DELETE FROM conversations 
                WHERE id NOT IN (
                    SELECT id FROM conversations 
                    WHERE session_id = ? 
                    ORDER BY timestamp DESC 
                    LIMIT 1000
                )
            ''', (session_id,))
            conn.commit()
        logger.debug(f"📝 Saved message to DB: {role} - {content[:50]}...")
    except Exception as e:
        logger.error(f"Database error: {e}", exc_info=True)

def load_recent_conversation_db(session_id: str, limit: int = 50) -> List[Dict]:
    """Load recent conversation from database"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT role, content, timestamp 
                FROM conversations 
                WHERE session_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (session_id, limit))
            messages = cursor.fetchall()
        return [{"role": msg[0], "content": msg[1], "timestamp": msg[2]} for msg in reversed(messages)]
    except Exception as e:
        logger.error(f"Database load error: {e}", exc_info=True)
        return []

def get_leads_df() -> pd.DataFrame:
    """Get leads as pandas DataFrame for export"""
    try:
        with get_db_connection() as conn:
            df = pd.read_sql_query("SELECT name, hashed_email, context, timestamp, consent FROM leads", conn)
        return df
    except Exception as e:
        logger.error(f"Lead export error: {e}", exc_info=True)
        return pd.DataFrame(columns=["name", "hashed_email", "context", "timestamp", "consent"])

def get_analytics_df() -> pd.DataFrame:
    """Get analytics as pandas DataFrame for export"""
    try:
        with get_db_connection() as conn:
            df = pd.read_sql_query("SELECT key, value, updated_at FROM analytics", conn)
        return df
    except Exception as e:
        logger.error(f"Analytics export error: {e}", exc_info=True)
        return pd.DataFrame(columns=["key", "value", "updated_at"])

# Core Functions
def get_key(name: str) -> Optional[str]:
    """Get API key with detailed logging"""
    env_value = os.getenv(name)
    secret_value = st.secrets.get(name)
    logger.debug(f"🔑 Key lookup - {name}:")
    logger.debug(f"  Environment: {'✅ Found' if env_value else '❌ Not found'}")
    logger.debug(f"  Secrets: {'✅ Found' if secret_value else '❌ Not found'}")
    return secret_value or env_value

def extract_email(text: str) -> Optional[str]:
    """Robust email validation using fullmatch"""
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    match = re.fullmatch(email_pattern, text.strip())
    return match.group(0) if match else None

def extract_name(text: str) -> str:
    """Simple name extraction - look for capitalized words that aren't email"""
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

@st.cache_data(ttl=1800, show_spinner=False)
def cached_engine_answer(_engine: HybridEngine, question: str) -> str:
    logger.info(f"🔍 Engine processing question: '{question}'")
    start_time = time.time()
    try:
        normalized = question.lower().strip()
        logger.debug(f"📤 Sending to engine: '{normalized}'")
        response = _engine.answer(normalized, "en")
        processing_time = time.time() - start_time
        logger.info(f"✅ Engine response received in {processing_time:.2f}s: '{response[:100]}...'")
        return response
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"❌ Engine error after {processing_time:.2f}s: {str(e)}", exc_info=True)
        return f"I'm having trouble right now. Please try again! 🧸 (Error: {str(e)})"

def teddy_filter(user_message: str, raw_answer: str, is_first: bool, lead_captured: bool) -> str:
    logger.debug(f"🎭 Applying teddy filter - First: {is_first}, Lead captured: {lead_captured}")
    
    # Only show greeting if it's the first message AND we haven't greeted yet in this session
    friendly_prefix = ""
    if is_first and not st.session_state.get("has_greeted", False):
        friendly_prefix = "Hi there, friend! 🧸 "
        st.session_state.has_greeted = True
        logger.debug("👋 First-time greeting added to response")
    
    sales_tail = ""
    if not lead_captured:
        if any(k in user_message.lower() for k in ["gift", "present", "birthday", "anniversary"]):
            sales_tail = " If this is a gift, I can suggest sizes or add a sweet note. 🎁"
        elif any(k in user_message.lower() for k in ["price", "how much", "cost", "buy"]):
            sales_tail = " I can also compare sizes to help you get the best value."
        elif any(k in user_message.lower() for k in ["custom", "personalize", "embroidery"]):
            sales_tail = " Tell me your idea—I'll check feasibility, timeline, and a fair quote."
    
    return f"{friendly_prefix}{raw_answer}{sales_tail}"

# Analytics with Batch Support
_analytics_lock = threading.Lock()
_analytics_batch: Dict[str, int] = {}

def get_analytics() -> Dict[str, int]:
    """Get analytics from database"""
    default = {
        "total_messages": 0, "faq_questions": 0, "lead_captures": 0, 
        "sales_related": 0, "order_tracking": 0, "total_sessions": 0,
        "affiliate_clicks": 0
    }
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key, value FROM analytics')
            results = cursor.fetchall()
        db_analytics = {row[0]: row[1] for row in results}
        return {**default, **db_analytics}
    except Exception as e:
        logger.error(f"Analytics load error: {e}", exc_info=True)
        return default

def update_analytics_batch(updates: Dict[str, int], immediate: bool = False):
    """Batch update analytics with optional immediate flush"""
    global _analytics_batch
    try:
        with _analytics_lock:
            for key, increment in updates.items():
                _analytics_batch[key] = _analytics_batch.get(key, 0) + increment
            if immediate or sum(_analytics_batch.values()) >= 10:
                if _analytics_batch:
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        for key, increment in _analytics_batch.items():
                            cursor.execute('''
                                INSERT INTO analytics (key, value, updated_at) 
                                VALUES (?, ?, ?)
                                ON CONFLICT(key) DO UPDATE SET 
                                value = value + excluded.value,
                                updated_at = excluded.updated_at
                            ''', (key, increment, datetime.now().isoformat()))
                        conn.commit()
                    if "analytics" in st.session_state:
                        current = st.session_state.analytics
                        for key, increment in _analytics_batch.items():
                            current[key] = current.get(key, 0) + increment
                        st.session_state.analytics = current
                    logger.debug(f"📊 Analytics updated: {_analytics_batch}")
                    _analytics_batch = {}
    except Exception as e:
        logger.error(f"Analytics update error: {e}", exc_info=True)

# Admin Dashboard
def render_admin_dashboard():
    """Render admin dashboard with leads and analytics export"""
    st.header("🧸 TedPro Admin Dashboard")
    st.markdown("Manage leads and analytics for CuddleHeros")
    
    # Leads section
    st.subheader("Leads")
    leads_df = get_leads_df()
    if not leads_df.empty:
        leads_df['est_value'] = leads_df['context'].apply(lambda x: 5 if 'sidebar' in x else 2)
        st.dataframe(leads_df, use_container_width=True)
        st.metric("Est. Total Lead Value", f"${leads_df['est_value'].sum()}")
        csv = leads_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Leads CSV",
            data=csv,
            file_name=f"cuddleheroes_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    else:
        st.info("No leads captured yet.")
    
    # Analytics section
    st.subheader("Analytics")
    analytics_df = get_analytics_df()
    if not analytics_df.empty:
        st.dataframe(analytics_df, use_container_width=True)
        csv = analytics_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Analytics CSV",
            data=csv,
            file_name=f"cuddleheroes_analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    else:
        st.info("No analytics data yet.")

# Debug Panel
def show_debug_panel():
    """Show debug information in sidebar"""
    with st.sidebar.expander("🔧 Debug Panel", expanded=False):
        st.write("**API Status:**")
        api_key = get_key("OPENROUTER_API_KEY")
        if api_key:
            masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
            st.success(f"✅ API Key: {masked_key}")
        else:
            st.error("❌ API Key: MISSING")
        if 'engine' in st.session_state:
            st.success("✅ Engine: Initialized")
        else:
            st.error("❌ Engine: Not initialized")
        try:
            db_path = Path("/tmp") / f"{client_id}_chat_data.db"
            if db_path.exists():
                st.success("✅ Database: Connected")
            else:
                st.warning("⚠️ Database: Not created yet")
        except:
            st.error("❌ Database: Error")
        st.write("**Session Info:**")
        st.write(f"Session ID: {st.session_state.get('session_id', 'None')}")
        st.write(f"Messages: {len(st.session_state.get('chat_history', []))}")
        if st.button("🔄 Clear Cache"):
            st.cache_data.clear()
            st.rerun()

# Engine Initialization
logger.info("🚀 Starting TedPro initialization...")

api_key = get_key("OPENROUTER_API_KEY")
if not api_key:
    logger.error("❌ CRITICAL: OPENROUTER_API_KEY not found!")
    st.error("""
    🔑 **API Key Missing!**
    
    **To fix this:**
    
    1. **Get API key** from [OpenRouter](https://openrouter.ai/keys)
    2. **Add to Streamlit Secrets:**
       - Go to app settings → Secrets
       - Add: `OPENROUTER_API_KEY = "your-key-here"`
    3. **Redeploy** the app
    """)
    st.stop()

try:
    init_database()
    logger.info("✅ Database initialized")
except Exception as e:
    logger.error(f"❌ Database initialization failed: {e}", exc_info=True)
    st.error(f"Database error: {e}")
    st.stop()

try:
    logger.info("🔄 Initializing HybridEngine...")
    start_time = time.time()
    if 'engine' not in st.session_state:
        engine = HybridEngine(api_key=api_key, client_id=client_id)
        st.session_state.engine = engine
    else:
        engine = st.session_state.engine
    init_time = time.time() - start_time
    logger.info(f"✅ HybridEngine initialized successfully in {init_time:.2f}s")
except Exception as e:
    logger.error(f"❌ Engine initialization failed: {str(e)}", exc_info=True)
    st.error(f"""
    ❌ **Engine Initialization Failed!**
    
    **Error:** {str(e)}
    
    **Check:**
    1. Is your OpenRouter API key valid?
    2. Does your account have credits?
    3. Check the logs for more details
    """)
    st.stop()

# Multi-Page Setup
pages = {
    "Chat": lambda: None,
    "Admin Dashboard": render_admin_dashboard
}
page = st.sidebar.selectbox("Select Page", list(pages.keys()), key="page_selector")
if page != "Chat":
    pages[page]()
    st.stop()

# UI Styling - Enhanced Performance with Orange Theme
st.markdown("""
<style>
body { 
    background: linear-gradient(180deg, #FFD5A5, #FFEDD2); 
    font-family: 'Arial', sans-serif; 
}
.user-msg { 
    background-color: #FFE1B3; 
    border-radius:10px; 
    padding:10px; 
    margin-bottom:8px; 
    border:1px solid #FFC085; 
    word-wrap: break-word;
    color: #2D1B00;
}
.bot-msg { 
    background-color: #FFF9F4; 
    border-left:5px solid #FFA94D; 
    border-radius:10px; 
    padding:10px; 
    margin-bottom:8px; 
    border:1px solid #FFE4CC; 
    word-wrap: break-word;
    color: #2D1B00;
}
.conversation-scroll { 
    max-height:400px; 
    overflow-y:auto; 
    padding:10px; 
    border:1px solid #FFE4CC; 
    border-radius:10px; 
    background-color:#FFFCF9; 
    scroll-behavior:smooth; 
    position: relative;
    transition: all 0.3s ease;
}
.quick-questions-form {
    border: 1px solid #FFD7A5;
    border-radius: 10px;
    padding: 15px;
    background: #FFF9F4;
    margin: 15px 0;
}
.quick-question-btn { 
    background-color:#FFEDD5; 
    border:1px solid #FFD7A5; 
    border-radius:8px; 
    padding:10px 6px; 
    cursor:pointer; 
    text-align:center; 
    transition: all 0.3s; 
    font-size:13px; 
    width:100%;
    border: none;
    min-height: 44px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #2D1B00;
    margin: 4px 0;
}
.quick-question-btn:hover { 
    background-color:#FFE1B3; 
    transform: translateY(-2px); 
    box-shadow: 0 4px 8px rgba(255, 165, 0, 0.2);
}
.quick-question-btn:disabled {
    background-color: #f0f0f0;
    color: #a0a0a0;
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
}
.analytics-badge {
    background: linear-gradient(135deg, #FFA94D, #FF922B);
    color: white;
    padding: 4px 8px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: bold;
}
.typing-indicator {
    display: flex;
    align-items: center;
    padding: 12px 16px;
    background: #FFF9F4;
    border-left: 5px solid #FFA94D;
    border-radius: 10px;
    margin-bottom: 8px;
    border: 1px solid #FFE4CC;
    font-style: italic;
    color: #5A3A1B;
    animation: fadeIn 0.3s ease-in;
}
.typing-dots {
    display: inline-flex;
    margin-left: 8px;
}
.typing-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background-color: #FF922B;
    margin: 0 2px;
    animation: typingAnimation 1.4s infinite ease-in-out;
}
.typing-dot:nth-child(1) { animation-delay: -0.32s; }
.typing-dot:nth-child(2) { animation-delay: -0.16s; }
.typing-dot:nth-child(3) { animation-delay: 0s; }
@keyframes typingAnimation {
    0%, 80%, 100% { 
        transform: scale(0.8);
        opacity: 0.5;
    }
    40% { 
        transform: scale(1);
        opacity: 1;
    }
}
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(5px); }
    to { opacity: 1; transform: translateY(0); }
}
.quick-questions-toggle {
    background: linear-gradient(135deg, #FFD8A5, #FFC085);
    border: 1px solid #FFB366;
    border-radius: 20px;
    padding: 6px 16px;
    font-size: 12px;
    color: #5A3A1B;
    cursor: pointer;
    transition: all 0.3s;
    margin: 10px 0;
}
.quick-questions-toggle:hover {
    background: linear-gradient(135deg, #FFC085, #FFA94D);
    transform: translateY(-1px);
}
.lead-banner {
    background: linear-gradient(135deg,#FFE8D6,#FFD8B5);
    padding:20px;
    border-radius:12px;
    margin:15px 0;
    text-align:center;
    border:2px dashed #FFA94D;
    animation: pulse 2s infinite;
}
@keyframes pulse {
    0% { border-color: #FFA94D; }
    50% { border-color: #FF922B; }
    100% { border-color: #FFA94D; }
}
.checkout-btn {
    background: linear-gradient(135deg, #FF922B, #FFA94D);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px;
    cursor: pointer;
    transition: all 0.3s;
    font-size: 14px;
    margin-top: 10px;
}
.checkout-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(255, 165, 0, 0.2);
}
.debug-panel {
    background: #f8f9fa;
    border: 1px solid #dee2e6;
    border-radius: 5px;
    padding: 10px;
    margin: 10px 0;
    font-family: monospace;
    font-size: 12px;
}
@media (max-width: 768px) {
    .quick-questions-grid {
        grid-template-columns: 1fr;
        gap: 6px;
    }
    .conversation-scroll {
        max-height: 350px;
        padding: 8px;
    }
    .user-msg, .bot-msg {
        padding: 8px;
        font-size: 14px;
    }
}
</style>

<script>
function scrollToBottom() {
    const scrollContainer = document.querySelector('.conversation-scroll');
    if (scrollContainer) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
        setTimeout(() => {
            scrollContainer.scrollTop = scrollContainer.scrollHeight;
        }, 150);
    }
}

const observer = new MutationObserver(scrollToBottom);
window.addEventListener('load', () => {
    const scrollContainer = document.querySelector('.conversation-scroll');
    if (scrollContainer) {
        observer.observe(scrollContainer, { childList: true, subtree: true });
    }
    scrollToBottom();
});

setInterval(scrollToBottom, 400);
</script>
""", unsafe_allow_html=True)

# Session State Initialization
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    update_analytics_batch({"total_sessions": 1}, immediate=True)
    logger.info(f"🆕 New session started: {st.session_state.session_id}")

default_states = {
    "chat_history": [],
    "show_history": False,
    "lead_captured": False,
    "lead_consent": False,
    "captured_emails": set(),
    "selected_quick_question": None,
    "show_quick_questions": False,
    "analytics": get_analytics(),
    "processing_active": False,
    "last_processed_time": 0,
    "user_message_count": 0,
    "last_lead_banner_shown": 0,
    "last_error": None,
    "affiliate_tag": st.secrets.get("AMAZON_TAG", "yourid-20"),
    "has_greeted": False,
}

for key, default_value in default_states.items():
    if key not in st.session_state:
        if key == "chat_history":
            recent_messages = load_recent_conversation_db(st.session_state.session_id, 50)
            st.session_state.chat_history = []
            for msg in recent_messages:
                if msg["role"] == "user":
                    st.session_state.chat_history.append({"user": msg["content"], "timestamp": msg["timestamp"]})
                else:
                    st.session_state.chat_history.append({"bot": msg["content"], "timestamp": msg["timestamp"]})
        else:
            st.session_state[key] = default_value

logger.debug(f"🔄 Session state initialized: {len(st.session_state.chat_history)} messages in history")

# Sidebar
st.sidebar.markdown("### 🧸 TedPro Assistant")
st.sidebar.markdown("Your friendly plushie expert!")

# Analytics
st.sidebar.markdown("### 📊 Live Analytics")
col1, col2 = st.sidebar.columns(2)
with col1:
    st.metric("Messages", st.session_state.analytics.get("total_messages", 0))
with col2: 
    st.metric("Leads", st.session_state.analytics.get("lead_captures", 0))

with st.sidebar.expander("📈 Detailed Metrics"):
    st.metric("FAQ Answers", st.session_state.analytics.get("faq_questions", 0))
    st.metric("Sales Inquiries", st.session_state.analytics.get("sales_related", 0))
    st.metric("Order Tracking", st.session_state.analytics.get("order_tracking", 0))
    st.metric("Total Sessions", st.session_state.analytics.get("total_sessions", 0))
    st.metric("Affiliate Clicks", st.session_state.analytics.get("affiliate_clicks", 0))

st.sidebar.markdown("---")
st.sidebar.markdown("### 💌 Get Our Plush Catalog")
name = st.sidebar.text_input("Your Name", key="sidebar_name")
email = st.sidebar.text_input("Your Email", key="sidebar_email")

subscribe_disabled = st.session_state.lead_captured
if st.sidebar.button(
    "✅ Already Subscribed!" if subscribe_disabled else "Subscribe & Get Catalog 🎁",
    disabled=subscribe_disabled,
    key="sidebar_subscribe"
):
    if name and email:
        extracted_email = extract_email(email)
        if extracted_email:
            try:
                hashed_email = hashlib.sha256(extracted_email.encode()).hexdigest()
                if hashed_email not in st.session_state.captured_emails:
                    engine.add_lead(name, extracted_email, context="sidebar_signup")
                    st.session_state.captured_emails.add(hashed_email)
                    update_analytics_batch({"lead_captures": 1})
                    st.session_state.lead_captured = True
                    st.session_state.sidebar_name = ""
                    st.session_state.sidebar_email = ""
                    st.sidebar.success("🎉 You're subscribed! We'll send the catalog soon.")
                    logger.info(f"📧 Lead captured: {name} <{extracted_email}>")
                    st.rerun()
                else:
                    st.sidebar.info("📧 You're already subscribed with this email!")
            except Exception as e:
                logger.error(f"Lead capture error: {e}", exc_info=True)
                st.sidebar.error(f"Failed to save subscription: {e}")
        else:
            st.sidebar.warning("Please enter a valid email address.")
    else:
        st.sidebar.warning("Please enter both name and email.")

show_debug_panel()

# Main Chat Interface
col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
with col1:
    st.markdown('<h1 style="color:#FF922B;">TedPro Marketing Assistant 🧸</h1>', unsafe_allow_html=True)
with col2:
    if st.button("📜 History", key="header_history_toggle"):
        st.session_state.show_history = not st.session_state.show_history
with col3:
    toggle_label = "❌ Hide" if st.session_state.show_quick_questions else "💡 Quick Q's"
    if st.button(toggle_label, key="quick_questions_toggle"):
        st.session_state.show_quick_questions = not st.session_state.show_quick_questions
with col4:
    st.markdown(
        f'<div class="analytics-badge">🆕 {st.session_state.analytics.get("total_sessions", 0)}</div>',
        unsafe_allow_html=True
    )

st.markdown('<p style="color:#5A3A1B;">Here to help with products, shipping, or special offers!</p>', unsafe_allow_html=True)

# Quick Questions
should_show_quick_questions = (
    st.session_state.show_quick_questions or 
    len(st.session_state.chat_history) == 0
)

if should_show_quick_questions and not st.session_state.processing_active:
    st.markdown("### 💡 Quick Questions")
    quick_questions = [
        "What's your pricing?", "Do you ship internationally?", 
        "Can I customize plushies?", "What's your return policy?", 
        "How long does shipping take?", "Do you have gift options?", 
        "What materials are used?", "Can I track my order?",
        "Do you offer discounts?", "What sizes are available?"
    ]
    
    with st.form("quick_questions_form"):
        st.markdown('<div class="quick-questions-form">', unsafe_allow_html=True)
        selected_question = st.radio(
            "Choose a question:",
            quick_questions,
            key="quick_questions_radio",
            label_visibility="collapsed"
        )
        submitted = st.form_submit_button("Ask this question")
        st.markdown('</div>', unsafe_allow_html=True)
        if submitted and selected_question:
            st.session_state.selected_quick_question = selected_question
            logger.info(f"🎯 Quick question selected: {selected_question}")

# Lead Banner
def should_show_lead_banner() -> bool:
    """Determine if lead banner should be shown"""
    if st.session_state.lead_captured:
        return False
    user_message_count = st.session_state.user_message_count
    last_shown = st.session_state.last_lead_banner_shown
    return (user_message_count == 0 or 
            (user_message_count >= 3 and user_message_count - last_shown >= 3))

if should_show_lead_banner():
    banner_text = """
    <div class='lead-banner'>
    <h4 style='color:#E65C00;margin:0'>🎁 Special Offer for New Friends!</h4>
    <p style='margin:8px 0;font-size:15px;color:#5A3A1B;'>Get our <b>free plushie catalog</b> + <b>10% discount</b> on your first order!</p>
    <p style='margin:0;font-style:italic;color:#8B5A2B'>Just ask about our products or drop your email in the sidebar →</p>
    </div>
    """
    st.markdown(banner_text, unsafe_allow_html=True)
    st.session_state.last_lead_banner_shown = st.session_state.user_message_count

# Chat Display Function
def display_chat():
    """Display chat messages"""
    st.markdown('<div class="conversation-scroll">', unsafe_allow_html=True)
    display_messages = st.session_state.chat_history[-20:]
    for msg in display_messages:
        if "user" in msg:
            st.markdown(
                f"<div class='user-msg'><b>You:</b> {msg['user']}"
                f"<div style='font-size:11px;color:#5A3A1B;text-align:right'>{format_timestamp(msg['timestamp'])}</div></div>",
                unsafe_allow_html=True
            )
        elif "bot" in msg:
            st.markdown(
                f"<div class='bot-msg'><b>TedPro:</b> {msg['bot']}"
                f"<div style='font-size:11px;color:#5A3A1B;text-align:right'>{format_timestamp(msg['timestamp'])}</div></div>",
                unsafe_allow_html=True
            )
    st.markdown('</div>', unsafe_allow_html=True)

# Message Processing
def process_message(user_input: str):
    """Optimized message processing with streaming and enhanced features"""
    current_time = time.time()
    if current_time - st.session_state.last_processed_time < 0.5:
        return
    st.session_state.last_processed_time = current_time
    logger.info(f"🔄 Processing message: '{user_input}'")
    try:
        st.session_state.user_message_count += 1
        analytics_updates = {"total_messages": 1}
        user_input_lower = user_input.lower()
        if any(k in user_input_lower for k in ["price", "buy", "order", "cost", "purchase"]):
            analytics_updates["sales_related"] = 1
        if any(k in user_input_lower for k in ["track", "shipping", "delivery"]) and any(c.isdigit() for c in user_input):
            analytics_updates["order_tracking"] = 1
        
        extracted_email = None
        extracted_name = "Friend"
        if not st.session_state.lead_captured and st.session_state.lead_consent:
            extracted_email = extract_email(user_input)
            if extracted_email and hashlib.sha256(extracted_email.encode()).hexdigest() not in st.session_state.captured_emails:
                extracted_name = extract_name(user_input)
                hashed_email = hashlib.sha256(extracted_email.encode()).hexdigest()
                try:
                    engine.add_lead(extracted_name, extracted_email, context="chat_auto_capture")
                    analytics_updates["lead_captures"] = 1
                    st.session_state.captured_emails.add(hashed_email)
                    st.session_state.lead_captured = True
                    logger.info(f"📧 Auto-captured lead: {extracted_name} <{extracted_email}>")
                except Exception as e:
                    logger.error(f"Lead capture error: {e}", exc_info=True)
                    st.session_state.last_error = str(e)
        elif "yes" in user_input_lower and not st.session_state.lead_consent:
            st.session_state.lead_consent = True

        start_time = time.time()
        try:
            user_messages_before = len([m for m in st.session_state.chat_history if "user" in m])
            is_first = user_messages_before == 1
            bot_placeholder = st.empty()
            bot_placeholder.markdown("""
            <div class="typing-indicator">
                Teddy is typing
                <div class="typing-dots">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            raw_response = ""
            for chunk in engine.stream_answer(user_input):
                raw_response += chunk
                bot_placeholder.markdown(
                    f"<div class='bot-msg'><b>TedPro:</b> {raw_response}"
                    f"<div style='font-size:11px;color:#5A3A1B;text-align:right'>{format_timestamp(datetime.now().isoformat())}</div></div>",
                    unsafe_allow_html=True
                )

            # Apply teddy filter to add personality
            filtered_response = teddy_filter(user_input, raw_response, is_first, st.session_state.lead_captured)

            # Add consent prompt if needed
            if not st.session_state.lead_consent:
                filtered_response += " Can I save your email for updates? Reply YES."

            is_purchase_intent = any(k in user_input_lower for k in ["buy", "order", "purchase"])
            
            if is_purchase_intent:
                affiliate_url = f"https://amazon.com/s?k=plushies&tag={st.session_state.affiliate_tag}"
                filtered_response += f" 💳 You can place your order anytime at [Amazon]({affiliate_url})."

            # Update the final display with the filtered response
            bot_placeholder.markdown(
                f"<div class='bot-msg'><b>TedPro:</b> {filtered_response}"
                f"<div style='font-size:11px;color:#5A3A1B;text-align:right'>{format_timestamp(datetime.now().isoformat())}</div></div>",
                unsafe_allow_html=True
            )

            if is_purchase_intent:
                if st.button(
                    "Shop on Amazon",
                    key=f"affiliate_{uuid.uuid4()}",
                    help="Go to affiliate link"
                ):
                    update_analytics_batch({"affiliate_clicks": 1})
                    st.markdown(f"<a href='{affiliate_url}' target='_blank'>Redirecting to Amazon...</a>", unsafe_allow_html=True)
                    logger.info("💳 Affiliate click tracked")

            if st.button(
                "Checkout Now",
                key=f"checkout_{uuid.uuid4()}",
                help="Proceed to mock checkout"
            ):
                st.markdown(
                    f"<div class='bot-msg'><b>TedPro:</b> Redirecting to secure checkout... (Mock Stripe flow)</div>",
                    unsafe_allow_html=True
                )
                logger.info("💳 Mock checkout initiated")

            bot_message_data = {"bot": filtered_response, "timestamp": datetime.now().isoformat()}
            st.session_state.chat_history.append(bot_message_data)
            append_to_conversation_db("assistant", filtered_response, st.session_state.session_id)

            if extracted_email and hashlib.sha256(extracted_email.encode()).hexdigest() in st.session_state.captured_emails:
                lead_placeholder = st.empty()
                lead_message = f"📧 Thanks, {extracted_name}! I've added {extracted_email} to our updates list!"
                lead_placeholder.markdown(
                    f"<div class='bot-msg'><b>TedPro:</b> {lead_message}"
                    f"<div style='font-size:11px;color:#5A3A1B;text-align:right'>{format_timestamp(datetime.now().isoformat())}</div></div>",
                    unsafe_allow_html=True
                )
                lead_message_data = {"bot": lead_message, "timestamp": datetime.now().isoformat()}
                st.session_state.chat_history.append(lead_message_data)
                append_to_conversation_db("assistant", lead_message, st.session_state.session_id)

            processing_time = time.time() - start_time
            logger.info(f"✅ Message processed successfully in {processing_time:.2f}s")

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"❌ Message processing error after {processing_time:.2f}s: {str(e)}", exc_info=True)
            st.session_state.last_error = str(e)
            error_message = f"I'm having a little trouble right now. Please try again soon! 🧸 (Error: {str(e)})"
            bot_placeholder.markdown(
                f"<div class='bot-msg'><b>TedPro:</b> {error_message}"
                f"<div style='font-size:11px;color:#5A3A1B;text-align:right'>{format_timestamp(datetime.now().isoformat())}</div></div>",
                unsafe_allow_html=True
            )
            error_message_data = {"bot": error_message, "timestamp": datetime.now().isoformat()}
            st.session_state.chat_history.append(error_message_data)
            append_to_conversation_db("assistant", error_message_data["bot"], st.session_state.session_id)
        
        update_analytics_batch(analytics_updates)
    
    finally:
        st.session_state.processing_active = False
        logger.debug("🔄 Message processing completed")
        st.rerun()

# Main chat rendering
if st.session_state.show_history:
    st.subheader("📜 Conversation History")
    if st.session_state.chat_history:
        display_chat()
    else:
        st.info("No chat history yet!")
else:
    if st.session_state.chat_history:
        display_chat()
    elif not st.session_state.show_quick_questions:
        st.info("💬 Start a conversation or click 'Quick Q's' for common questions!")

# Process quick question or user input
user_input = st.chat_input(
    "Ask me about plushies, pricing, shipping, or anything else! 🧸",
    disabled=st.session_state.processing_active
)

if st.session_state.selected_quick_question and not st.session_state.processing_active:
    logger.info(f"🎯 Processing quick question: {st.session_state.selected_quick_question}")
    user_input = st.session_state.selected_quick_question
    st.session_state.selected_quick_question = None

if user_input and not st.session_state.processing_active:
    logger.info(f"💬 Input received: {user_input}")
    st.session_state.processing_active = True
    append_to_conversation_db("user", user_input, st.session_state.session_id)
    st.session_state.chat_history.append({"user": user_input, "timestamp": datetime.now().isoformat()})
    st.rerun()

if (
    st.session_state.chat_history
    and "user" in st.session_state.chat_history[-1]
    and st.session_state.processing_active
):
    process_message(st.session_state.chat_history[-1]["user"])

# Flush analytics
update_analytics_batch({}, immediate=True)

# Footer
st.markdown("""
<br>
<hr>
<center>
<small style="color: #5A3A1B;">© 2025 TedPro Pro Chatbot by The Cuddleheros Team 🧸</small>
<br>
<small style="color: #FFA94D;">Professional Plushie Assistant v3.1 - Complete Version | Upgrade to SaaS Pro Contact us!</small>
</center>
""", unsafe_allow_html=True)

