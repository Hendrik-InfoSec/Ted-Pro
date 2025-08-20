import os
from datetime import datetime
import streamlit as st
from hybrid_engine import HybridEngine

# -------------------------
# Helpers
# -------------------------
def load_css():
    st.markdown(
        """
        <style>
        .app-shell {
            background: linear-gradient(135deg, #fff7f0 0%, #ffe4d6 100%);
            padding: 0;
            margin: 0;
            border-radius: 0;
        }
        .header-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }
        .brand { display: flex; align-items: center; gap: 0.5rem; }
        .title { font-size: 1.2rem; font-weight: bold; color: #6b3e26; }
        .badge { background: #ff914d; color: white; padding: 0.1rem 0.5rem; border-radius: 5px; font-size: 0.7rem; }
        .messages { margin-top: 1rem; }
        .msg { margin-bottom: 0.5rem; padding: 0.5rem; border-radius: 8px; }
        .user { background: #ffe8d9; text-align: right; }
        .bot { background: #fff; border: 1px solid #ffd0b0; }
        </style>
        """,
        unsafe_allow_html=True,
    )

def get_key(name: str) -> str | None:
    return os.getenv(name) or st.secrets.get(name)

@st.cache_resource
def get_engine(api_key, model, temp):
    return HybridEngine(api_key=api_key, model=model, temperature=temp)

def teddy_filter(user_msg, raw_answer: str) -> str:
    # Wraps bot replies in a teddy-friendly tone
    teddy_prefix = "🧸 Teddy: "
    return teddy_prefix + raw_answer.strip()

def render_message(message: str, role: str, ts: str, idx: int) -> str:
    css_class = "user" if role == "user" else "bot"
    return f'<div class="msg {css_class}"><span>{message}</span><br><small>{ts}</small></div>'

# -------------------------
# Main
# -------------------------
def main():
    load_css()
    st.markdown('<div class="app-shell">', unsafe_allow_html=True)

    # --- Header (keeps logo + name + version badge)
    st.markdown(
        '<div class="header-row"><div class="brand">'
        '<div class="title">🧸 Ted Pro — Your Cuddleheroes Plush Buddy</div>'
        '<span class="badge">v4.1</span>'
        '</div></div>', unsafe_allow_html=True
    )
    
    # 🚫 REMOVED this line so nothing shows to visitors
    # st.caption("Smart FAQ + fuzzy matching + GPT fallback • Private & deployment-ready")

    # --- Keys & engine
    api_key = get_key("OPENROUTER_API_KEY")
    if not api_key:
        st.error("Missing API key. Set OPENROUTER_API_KEY via env or Streamlit Secrets.")
        st.markdown("</div>", unsafe_allow_html=True)
        st.stop()

    # --- State
    if "history" not in st.session_state:
        st.session_state.history = []
    if "reload_faqs" not in st.session_state:
        st.session_state.reload_faqs = False
    if "show_history" not in st.session_state:
        st.session_state.show_history = True

    engine = get_engine(api_key, "deepseek/deepseek-r1:free", 0.7)
    if st.session_state.reload_faqs:
        st.cache_resource.clear()
        engine = get_engine(api_key, "deepseek/deepseek-r1:free", 0.7)
        st.session_state.reload_faqs = False
        st.success("FAQs reloaded.")

    # --- Chat UI
    if st.session_state.show_history:
        st.markdown("<div class='messages'>", unsafe_allow_html=True)
        for idx, (role, message, ts) in enumerate(st.session_state.history):
            st.markdown(render_message(message, role, ts, idx), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    def on_send():
        user_msg = st.session_state.input_text.strip()
        if not user_msg:
            return
        st.session_state.history.append(("user", user_msg, datetime.now().strftime("%H:%M")))
        engine.add_to_history("user", user_msg)
        with st.spinner("Teddy is thinking... 🐻"):
            raw_answer = engine.answer(user_msg) or "I’m always here to help with our plushies!"
            teddy_answer = teddy_filter(user_msg, raw_answer)
        st.session_state.history.append(("bot", teddy_answer, datetime.now().strftime("%H:%M")))
        engine.add_to_history("assistant", teddy_answer)
        st.session_state.input_text = ""

    # Text input with no extra caption above it
    st.text_input(
        "Type your question here...",
        key="input_text",
        placeholder="Ask about pricing, shipping, customization, gifts, or track an order (e.g., ORDER1234)...",
        on_change=on_send,
        label_visibility="collapsed",
    )

    st.markdown("</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
