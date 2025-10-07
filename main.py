import streamlit as st
from hybrid_engine import HybridEngine
from datetime import datetime
from pathlib import Path
import json
import os
import re
import time
import uuid
import random
import threading
import logging
from typing import List, Set
import sqlite3
import hashlib
import traceback
import concurrent.futures

# -----------------------------
# Setup & Configuration - Streamlit Cloud Compatible
# -----------------------------
st.set_page_config(
    page_title="TedPro Marketing Assistant 🧸",
    page_icon="🧸",
    layout="centered"
)

# Configure logging - Streamlit Cloud compatible (NO FileHandler)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # Only StreamHandler for cloud compatibility
)
logger = logging.getLogger("TedPro")

# -----------------------------
# Safe Engine Wrapper with Timeout
# -----------------------------
def safe_engine_answer(engine, question):
    """Wrapper with timeout protection around engine calls"""
    logger.info(f"🚀 Engine answering: '{question}'")
    start_time = time.time()
    
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(engine.answer, question)
            result = future.result(timeout=25)
            elapsed = time.time() - start_time
            logger.info(f"✅ Engine answered in {elapsed:.2f}s: '{result[:80]}...'")
            return result
    except concurrent.futures.TimeoutError:
        elapsed = time.time() - start_time
        logger.error(f"❌ Engine timeout after {elapsed:.2f}s for: '{question}'")
        return "Teddy got a bit sleepy waiting for a reply! 🧸 Please try again in a moment."
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Engine error after {elapsed:.2f}s: {e}")
        logger.error(traceback.format_exc())
        return f"I'm having trouble right now. Please try again! 🧸 (Error: {str(e)})"

# -----------------------------
# Debug Panel
# -----------------------------
def show_debug_panel():
    """Show debug information in sidebar"""
    with st.sidebar.expander("🔧 Debug Panel", expanded=False):
        st.write("**API Status:**")
        
        # Check API key
        api_key = get_key("OPENROUTER_API_KEY")
        if api_key:
            masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
            st.success(f"✅ API Key: {masked_key}")
        else:
            st.error("❌ API Key: MISSING")
        
        # Engine status
        if 'engine' in st.session_state:
            st.success("✅ Engine: Initialized")
        else:
            st.error("❌ Engine: Not initialized")
        
        # Session info
        st.write("**Session Info:**")
        st.write(f"Session ID: {st.session_state.get('session_id', 'None')}")
        st.write(f"Messages: {len(st.session_state.get('chat_history', []))}")
        st.write(f"Processing Active: {st.session_state.get('processing_active', False)}")
        
        # Clear cache button
        if st.button("🔄 Clear Cache"):
            st.cache_data.clear()
            st.rerun()

# -----------------------------
# Database Setup for Performance
# -----------------------------
def init_database():
    """Initialize SQLite database for better performance"""
    logger.info("Initializing database...")
    # Use /tmp directory which has write permissions on Streamlit Cloud
    db_path = Path("/tmp") / f"{client_id}_chat_data.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Conversations table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL
            )
        ''')
        
        # Analytics table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS analytics (
                key TEXT PRIMARY KEY,
                value INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        ''')
        
        # Leads table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                context TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise

def append_to_conversation_db(role, content, session_id):
    """Append message to database"""
    try:
        db_path = Path("/tmp") / f"{client_id}_chat_data.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO conversations (role, content, timestamp, session_id)
            VALUES (?, ?, ?, ?)
        ''', (role, content, datetime.now().isoformat(), session_id))
        
        conn.commit()
        conn.close()
        logger.debug(f"📝 Saved message to DB: {role} - {content[:50]}...")
    except Exception as e:
        logger.error(f"Database error: {e}")

# -----------------------------
# Core Functions
# -----------------------------
def get_key(name: str):
    """Get API key with detailed logging"""
    env_value = os.getenv(name)
    secret_value = st.secrets.get(name)
    
    return secret_value or env_value

def extract_email(text: str):
    """Robust email validation using fullmatch"""
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    match = re.fullmatch(email_pattern, text.strip())
    return match.group(0) if match else None

def extract_name(text: str):
    """Simple name extraction - look for capitalized words that aren't email"""
    words = text.split()
    for word in words:
        if (word.istitle() and len(word) > 1 and 
            '@' not in word and '.' not in word and
            not any(char.isdigit() for char in word)):
            return word
    return "Friend"

def format_timestamp():
    """Simple timestamp formatting"""
    return datetime.now().strftime("%H:%M")

def teddy_filter(user_message: str, raw_answer: str, is_first: bool, lead_captured: bool) -> str:
    logger.debug(f"🎭 Applying teddy filter - First: {is_first}, Lead captured: {lead_captured}")
    
    friendly_prefix = "Hi there, friend! 🧸 " if is_first else ""
    sales_tail = ""
    
    if not lead_captured:
        if any(k in user_message.lower() for k in ["gift", "present", "birthday", "anniversary"]):
            sales_tail = " If this is a gift, I can suggest sizes or add a sweet note. 🎁"
        elif any(k in user_message.lower() for k in ["price", "how much", "cost", "buy"]):
            sales_tail = " I can also compare sizes to help you get the best value."
        elif any(k in user_message.lower() for k in ["custom", "personalize", "embroidery"]):
            sales_tail = " Tell me your idea—I'll check feasibility, timeline, and a fair quote."
    
    if any(k in user_message.lower() for k in ["buy", "order", "purchase"]):
        sales_tail += " 💳 You can place your order anytime at [Cuddleheroes Store](https://cuddleheroes.example.com)."
    
    return f"{friendly_prefix}{raw_answer}{sales_tail}"

# -----------------------------
# Analytics with Batch Support
# -----------------------------
_analytics_lock = threading.Lock()
_analytics_batch = {}

def get_analytics():
    """Get analytics from database"""
    default = {
        "total_messages": 0, "faq_questions": 0, "lead_captures": 0, 
        "sales_related": 0, "order_tracking": 0, "total_sessions": 0
    }
    try:
        db_path = Path("/tmp") / f"{client_id}_chat_data.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT key, value FROM analytics')
        results = cursor.fetchall()
        conn.close()
        
        db_analytics = {row[0]: row[1] for row in results}
        return {**default, **db_analytics}
    except Exception as e:
        logger.error(f"Analytics load error: {e}")
        return default

def update_analytics_batch(updates, immediate=False):
    """Batch update analytics with optional immediate flush"""
    global _analytics_batch
    
    try:
        with _analytics_lock:
            # Merge updates into batch
            for key, increment in updates.items():
                _analytics_batch[key] = _analytics_batch.get(key, 0) + increment
            
            # Flush if immediate or batch is large
            if immediate or sum(_analytics_batch.values()) >= 10:
                if _analytics_batch:
                    db_path = Path("/tmp") / f"{client_id}_chat_data.db"
                    conn = sqlite3.connect(db_path)
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
                    conn.close()
                    
                    # Update session state
                    if "analytics" in st.session_state:
                        current = st.session_state.analytics
                        for key, increment in _analytics_batch.items():
                            current[key] = current.get(key, 0) + increment
                        st.session_state.analytics = current
                    
                    logger.debug(f"📊 Analytics updated: {_analytics_batch}")
                    _analytics_batch = {}
                    
    except Exception as e:
        logger.error(f"Analytics update error: {e}")

# -----------------------------
# Engine Initialization
# -----------------------------
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
       - Add: OPENROUTER_API_KEY = "your-key-here"
    3. **Redeploy** the app
    """)
    st.stop()

logger.info("✅ API key found, initializing engine...")

client_id = "tedpro_client"

# Initialize database
try:
    init_database()
    logger.info("✅ Database initialized")
except Exception as e:
    logger.error(f"❌ Database initialization failed: {e}")
    st.error(f"Database error: {e}")
    st.stop()

# Initialize engine
try:
    logger.info("🔄 Initializing HybridEngine...")
    
    engine = HybridEngine(api_key=api_key, client_id=client_id)
    
    # Store engine in session state for persistence
    st.session_state.engine = engine
    logger.info("✅ HybridEngine initialized successfully")
    
except Exception as e:
    logger.error(f"❌ Engine initialization failed: {str(e)}")
    logger.error(f"🔍 Full traceback: {traceback.format_exc()}")
    st.error(f"""
    ❌ **Engine Initialization Failed!**
    
    **Error:** {str(e)}
    """)
    st.stop()

# Show debug panel
show_debug_panel()

# -----------------------------
# UI Styling
# -----------------------------
st.markdown("""
<style>
.chat-message {
    padding: 1rem;
    border-radius: 0.5rem;
    margin-bottom: 1rem;
    display: flex;
    flex-direction: column;
}
.chat-message.user {
    background-color: #FFE1B3;
    border: 1px solid #FFC085;
}
.chat-message.assistant {
    background-color: #FFF9F4;
    border-left: 5px solid #FFA94D;
    border: 1px solid #FFE4CC;
}
.chat-timestamp {
    font-size: 0.75rem;
    color: #5A3A1B;
    text-align: right;
    margin-top: 0.5rem;
}
.typing-indicator {
    display: flex;
    align-items: center;
    padding: 1rem;
    background: #FFF9F4;
    border-left: 5px solid #FFA94D;
    border-radius: 0.5rem;
    margin-bottom: 1rem;
    border: 1px solid #FFE4CC;
    font-style: italic;
    color: #5A3A1B;
}
.typing-dots {
    display: inline-flex;
    margin-left: 0.5rem;
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
</style>
""", unsafe_allow_html=True)

# -----------------------------
# Session State Initialization
# -----------------------------
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    update_analytics_batch({"total_sessions": 1}, immediate=True)
    logger.info(f"🆕 New session started: {st.session_state.session_id}")

# Initialize session state
default_states = {
    "chat_history": [],
    "show_history": False,
    "lead_captured": False,
    "captured_emails": set(),
    "selected_quick_question": None,
    "show_quick_questions": False,
    "analytics": get_analytics(),
    "processing_active": False,
    "last_processed_time": 0,
    "user_message_count": 0,
    "last_lead_banner_shown": 0,
}

for key, default_value in default_states.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

logger.debug(f"🔄 Session state initialized: {len(st.session_state.chat_history)} messages in history")

# -----------------------------
# Sidebar
# -----------------------------
st.sidebar.markdown("### 🧸 TedPro Assistant")
st.sidebar.markdown("Your friendly plushie expert!")

# Analytics
st.sidebar.markdown("### 📊 Live Analytics")
col1, col2 = st.sidebar.columns(2)
with col1:
    st.metric("Messages", st.session_state.analytics.get("total_messages", 0))
with col2: 
    st.metric("Leads", st.session_state.analytics.get("lead_captures", 0))

# -----------------------------
# Main Chat Interface
# -----------------------------
st.markdown('<h1 style="color:#FF922B;">TedPro Marketing Assistant 🧸</h1>', unsafe_allow_html=True)
st.markdown('<p style="color:#5A3A1B;">Here to help with products, shipping, or special offers!</p>', unsafe_allow_html=True)

# Display chat messages
for message in st.session_state.chat_history:
    if "user" in message:
        st.markdown(f"""
        <div class="chat-message user">
            <div><strong>You:</strong> {message['user']}</div>
            <div class="chat-timestamp">{message.get('timestamp', '')}</div>
        </div>
        """, unsafe_allow_html=True)
    elif "bot" in message:
        st.markdown(f"""
        <div class="chat-message assistant">
            <div><strong>TedPro:</strong> {message['bot']}</div>
            <div class="chat-timestamp">{message.get('timestamp', '')}</div>
        </div>
        """, unsafe_allow_html=True)

# Show typing indicator if processing
if st.session_state.processing_active:
    st.markdown("""
    <div class="typing-indicator">
        Teddy is typing
        <div class="typing-dots">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# -----------------------------
# Message Processing
# -----------------------------
def process_message(user_input):
    """Simplified message processing that actually works"""
    if not user_input or st.session_state.processing_active:
        return
    
    # Rate limiting
    current_time = time.time()
    if current_time - st.session_state.last_processed_time < 1.0:
        return
    
    st.session_state.processing_active = True
    st.session_state.last_processed_time = current_time
    
    logger.info(f"🔄 Processing message: '{user_input}'")
    
    try:
        # Track user message count
        st.session_state.user_message_count += 1
        
        # Add user message to history immediately
        user_message_data = {
            "user": user_input, 
            "timestamp": format_timestamp()
        }
        st.session_state.chat_history.append(user_message_data)
        append_to_conversation_db("user", user_input, st.session_state.session_id)
        
        # Analytics
        analytics_updates = {"total_messages": 1}
        
        # Process the response
        try:
            user_messages_before = len([m for m in st.session_state.chat_history if "user" in m])
            is_first = user_messages_before == 1
            
            # Get response directly without caching issues
            logger.info("🟢 Getting engine response...")
            raw_response = engine.answer(user_input)
            filtered_response = teddy_filter(user_input, raw_response, is_first, st.session_state.lead_captured)
            
            # Add bot response to history
            bot_message_data = {
                "bot": filtered_response, 
                "timestamp": format_timestamp()
            }
            st.session_state.chat_history.append(bot_message_data)
            append_to_conversation_db("assistant", filtered_response, st.session_state.session_id)
            
            logger.info(f"✅ Message processed successfully")
                
        except Exception as e:
            logger.error(f"❌ Message processing error: {str(e)}")
            error_message_data = {
                "bot": f"I'm having a little trouble right now. Please try again soon! 🧸", 
                "timestamp": format_timestamp()
            }
            st.session_state.chat_history.append(error_message_data)
            append_to_conversation_db("assistant", error_message_data["bot"], st.session_state.session_id)
        
        # Update analytics
        update_analytics_batch(analytics_updates)
        
    finally:
        st.session_state.processing_active = False
        logger.debug("🔄 Message processing completed")
        # Force a rerun to update the UI
        st.rerun()

# Process regular chat input
user_input = st.chat_input("Ask me about plushies, pricing, shipping, or anything else! 🧸")
if user_input and not st.session_state.processing_active:
    logger.info(f"💬 User input received: {user_input}")
    process_message(user_input)

# Flush analytics
update_analytics_batch({}, immediate=True)

# -----------------------------
# Footer
# -----------------------------
st.markdown("""
<br>
<hr>
<center>
<small style="color: #5A3A1B;">© 2025 TedPro Pro Chatbot by Tash & Hendrik 🧸</small>
<br>
<small style="color: #FFA94D;">Professional Plushie Assistant v3.2 - Display Fixed</small>
</center>
""", unsafe_allow_html=True)

logger.info("🏁 TedPro application loaded successfully")
