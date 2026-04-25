import streamlit as st
from hybrid_engine import HybridEngine
from datetime import datetime, timedelta
import uuid, time, hashlib, re, os, logging
from typing import List, Dict, Optional
from supabase import create_client, Client
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- 1. CONFIG & API SETUP ---
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

# --- 6. LEAD CAPTURE COMPONENT ---
def render_lead_capture():
    """Render lead capture banner - shows form or success message persistently"""
    with st.container():
        if not st.session_state.lead_captured or st.session_state.test_mode:
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
                            st.success("✅ Welcome to the VIP Cuddlers club! Check your email for the secret catalog.")
                            # Link lead to session
                            try:
                                engine.supabase.table('leads').update({
                                    'session_id': st.session_state.session_id
                                }).eq('email', l_email).execute()
                            except Exception as e:
                                logging.error(f"Lead session link error: {e}")
                        else:
                            st.error("❌ Couldn't save your info. The email might already be registered.")
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")
            elif submit:
                st.warning("Please enter a valid email address 📧")
        else:
            st.success("✅ You're a VIP Cuddler! Check your email for the secret catalog.")

# --- 6b. CONVERSATION SAVING ---
def save_conversation(user_msg: str, bot_msg: str):
    """Save conversation exchange to Supabase"""
    try:
        engine.supabase.table('conversations').insert({
            'session_id': st.session_state.session_id,
            'client_id': 'tedpro_client',
            'user_message': user_msg,
            'bot_response': bot_msg,
            'created_at': datetime.now().isoformat(),
            'metadata': {'source': 'main_chat'}
        }).execute()
    except Exception as e:
        logging.error(f"Conversation save error: {e}")


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

# Lead capture - always show banner area after first exchange
if len(st.session_state.chat_history) >= 2:
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
            with st.spinner(""):
                raw_response = "".join([chunk for chunk in engine.stream_answer(last_msg["content"])])
                final_response = apply_teddy_vibes(raw_response)

            st.session_state.chat_history.append({
                "role": "assistant", 
                "content": final_response, 
                "time": get_teddy_time()
            })
            # Save conversation to Supabase
            save_conversation(last_msg["content"], final_response)
        except Exception as e:
            error_msg = "I'm having trouble connecting right now. Please try again! 🧸"
            st.session_state.chat_history.append({
                "role": "assistant", 
                "content": error_msg, 
                "time": get_teddy_time()
            })
            logging.error(f"Chat error: {e}")

        st.session_state.typing = False
        st.rerun()
