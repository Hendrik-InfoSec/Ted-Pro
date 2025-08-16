import os
from datetime import datetime
import streamlit as st
from hybrid_engine import HybridEngine

# -------------------------
# Page config
# -------------------------
st.set_page_config(page_title="🧸 Ted Pro — Cuddleheroes", layout="centered")

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
# CSS Styling (polished)
# -------------------------
def load_css():
    st.markdown("""
    <style>
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
        background: rgba(255,255,255,0.9);
        border: 1px solid rgba(0,0,0,0.05);
        border-radius: 18px;
        box-shadow: 0 10px 30px var(--shadow);
        padding: 18px 18px 12px 18px;
    }
    .header-row {
        display:flex; align-items:center; justify-content:space-between; gap:12px;
        margin-bottom: 8px;
    }
    .brand {
        display:flex; align-items:center; gap:10px;
    }
    .brand .title {
        font-weight: 800; font-size: 22px;
    }
    .badge {
        display:inline-block;padding:6px 10px;border-radius:999px;
        background:#fff3d6;border:1px solid #ffc36a;font-size:12px;color:#6a3b00
    }
    .toolbar {display:flex; gap:8px; align-items:center;}
    .toolbtn {
        background: var(--cream);
        border: 1px solid #f3d5b3;
        padding: 6px 10px;
        border-radius: 10px;
        font-size: 13px;
        cursor: pointer;
        user-select: none;
    }
    .toolbtn:hover { filter: brightness(0.98); }
    .messages {
        max-height: 560px;
        overflow-y: auto;
        padding: 14px;
        background: rgba(255, 255, 255, 0.9);
        border-radius: 14px;
        box-shadow: 0 5px 16px var(--shadow);
        border: 1.5px solid rgba(255, 111, 49, 0.35);
        margin-top: 8px;
    }
    .message.user {
        background: #FF9E3B;
        padding: 12px 16px;
        border-radius: 16px 16px 0 16px;
        margin: 8px 0 8px auto;
        max-width: 75%;
        color: #3a1a00;
        font-weight: 600;
        font-size: 15px;
        box-shadow: 2px 2px 8px rgba(255, 110, 30, 0.5);
    }
    .message.bot {
        background: #FFD78A;
        padding: 12px 16px;
        border-radius: 16px 16px 16px 0;
        margin: 8px 0 8px 0;
        max-width: 75%;
        color: #2f1b0e;
        font-weight: 600;
        font-size: 15px;
        box-shadow: 2px 2px 8px rgba(255, 150, 50, 0.5);
    }
    .timestamp {
        font-size: 11px;
        color: #6a542f;
        margin-top: 6px;
        text-align: right;
        user-select: none;
        opacity: 0.8;
    }
    div[data-baseweb="input"] > input {
        background-color: #FFEDD1 !important;
        color: #2f1b0e !important;
        border-radius: 10px !important;
        font-weight: 600;
    }
    </style>
    """, unsafe_allow_html=True)

def render_message(text, role, timestamp, idx):
    cls = "user" if role == "user" else "bot"
    return f'''
    <div class="message {cls}" id="msg-{idx}">
        {text}
        <div class="timestamp">{timestamp}</div>
    </div>
    '''

# -------------------------
# Personality wrapper (teddy)
# -------------------------
def teddy_filter(user_message: str, raw_answer: str, is_first: bool) -> str:
    # friendly micro-copy, with light sales nudge (without being spammy)
    friendly_prefix = "Hi there, friend! 🧸 " if is_first else ""
    sales_tail = ""
    if any(k in user_message.lower() for k in ["gift", "present", "birthday", "anniversary"]):
        sales_tail = " If this is a gift, I can suggest sizes or add a sweet note. 🎁"
    elif any(k in user_message.lower() for k in ["price", "how much", "cost", "buy"]):
        sales_tail = " I can also compare sizes to help you get the best value."
    elif any(k in user_message.lower() for k in ["custom", "personalize", "embroidery"]):
        sales_tail = " Tell me your idea—I’ll check feasibility, timeline, and a fair quote."
    return f"{friendly_prefix}{raw_answer}{sales_tail}"

@st.cache_resource(show_spinner=False)
def get_engine(api_key, model_name, temperature):
    return HybridEngine(api_key=api_key, model_name=model_name, temperature=temperature)

def main():
    load_css()
    # --- App shell & header ---
    st.markdown('<div class="app-shell">', unsafe_allow_html=True)
    colL, colR = st.columns([0.75, 0.25])
    with colL:
        st.markdown(
            '<div class="header-row"><div class="brand">'
            '<div class="title">🧸 Ted Pro — Your Cuddleheroes Plush Buddy</div>'
            '<span class="badge">v4.1</span>'
            '</div></div>', unsafe_allow_html=True
        )
        st.caption("Smart FAQ + fuzzy matching + GPT fallback • Private & deployment-ready")
    with colR:
        st.markdown('<div class="toolbar">', unsafe_allow_html=True)
        # toolbar buttons rendered later after we have state
        st.markdown('</div>', unsafe_allow_html=True)

    # --- Keys & model ---
    api_key = get_key("OPENROUTER_API_KEY")
    if not api_key:
        st.error("Missing API key. Set OPENROUTER_API_KEY via env or Streamlit Secrets.")
        st.markdown("</div>", unsafe_allow_html=True)  # close .app-shell
        st.stop()

    # Sidebar controls
    with st.sidebar:
        st.header("⚙️ Settings")
        model_choice = st.selectbox(
            "AI Model",
            ["deepseek/deepseek-r1:free", "openai/gpt-4o-mini", "anthropic/claude-3-haiku"],
            index=0
        )
        temperature = st.slider("Creativity (Temperature)", 0.1, 1.2, 0.7, 0.1)
        colA, colB = st.columns(2)
        with colA:
            if st.button("Clear Chat"):
                st.session_state.history = []
        with colB:
            if st.button("Reload FAQs"):
                st.session_state.reload_faqs = True

    # --- State ---
    if "history" not in st.session_state:
        st.session_state.history = []
    if "reload_faqs" not in st.session_state:
        st.session_state.reload_faqs = False
    if "show_history" not in st.session_state:
        st.session_state.show_history = True  # default visible

    # --- Engine ---
    engine = get_engine(api_key, model_choice, temperature)
    if st.session_state.reload_faqs:
        st.cache_resource.clear()
        engine = get_engine(api_key, model_choice, temperature)
        st.session_state.reload_faqs = False
        st.success("FAQs reloaded.")

    # --- Toolbar (top-right) ---
    tcol1, tcol2, tcol3 = st.columns(3)
    with tcol1:
        toggle = st.button(("👁 Hide History" if st.session_state.show_history else "👁 Show History"))
        if toggle:
            st.session_state.show_history = not st.session_state.show_history
    with tcol2:
        st.button("🗑 Clear", on_click=lambda: st.session_state.update({"history": []}))
    with tcol3:
        st.button("🔄 Reload FAQs", on_click=lambda: st.session_state.update({"reload_faqs": True}))

    # --- Chat UI ---
    if st.session_state.show_history:
        st.markdown("<div class='messages'>", unsafe_allow_html=True)
        for idx, (role, message, ts) in enumerate(st.session_state.history):
            st.markdown(render_message(message, role, ts, idx), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    def on_send():
        user_msg = st.session_state.input_text.strip()
        if not user_msg:
            return
        # Save user message
        st.session_state.history.append(("user", user_msg, datetime.now().strftime("%H:%M")))
        engine.add_to_history("user", user_msg)
        # Generate answer
        with st.spinner("Teddy is thinking... 🐻"):
            raw_answer = engine.answer(user_msg) or "I’m always here to help with our plushies!"
            is_first = (len([r for r, _, _ in st.session_state.history if r == "user"]) == 1)
            teddy_answer = teddy_filter(user_msg, raw_answer, is_first=is_first)
        # Save bot answer
        st.session_state.history.append(("bot", teddy_answer, datetime.now().strftime("%H:%M")))
        engine.add_to_history("assistant", teddy_answer)
        st.session_state.input_text = ""

    st.text_input(
        "Type your question here...",
        key="input_text",
        placeholder="Ask about pricing, shipping, customization, gifts, or track an order (e.g., ORDER1234)...",
        on_change=on_send,
        label_visibility="collapsed",
    )

    st.markdown("</div>", unsafe_allow_html=True)  # close .app-shell

if __name__ == "__main__":
    main()

