import streamlit as st
from datetime import datetime
from hybrid_engine import HybridEngine
import os

# -------------------------
# CSS Styling
# -------------------------
def load_css():
    st.markdown("""
    <style>
    body, .stApp {
        background: linear-gradient(135deg, #FFA559 0%, #7EC8E3 50%, #B980F0 100%);
        font-family: 'Comic Sans MS', cursive, sans-serif;
        color: #42210B;
    }
    .messages {
        max-height: 600px;
        overflow-y: auto;
        padding: 15px;
        background: rgba(255, 255, 255, 0.85);
        border-radius: 20px;
        box-shadow: 0 5px 20px rgba(0,0,0,0.15);
        border: 3px solid #FF6F31;
    }
    .message.user {
        background: #FF9E3B;
        padding: 15px 25px;
        border-radius: 25px 25px 0 25px;
        margin: 8px 0 8px auto;
        max-width: 70%;
        color: #3a1a00;
        font-weight: 700;
        font-size: 16px;
        box-shadow: 2px 2px 8px rgba(255, 110, 30, 0.7);
    }
    .message.bot {
        background: #FFD78A;
        padding: 15px 25px;
        border-radius: 25px 25px 25px 0;
        margin: 8px 0 8px 0;
        max-width: 70%;
        color: #42210B;
        font-weight: 600;
        font-size: 16px;
        box-shadow: 2px 2px 8px rgba(255, 150, 50, 0.6);
    }
    .timestamp {
        font-size: 11px;
        color: #886632;
        margin-top: 5px;
        text-align: right;
        font-style: italic;
        user-select: none;
    }
    /* Orange input box */
    div[data-baseweb="input"] > input {
        background-color: #FF9E3B !important;
        color: #3a1a00 !important;
        border-radius: 10px !important;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

# -------------------------
# Render message
# -------------------------
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
def teddy_filter(user_message, raw_answer, is_first):
    """
    Makes Teddy warm, caring, sales-focused,
    but without repeating 'hello' each time.
    """
    teddy_tone = (
        "You are Teddy, a warm, caring plush bear representing Cuddleheroes. "
        "You answer in a supportive, emotionally comforting tone, "
        "always subtly encouraging the customer to explore or purchase plushies. "
        "Stay on topic: Cuddleheroes plush toys, sales, shipping, returns, "
        "materials, and gift suggestions. "
        "Do not greet with 'Hello' unless it is the first message in the conversation. "
        "If it is not related to plushies, steer the conversation back politely."
    )
    if is_first:
        prefix = "Hi there, friend! 🧸 "
    else:
        prefix = ""
    return f"{prefix}{raw_answer}"

# -------------------------
# Streamlit app
# -------------------------
@st.cache_resource(show_spinner=False)
def get_engine(api_key, model_name, temperature):
    return HybridEngine(api_key, model_name=model_name, temperature=temperature)

def main():
    st.set_page_config(page_title="🧸 Chat with Teddy — Your Cuddleheroes Plush Buddy", layout="centered")
    load_css()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        st.error("Missing API key! Please set OPENROUTER_API_KEY.")
        st.stop()

    with st.sidebar:
        st.header("⚙️ Settings")
        model_choice = st.selectbox(
            "AI Model",
            ["deepseek/deepseek-r1:free", "claude/claude-3", "gpt-4o-mini", "mixtral/mixtral-13b"],
            index=0
        )
        temperature = st.slider("Creativity (Temperature)", 0.1, 1.0, 0.7)
        if st.button("Clear Chat History"):
            st.session_state.history = []
            st.session_state.input_text = ""

    engine = get_engine(api_key, model_choice, temperature)

    if "history" not in st.session_state:
        st.session_state.history = []
    if "input_text" not in st.session_state:
        st.session_state.input_text = ""

    def on_send():
        user_msg = st.session_state.input_text.strip()
        if user_msg:
            st.session_state.history.append(("user", user_msg, datetime.now().strftime("%H:%M")))
            with st.spinner("Teddy is thinking... 🐻"):
                raw_answer = engine.get_answer(user_msg) or "I’m always here to help with our plushies!"
                teddy_answer = teddy_filter(user_msg, raw_answer, len(st.session_state.history) == 1)
            st.session_state.history.append(("bot", teddy_answer, datetime.now().strftime("%H:%M")))
            st.session_state.input_text = ""

    st.title("🧸 Chat with Teddy — Your Cuddleheroes Plush Buddy")
    st.markdown("<div class='messages'>", unsafe_allow_html=True)
    for idx, (role, message, ts) in enumerate(st.session_state.history):
        st.markdown(render_message(message, role, ts, idx), unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.text_input(
        "Type your question here...",
        key="input_text",
        placeholder="Ask me about Cuddleheroes plushies, shipping, or gifts...",
        on_change=on_send,
        label_visibility="collapsed",
    )

if __name__ == "__main__":
    main()