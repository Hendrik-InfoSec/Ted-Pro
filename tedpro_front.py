import os
from datetime import datetime
import streamlit as st
from hybrid_engine import HybridEngine

# -------------------------
# Page config
# -------------------------
st.set_page_config(
    page_title="🧸 Ted Pro — Cuddleheroes",
    layout="centered",
    initial_sidebar_state="collapsed",
    page_icon="🧸"
)

# -------------------------
# Inject CSS to hide Streamlit UI + style
# -------------------------
def inject_global_hides():
    st.markdown("""
    <style>
    /* Hide Streamlit default UI */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stSidebar"] {display: none;}
    [data-testid="stToolbar"] {display: none !important;}
    .stAppDeployButton {display: none !important;}
    .viewerBadge_container__1QSob {display: none !important;}
    </style>
    """, unsafe_allow_html=True)

inject_global_hides()

# -------------------------
# Secrets / Keys
# -------------------------
def get_key(name: str):
    v = os.getenv(name)
    if v:
        return v
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return None

# -------------------------
# CSS Styling (polished theme)
# -------------------------
def load_css():
    st.markdown("""<style>
    :root {
      --bg1: #FFA559;
      --bg2: #7EC8E3;
      --bg3: #B980F0;
      --ink: #2f1b0e;
      --shadow: rgba(0,0,0,0.12);
      --accent: #FF6F31;
      --cream: #FFF6EA;
    }
    body, .stApp {
        background: linear-gradient(135deg, var(--bg1) 0%, var(--bg2) 50%, var(--bg3) 100%);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: var(--ink);
    }
    .app-shell {
        max-width: 860px;
        margin: 20px auto 80px auto;
        background: rgba(255,255,255,0.92);
        border: 1px solid rgba(0,0,0,0.05);
        border-radius: 18px;
        box-shadow: 0 10px 30px var(--shadow);
        padding: 18px 18px 12px 18px;
    }
    .header-row {display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom: 8px;}
    .brand {display:flex; align-items:center; gap:10px;}
    .brand .title {font-weight: 800; font-size: 22px;}
    .badge {display:inline-block;padding:6px 10px;border-radius:999px;background:#fff3d6;
            border:1px solid #ffc36a;font-size:12px;color:#6a3b00}
    .messages {max-height: 560px; overflow-y: auto; padding: 14px;
               background: rgba(255, 255, 255, 0.9); border-radius: 14px;
               box-shadow: 0 5px 16px var(--shadow);
               border: 1.5px solid rgba(255, 111, 49, 0.35); margin-top: 8px;}
    .message.user {background: #FF9E3B; padding: 12px 16px;
                   border-radius: 16px 16px 0 16px; margin: 8px 0 8px auto;
                   max-width: 75%; color: #3a1a00; font-weight: 600; font-size: 15px;
                   box-shadow: 2px 2px 8px rgba(255, 110, 30, 0.5);}
    .message.bot {background: #FFD78A; padding: 12px 16px;
                  border-radius: 16px 16px 16px 0; margin: 8px 0 8px 0;
                  max-width: 75%; color: #2f1b0e; font-weight: 600; font-size: 15px;
                  box-shadow: 2px 2px 8px rgba(255, 150, 50, 0.5);}
    .timestamp {font-size: 11px; color: #6a542f; margin-top: 6px;
                text-align: right; user-select: none; opacity: 0.8;}
    div[data-baseweb="input"] > input {
        background-color: #FFEDD1 !important; color: #2f1b0e !important;
        border-radius: 10px !important; font-weight: 600;
    }
    </style>""", unsafe_allow_html=True)

def render_message(text, role, timestamp, idx):
    cls = "user" if role == "user" else "bot"
    return f'''
    <div class="message {cls}" id="msg-{idx}">
        {text}
        <div class="timestamp">{timestamp}</div>
    </div>
    '''

# -------------------------
# Personality wrapper
# -------------------------
def teddy_filter(user_message: str, raw_answer: str) -> str:
    sales_tail = ""
    if any(k in user_message.lower() for k in ["gift", "present", "birthday", "anniversary"]):
        sales_tail = " If this is a gift, I can suggest sizes or add a sweet note. 🎁"
    elif any(k in user_message.lower() for k in ["price", "how much", "cost", "buy"]):
        sales_tail = " I can also compare sizes to help you get the best value."
    elif any(k in user_message.lower() for k in ["custom", "personalize", "embroidery"]):
        sales_tail = " Tell me your idea—I’ll check feasibility, timeline, and a fair quote."
    return f"{raw_answer}{sales_tail}"

@st.cache_resource(show_spinner=False)
def get_engine(api_key, model_name, temperature):
    return HybridEngine(api_key=api_key, model_name=model_name, temperature=temperature)

# -------------------------
# Main
# -------------------------
def main():
    load_css()
    st.markdown('<div class="app-shell">', unsafe_allow_html=True)

    # --- Header
    st.markdown(
        '<div class="header-row"><div class="brand">'
        '<div class="title">🧸 Ted Pro — Your Cuddleheroes Plush Buddy</div>'
        '<span class="badge">v4.1</span>'
        '</div></div>', unsafe_allow_html=True
    )
    st.caption("Smart FAQ + fuzzy matching + GPT fallback • Private & deployment-ready")

    # --- Keys & engine
    api_key = get_key("OPENROUTER_API_KEY")
    if not api_key:
        st.error("Missing API key. Set OPENROUTER_API_KEY via env or Streamlit Secrets.")
        st.markdown("</div>",
