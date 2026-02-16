import streamlit as st
from hybrid_engine import HybridEngine
from datetime import datetime, timedelta
import uuid, time, hashlib, re, os, logging
from typing import List, Dict, Optional
from supabase import create_client, Client

# --- 1. CONFIG & API SETUP ---
st.set_page_config(
    page_title="TedPro Marketing Assistant 🧸",
    page_icon="🧸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Timezone Fix: Adjusting for the 2-hour offset you mentioned
# If server is 00:48 and you are 02:52, we add a 2-hour offset.
def get_teddy_time():
    utc_now = datetime.now()
    # Adding 2 hours to match your local time reported
    local_now = utc_now + timedelta(hours=2)
    return local_now.strftime("%H:%M")

# --- 2. THE "GELLED" UI DESIGN ---
st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@400;600&display=swap');
    html, body, [class*="css"] {{ font-family: 'Quicksand', sans-serif; }}
    
    .stApp {{ background: #FFF9F4; }}
    
    /* Clean Chat Bubbles */
    .chat-container {{
        padding: 20px;
        max-width: 900px;
        margin: auto;
    }}
    .user-msg {{
        background: #FFD8A8;
        color: #432818;
        padding: 15px;
        border-radius: 18px 18px 2px 18px;
        margin: 10px 0 10px auto;
        width: fit-content;
        max-width: 80%;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }}
    .bot-msg {{
        background: white;
        color: #5A3A1B;
        padding: 15px;
        border-radius: 18px 18px 18px 2px;
        margin: 10px auto 10px 0;
        width: fit-content;
        max-width: 80%;
        border: 1px solid #FFE4CC;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }}
    .time-stamp {{
        font-size: 0.7em;
        opacity: 0.5;
        margin-top: 5px;
        text-align: right;
    }}
    
    /* Hide Streamlit Header/Footer */
    header, footer {{ visibility: hidden; }}
</style>
""", unsafe_allow_html=True)

# --- 3. BACKEND INITIALIZATION (Restored from your code) ---
@st.cache_resource
def init_engine():
    api_key = st.secrets.get("OPENROUTER_API_KEY")
    sb_url = st.secrets.get("SUPABASE_URL")
    sb_key = st.secrets.get("SUPABASE_KEY")
    if not all([api_key, sb_url, sb_key]):
        st.error("Missing API Keys in Secrets!")
        st.stop()
    return HybridEngine(api_key=api_key, supabase_url=sb_url, supabase_key=sb_key, client_id="tedpro_client")

engine = init_engine()

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.chat_history = []
    st.session_state.lead_captured = False

# --- 4. TEDDY'S PERSONALITY FILTER ---
def apply_teddy_vibes(text: str) -> str:
    # Adding warmth and personality without being annoying
    warm_closers = ["Paws and hugs, Teddy 🧸", "Stay cozy! 🍯", "Waiting for your next question! ✨"]
    if "price" in text.lower() or "cost" in text.lower():
        text = "I've sniffed out the best value for you! " + text
    return f"{text}\n\n*{warm_closers[int(time.time()) % 3]}*"

# --- 5. SIDEBAR & NAVIGATION ---
with st.sidebar:
    st.markdown("# 🧸 TedPro Hub")
    st.caption("Professional Plushie Assistant")
    st.markdown("---")
    
    # Newsletter / Lead Gen (Cleaner Sidebar Version)
    if not st.session_state.lead_captured:
        st.markdown("### 🍯 Join the Honey-Pot")
        st.write("Get our secret catalog and 10% off!")
        l_name = st.text_input("Name", placeholder="Your name")
        l_email = st.text_input("Email", placeholder="hello@friend.com")
        if st.button("Send Me the Catalog 🎁", use_container_width=True):
            if l_email and "@" in l_email:
                engine.add_lead(l_name, l_email, context="sidebar_v3")
                st.session_state.lead_captured = True
                st.success("Check your inbox, friend!")
                st.rerun()
    else:
        st.success("✅ You're a VIP Cuddler!")
    
    st.markdown("---")
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()

# --- 6. MAIN CHAT FLOW ---
st.title("Hi! I'm Teddy. Let's chat! 🧸")

# Quick Question Buttons (Removed the clunky form, made them Instant)
st.markdown("##### 💡 Ask me about...")
q_cols = st.columns(4)
quick_qs = ["Pricing 💰", "Shipping 📦", "Custom Work 🎨", "Safety ✅"]

for i, label in enumerate(quick_qs):
    if q_cols[i].button(label, use_container_width=True):
        user_q = label.split(" ")[0] # Get the text only
        st.session_state.chat_history.append({"role": "user", "content": user_q, "time": get_teddy_time()})
        
        with st.spinner("Sniffing out the answer..."):
            raw_response = "".join([chunk for chunk in engine.stream_answer(user_q)])
            final_response = apply_teddy_vibes(raw_response)
            st.session_state.chat_history.append({"role": "assistant", "content": final_response, "time": get_teddy_time()})
        st.rerun()

# Display Chat History
chat_placeholder = st.container()
with chat_placeholder:
    for msg in st.session_state.chat_history:
        div_class = "user-msg" if msg["role"] == "user" else "bot-msg"
        st.markdown(f"""
            <div class="{div_class}">
                {msg['content']}
                <div class="time-stamp">{msg['time']}</div>
            </div>
        """, unsafe_allow_html=True)

# User Input
if prompt := st.chat_input("Ask me anything about CuddleHeros..."):
    # Add User Message
    t = get_teddy_time()
    st.session_state.chat_history.append({"role": "user", "content": prompt, "time": t})
    
    # Generate Bot Response
    with st.spinner("Teddy is thinking..."):
        raw_response = "".join([chunk for chunk in engine.stream_answer(prompt)])
        final_response = apply_teddy_vibes(raw_response)
        st.session_state.chat_history.append({"role": "assistant", "content": final_response, "time": t})
    
    st.rerun()
