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
# CSS Styling
# -------------------------
def load_css():
    st.markdown("""
    <style>
    body, .stApp {
        background: linear-gradient(135deg, #FFA559 0%, #7EC8E3 50%, #B980F0 100%);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: #2f1b0e;
    }
    .messages {
        max-height: 600px;
        overflow-y: auto;
        padding: 15px;
        background: rgba(255, 255, 255, 0.9);
        border-radius: 16px;
        box-shadow: 0 5px 20px rgba(0,0,0,0.12);
        border: 2px solid rgba(255, 111, 49, 0.5);
    }
    .message.user {
        background: #FF9E3B;
        padding: 12px 18px;
        border-radius: 18px 18px 0 18px;
        margin: 8px 0 8px auto;
        max-width: 75%;
        color: #3a1a00;
        font-weight: 600;
        font-size: 15px;
        box-shadow: 2px 2px 8px rgba(255, 110, 30, 0.5);
    }
    .message.bot {
        background: #FFD78A;
        padding: 12px 18px;
        border-radius: 18px 18px 18px 0;
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
    .badge {
        display:inline-block;padding:6px 10px;border-radius:999px;
        background:#fff3d6;border:1px solid #ffc36a;font-size:12px;color:#6a3b00
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

def teddy_filter(user_message, raw_answer, is_first):
    prefix = "Hi there, friend! 🧸 " if is_first else ""
    return f"{prefix}{raw_answer}"

@st.cache_resource(show_spinner=False)
def get_engine(api_key, model_name, temperature):
    return HybridEngine(api_key=api_key, model_name=model_name, temperature=temperature)

def main():
    load_css()
    st.title("🧸 Ted Pro — Your Cuddleheroes Plush Buddy")
    st.caption("Smart FAQ + fuzzy matching + GPT fallback • Private & deployment-ready")
    st.markdown('<span class="badge">v2025.08</span>', unsafe_allow_html=True)

    # --- Keys & model ---
    api_key = get_key("OPENROUTER_API_KEY")
    if not api_key:
        st.error("Missing API key. Set OPENROUTER_API_KEY via env or Streamlit Secrets.")
        st.stop()

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

    # --- Session state ---
    if "history" not in st.session_state:
        st.session_state.history = []
    if "reload_faqs" not in st.session_state:
        st.session_state.reload_faqs = False

    engine = get_engine(api_key, model_choice, temperature)
    if st.session_state.reload_faqs:
        # Rebuild engine to reload faqs.json/client_faq.json
        st.cache_resource.clear()
        engine = get_engine(api_key, model_choice, temperature)
        st.session_state.reload_faqs = False
        st.success("FAQs reloaded.")

    # --- Chat UI ---
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
            teddy_answer = teddy_filter(user_msg, raw_answer, is_first=(len(st.session_state.history) <= 2))
        # Save bot answer
        st.session_state.history.append(("bot", teddy_answer, datetime.now().strftime("%H:%M")))
        engine.add_to_history("assistant", teddy_answer)
        st.session_state.input_text = ""

    st.text_input(
        "Type your question here...",
        key="input_text",
        placeholder="Ask about pricing, shipping, customization, gifts...",
        on_change=on_send,
        label_visibility="collapsed",
    )

if __name__ == "__main__":
    main()
