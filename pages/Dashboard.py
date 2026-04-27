import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import datetime, timedelta
import os

st.set_page_config(
    page_title="TedPro Admin Dashboard 📊",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- AUTH CHECK ---
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "tedpro2024")

if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False

if not st.session_state.admin_authenticated:
    st.markdown("# 🔐 Admin Access")
    password = st.text_input("Enter admin password", type="password")
    if st.button("Login"):
        if password == ADMIN_PASSWORD:
            st.session_state.admin_authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()

# --- SUPABASE CONNECTION ---
@st.cache_resource
def get_supabase():
    sb_url = os.environ.get("SUPABASE_URL")
    sb_key = os.environ.get("SUPABASE_KEY")
    if not sb_url or not sb_key:
        st.error("Supabase credentials not found")
        st.stop()
    return create_client(sb_url, sb_key)

supabase = get_supabase()

# --- STYLING ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Quicksand', sans-serif; }
    .stApp { background: linear-gradient(135deg, #FFF9F4 0%, #FFEDD2 100%); }
    header, footer { visibility: hidden; }
    .metric-card {
        background: white;
        padding: 20px;
        border-radius: 16px;
        box-shadow: 0 4px 16px rgba(45, 27, 0, 0.08);
        border: 1px solid #FFE4CC;
    }
    .metric-value {
        font-size: 32px;
        font-weight: 700;
        color: #FF922B;
    }
    .metric-label {
        font-size: 14px;
        color: #8B6914;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
</style>
""", unsafe_allow_html=True)

# --- HEADER ---
st.markdown("# 📊 TedPro Admin Dashboard")
st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# --- METRICS ---
try:
    leads_count = len(supabase.table('leads').select('id', count='exact').execute().data)
    conv_count = len(supabase.table('conversations').select('id', count='exact').execute().data)
    cache_count = len(supabase.table('qa_cache').select('id', count='exact').execute().data)

    # Today's leads
    today = datetime.now().date().isoformat()
    today_leads = len(supabase.table('leads').select('id').gte('timestamp', today).execute().data)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{leads_count}</div>
                <div class="metric-label">Total Leads</div>
            </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{today_leads}</div>
                <div class="metric-label">Today's Leads</div>
            </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{conv_count}</div>
                <div class="metric-label">Conversations</div>
            </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{cache_count}</div>
                <div class="metric-label">Cached Q&A</div>
            </div>
        """, unsafe_allow_html=True)

except Exception as e:
    st.error(f"Error loading metrics: {e}")

st.markdown("---")

# --- TABS ---
tab1, tab2, tab3 = st.tabs(["📝 Leads", "💬 Conversations", "📈 Analytics"])

with tab1:
    st.markdown("### Recent Leads")
    try:
        leads = supabase.table('leads').select('*').order('timestamp', desc=True).limit(50).execute()
        if leads.data:
            df = pd.DataFrame(leads.data)
            df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d %H:%M')
            df = df[['name', 'email', 'context', 'timestamp', 'consent']]
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Download button
            csv = df.to_csv(index=False)
            st.download_button("📥 Download Leads CSV", csv, "leads.csv", "text/csv")
        else:
            st.info("No leads yet")
    except Exception as e:
        st.error(f"Error loading leads: {e}")

with tab2:
    st.markdown("### Recent Conversations")
    try:
        convs = supabase.table('conversations').select('*').order('created_at', desc=True).limit(50).execute()
        if convs.data:
            df = pd.DataFrame(convs.data)
            df['created_at'] = pd.to_datetime(df['created_at']).dt.strftime('%Y-%m-%d %H:%M')

            # Show expandable conversation cards
            for _, row in df.head(20).iterrows():
                with st.expander(f"🧑 {row['user_message'][:50]}... | {row['created_at']}"):
                    st.markdown(f"**User:** {row['user_message']}")
                    st.markdown(f"**Teddy:** {row['bot_response'][:500]}...")
                    st.caption(f"Session: {row['session_id'][:8]}...")
        else:
            st.info("No conversations yet")
    except Exception as e:
        st.error(f"Error loading conversations: {e}")

with tab3:
    st.markdown("### Popular Questions")
    try:
        cache = supabase.table('qa_cache').select('*').order('hit_count', desc=True).limit(20).execute()
        if cache.data:
            df = pd.DataFrame(cache.data)
            df = df[['question_normalized', 'hit_count', 'created_at']]
            df['created_at'] = pd.to_datetime(df['created_at']).dt.strftime('%Y-%m-%d')
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No cached questions yet")
    except Exception as e:
        st.error(f"Error loading analytics: {e}")

# --- FOOTER ---
st.markdown("---")
if st.button("🚪 Logout"):
    st.session_state.admin_authenticated = False
    st.rerun()
