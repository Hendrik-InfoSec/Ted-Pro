import streamlit as st
from supabase import create_client, Client
import os
import requests

st.set_page_config(
    page_title="TedPro Dev Tools 🔧",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- AUTH CHECK ---
DEV_PASSWORD = os.environ.get("DEV_PASSWORD", "tedprodev2024")

if "dev_authenticated" not in st.session_state:
    st.session_state.dev_authenticated = False

if not st.session_state.dev_authenticated:
    st.markdown("# 🔐 Developer Access")
    password = st.text_input("Enter dev password", type="password")
    if st.button("Login"):
        if password == DEV_PASSWORD:
            st.session_state.dev_authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()

# --- STYLING ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Quicksand', sans-serif; }
    .stApp { background: linear-gradient(135deg, #FFF9F4 0%, #FFEDD2 100%); }
    header, footer { visibility: hidden; }
    .status-ok { color: #4CAF50; font-weight: 600; }
    .status-fail { color: #f44336; font-weight: 600; }
    .status-warn { color: #FF9800; font-weight: 600; }
    .dev-card {
        background: white;
        padding: 20px;
        border-radius: 16px;
        box-shadow: 0 4px 16px rgba(45, 27, 0, 0.08);
        border: 1px solid #FFE4CC;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("# 🔧 TedPro Developer Tools")

# --- ENVIRONMENT CHECKS ---
st.markdown("### 🔑 Environment Variables")
with st.container():
    env_vars = {
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", "NOT SET"),
        "SUPABASE_URL": os.environ.get("SUPABASE_URL", "NOT SET"),
        "SUPABASE_KEY": os.environ.get("SUPABASE_KEY", "NOT SET")[:20] + "..." if os.environ.get("SUPABASE_KEY") else "NOT SET",
        "GMAIL_USER": os.environ.get("GMAIL_USER", "NOT SET"),
        "GMAIL_APP_PASSWORD": "SET ✓" if os.environ.get("GMAIL_APP_PASSWORD") else "NOT SET",
        "RESEND_API_KEY": "SET ✓" if os.environ.get("RESEND_API_KEY") else "NOT SET",
    }

    for key, value in env_vars.items():
        status = "✅" if value not in ["NOT SET", "None"] else "❌"
        st.write(f"{status} **{key}**: {value}")

# --- SUPABASE CONNECTION TEST ---
st.markdown("### 🗄️ Database Connection")
with st.container():
    try:
        sb_url = os.environ.get("SUPABASE_URL")
        sb_key = os.environ.get("SUPABASE_KEY")

        if sb_url and sb_key:
            supabase = create_client(sb_url, sb_key)

            # Test tables
            tables = ['leads', 'conversations', 'qa_cache']
            for table in tables:
                try:
                    result = supabase.table(table).select('count').limit(1).execute()
                    st.markdown(f'<span class="status-ok">✅ {table}: OK</span>', unsafe_allow_html=True)
                except Exception as e:
                    st.markdown(f'<span class="status-fail">❌ {table}: {str(e)[:100]}</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="status-fail">❌ Supabase credentials missing</span>', unsafe_allow_html=True)
    except Exception as e:
        st.markdown(f'<span class="status-fail">❌ Connection failed: {str(e)[:100]}</span>', unsafe_allow_html=True)

# --- API HEALTH CHECKS ---
st.markdown("### 🌐 External API Status")
with st.container():
    col1, col2 = st.columns(2)

    with col1:
        st.write("**OpenRouter API**")
        try:
            response = requests.get("https://openrouter.ai/api/v1/models", timeout=10)
            if response.status_code == 200:
                st.markdown('<span class="status-ok">✅ Online</span>', unsafe_allow_html=True)
            else:
                st.markdown(f'<span class="status-warn">⚠️ Status {response.status_code}</span>', unsafe_allow_html=True)
        except Exception as e:
            st.markdown(f'<span class="status-fail">❌ {str(e)[:80]}</span>', unsafe_allow_html=True)

    with col2:
        st.write("**Gmail SMTP**")
        try:
            import smtplib
            server = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=5)
            server.quit()
            st.markdown('<span class="status-ok">✅ Reachable</span>', unsafe_allow_html=True)
        except Exception as e:
            st.markdown(f'<span class="status-warn">⚠️ {str(e)[:80]}</span>', unsafe_allow_html=True)

# --- SESSION STATE DEBUG ---
st.markdown("### 🧪 Session State")
with st.expander("View current session state"):
    for key, value in st.session_state.items():
        if key != "admin_authenticated" and key != "dev_authenticated":
            st.write(f"**{key}**: {value}")

# --- QUICK ACTIONS ---
st.markdown("### ⚡ Quick Actions")
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("🗑️ Clear Cache", use_container_width=True):
        try:
            sb_url = os.environ.get("SUPABASE_URL")
            sb_key = os.environ.get("SUPABASE_KEY")
            if sb_url and sb_key:
                supabase = create_client(sb_url, sb_key)
                supabase.table('qa_cache').delete().neq('id', '0').execute()
                st.success("Cache cleared!")
        except Exception as e:
            st.error(f"Error: {e}")

with col2:
    if st.button("📧 Test Email", use_container_width=True):
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            gmail_user = os.environ.get("GMAIL_USER")
            gmail_pass = os.environ.get("GMAIL_APP_PASSWORD")

            if gmail_user and gmail_pass:
                msg = MIMEMultipart()
                msg['From'] = gmail_user
                msg['To'] = gmail_user
                msg['Subject'] = "TedPro Test Email 🧸"
                msg.attach(MIMEText("<h1>Test from TedPro Dev Tools</h1><p>If you see this, email is working!</p>", 'html'))

                with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                    server.login(gmail_user, gmail_pass)
                    server.sendmail(gmail_user, gmail_user, msg.as_string())
                st.success("Test email sent!")
            else:
                st.error("Gmail credentials not set")
        except Exception as e:
            st.error(f"Email failed: {e}")

with col3:
    if st.button("🔄 Refresh App", use_container_width=True):
        st.rerun()

# --- FOOTER ---
st.markdown("---")
if st.button("🚪 Logout"):
    st.session_state.dev_authenticated = False
    st.rerun()
