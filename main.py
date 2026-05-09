import streamlit as st
from hybrid_engine import HybridEngine
from datetime import datetime, timedelta
import uuid
import time
import os
import logging
import smtplib

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# ---------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------

st.set_page_config(
    page_title="TedPro Marketing Assistant 🧸",
    page_icon="🧸",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------------------------------------------------
# TIMEZONE
# ---------------------------------------------------

LOCAL_OFFSET_HOURS = 2


def get_teddy_time():
    utc_now = datetime.now()
    local_now = utc_now + timedelta(hours=LOCAL_OFFSET_HOURS)
    return local_now.strftime("%H:%M")


# ---------------------------------------------------
# UI / CSS
# ---------------------------------------------------

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Quicksand', sans-serif;
    }

    .stApp {
        background: linear-gradient(135deg, #FFF9F4 0%, #FFEDD2 100%);
    }

    header {
        visibility: hidden;
    }

    footer {
        visibility: hidden;
    }

    .stDeployButton {
        display: none;
    }

    .main-container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 0 20px;
    }

    .chat-wrapper {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 20px 0;
    }

    .message-row {
        display: flex;
        width: 100%;
        animation: fadeIn 0.3s ease-in;
    }

    @keyframes fadeIn {
        from {
            opacity: 0;
            transform: translateY(10px);
        }

        to {
            opacity: 1;
            transform: translateY(0);
        }
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
    }

    .bot-bubble .message-meta {
        color: #8B6914;
    }

    .user-bubble .message-meta {
        color: rgba(255,255,255,0.8);
    }

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
    }

    .typing-indicator {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 16px 20px;
        background: white;
        border-radius: 20px;
        border-bottom-left-radius: 4px;
        border: 1px solid #FFE4CC;
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

    .typing-dot:nth-child(1) {
        animation-delay: 0s;
    }

    .typing-dot:nth-child(2) {
        animation-delay: 0.2s;
    }

    .typing-dot:nth-child(3) {
        animation-delay: 0.4s;
    }

    @keyframes typingBounce {
        0%, 80%, 100% {
            transform: translateY(0);
        }

        40% {
            transform: translateY(-10px);
        }
    }

    .typing-text {
        font-size: 14px;
        color: #8B6914;
        margin-left: 8px;
        font-style: italic;
    }

    .quick-questions {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        justify-content: center;
        margin: 20px 0;
    }

    .lead-banner {
        background: linear-gradient(135deg, #FF922B 0%, #FF8C42 100%);
        color: white;
        padding: 20px;
        border-radius: 16px;
        margin: 20px 0;
        text-align: center;
    }

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
        0%, 100% {
            transform: translateY(0);
        }

        50% {
            transform: translateY(-10px);
        }
    }

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

# ---------------------------------------------------
# BACKEND INITIALIZATION
# ---------------------------------------------------

@st.cache_resource
def init_engine():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    sb_url = os.environ.get("SUPABASE_URL")
    sb_key = os.environ.get("SUPABASE_KEY")

    if not all([api_key, sb_url, sb_key]):
        st.error("Missing environment variables.")
        st.stop()

    return HybridEngine(
        api_key=api_key,
        supabase_url=sb_url,
        supabase_key=sb_key,
        client_id="tedpro_client"
    )


try:
    engine = init_engine()

except Exception as e:
    st.error(f"Failed to initialize engine: {e}")
    st.stop()

# ---------------------------------------------------
# SESSION STATE
# ---------------------------------------------------

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "lead_captured" not in st.session_state:
    st.session_state.lead_captured = False

if "typing" not in st.session_state:
    st.session_state.typing = False

# ---------------------------------------------------
# TEDDY PERSONALITY
# ---------------------------------------------------

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

# ---------------------------------------------------
# EMAIL SENDING
# ---------------------------------------------------

def send_welcome_email(name: str, email: str) -> bool:

    try:
        gmail_user = os.environ.get("GMAIL_USER")
        gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

        if not gmail_user or not gmail_password:
            logging.error("Missing Gmail credentials")
            return False

        greeting_name = name if name else "Friend"

        msg = MIMEMultipart('alternative')
        msg['Subject'] = "Welcome to the CuddleHeros VIP Club 🧸"
        msg['From'] = gmail_user
        msg['To'] = email

        html_content = f"""
        <html>
        <body style="font-family:sans-serif;background:#FFF9F4;padding:20px;">
            <div style="background:white;padding:30px;border-radius:20px;">
                <h1>Welcome {greeting_name}! 🧸</h1>

                <p>Thanks for joining the Honey-Pot!</p>

                <div style="
                    background:#FFE4CC;
                    padding:20px;
                    border-radius:12px;
                    text-align:center;
                    margin:20px 0;
                ">
                    <h2>TEDDY10</h2>
                    <p>10% OFF your first order</p>
                </div>

                <p>Paws and hugs,<br>Teddy 🧸</p>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_content, 'html'))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(
                gmail_user,
                email,
                msg.as_string()
            )

        logging.info(f"Welcome email sent to {email}")
        return True

    except Exception as e:
        logging.error(f"Email send failed: {e}")
        return False

# ---------------------------------------------------
# LEAD CAPTURE
# ---------------------------------------------------

def render_lead_capture():

    if not st.session_state.lead_captured:

        st.markdown("""
        <div class="lead-banner">
            <h3>🍯 Join the Honey-Pot</h3>
            <p>Get our secret catalog and 10% off your first order!</p>
        </div>
        """, unsafe_allow_html=True)

        col1, col2, col3 = st.columns([2, 2, 1])

        with col1:
            l_name = st.text_input(
                "Name",
                placeholder="Your name",
                label_visibility="collapsed"
            )

        with col2:
            l_email = st.text_input(
                "Email",
                placeholder="hello@friend.com",
                label_visibility="collapsed"
            )

        with col3:
            submit = st.button(
                "Get 10% Off 🎁",
                use_container_width=True,
                type="primary"
            )

        if submit and l_email and "@" in l_email:

            with st.spinner("Saving your info..."):

                try:
                    result = engine.add_lead(
                        l_name,
                        l_email,
                        context="main_chat_v4"
                    )

                    if result:

                        st.session_state.lead_captured = True

                        email_sent = send_welcome_email(
                            l_name,
                            l_email
                        )

                        if email_sent:
                            st.success(
                                "✅ Welcome to the VIP Cuddlers club!"
                            )
                        else:
                            st.warning(
                                "Lead saved but email could not be sent."
                            )

                    else:
                        st.error(
                            "Email may already exist."
                        )

                except Exception as e:
                    st.error(f"Error: {e}")

        elif submit:
            st.warning("Please enter a valid email address.")

# ---------------------------------------------------
# MAIN CONTAINER
# ---------------------------------------------------

st.markdown("<div class='main-container'>", unsafe_allow_html=True)

# ---------------------------------------------------
# HEADER
# ---------------------------------------------------

st.markdown("""
<div style="text-align:center;padding:20px 0;">
    <h1 style="color:#2D1B00;">
        TedPro Assistant
    </h1>

    <p style="color:#8B6914;">
        Your friendly plushie expert 🧸
    </p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------
# QUICK QUESTIONS
# ---------------------------------------------------

quick_qs = [
    ("Pricing 💰", "What are your prices?"),
    ("Shipping 📦", "How does shipping work?"),
    ("Custom Work 🎨", "Can I order custom plushies?"),
    ("Safety ✅", "Are your plushies safe for kids?")
]

q_cols = st.columns(4)

for i, (label, query) in enumerate(quick_qs):

    if q_cols[i].button(
        label,
        use_container_width=True,
        key=f"qq_{i}"
    ):

        st.session_state.chat_history.append({
            "role": "user",
            "content": query,
            "time": get_teddy_time()
        })

        st.session_state.typing = True
        st.rerun()

# ---------------------------------------------------
# CHAT AREA
# ---------------------------------------------------

chat_container = st.container()

with chat_container:

    if not st.session_state.chat_history:

        st.markdown("""
        <div class="welcome-container">
            <div class="teddy-welcome">🧸</div>

            <h1>Hi! I'm Teddy</h1>

            <p>
                Ask me anything about CuddleHeros plushies!
            </p>
        </div>
        """, unsafe_allow_html=True)

    else:

        st.markdown("<div class='chat-wrapper'>", unsafe_allow_html=True)

        for msg in st.session_state.chat_history:

            is_user = msg["role"] == "user"

            row_class = "user-row" if is_user else "bot-row"
            bubble_class = "user-bubble" if is_user else "bot-bubble"
            avatar_class = "user-avatar" if is_user else "bot-avatar"
            avatar_emoji = "👤" if is_user else "🧸"

            st.markdown(f"""
            <div class="message-row {row_class}">
                <div class="avatar {avatar_class}">
                    {avatar_emoji}
                </div>

                <div class="message-bubble {bubble_class}">
                    {msg['content']}
                    <div class="message-meta">
                        {msg['time']}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        if st.session_state.typing:

            st.markdown("""
            <div class="message-row bot-row">
                <div class="avatar bot-avatar">🧸</div>

                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>

                    <span class="typing-text">
                        Teddy is thinking...
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------
# LEAD CAPTURE
# ---------------------------------------------------

if (
    len(st.session_state.chat_history) >= 2
    and not st.session_state.lead_captured
):
    st.markdown("---")
    render_lead_capture()

st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------
# CLEAR CHAT BUTTON
# ---------------------------------------------------

col1, col2 = st.columns([1, 5])

with col1:
    if st.button("🗑️ Clear Chat"):
        st.session_state.chat_history = []
        st.rerun()

# ---------------------------------------------------
# CHAT INPUT
# ---------------------------------------------------

if prompt := st.chat_input(
    "Ask me anything about CuddleHeros..."
):

    st.session_state.chat_history.append({
        "role": "user",
        "content": prompt,
        "time": get_teddy_time()
    })

    st.session_state.typing = True
    st.rerun()

# ---------------------------------------------------
# BOT RESPONSE
# ---------------------------------------------------

if (
    st.session_state.typing
    and st.session_state.chat_history
):

    last_msg = st.session_state.chat_history[-1]

    if last_msg["role"] == "user":

        time.sleep(0.5)

        try:
            user_query = last_msg["content"]

            product_keywords = [
                'have',
                'stock',
                'buy',
                'price',
                'cost',
                'plushie',
                'teddy',
                'bear',
                'unicorn',
                'dinosaur',
                'bunny',
                'custom',
                'order',
                'catalog',
                'shop',
                'available'
            ]

            is_product_query = any(
                kw in user_query.lower()
                for kw in product_keywords
            )

            product_context = ""

            if is_product_query:

                products = engine.search_products(
                    user_query,
                    max_results=5
                )

                if products:

                    product_context = (
                        "\n\n[PRODUCT INFO]\n"
                        + engine.format_product_response(products)
                    )

            enhanced_query = user_query

            if product_context:
                enhanced_query += "\n\n" + product_context

            raw_response = "".join([
                chunk
                for chunk in engine.stream_answer(
                    enhanced_query
                )
            ])

            final_response = apply_teddy_vibes(raw_response)

            st.session_state.chat_history.append({
                "role": "assistant",
                "content": final_response,
                "time": get_teddy_time()
            })

        except Exception as e:

            logging.error(f"Chat error: {e}")

            st.session_state.chat_history.append({
                "role": "assistant",
                "content": (
                    "I'm having trouble connecting right now. "
                    "Please try again! 🧸"
                ),
                "time": get_teddy_time()
            })

        st.session_state.typing = False
        st.rerun()
