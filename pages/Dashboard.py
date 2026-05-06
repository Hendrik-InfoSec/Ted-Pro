import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import datetime, timedelta
import os

# --- AUTH CHECK ---
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "tedpro2024")

if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False

if not st.session_state.admin_authenticated:
    st.markdown("# 🔐 Admin Access")
    
    # Use a counter to generate a new key on failed attempts (clears the input)
    if "admin_pw_counter" not in st.session_state:
        st.session_state.admin_pw_counter = 0
    
    def try_login():
        st.session_state.login_attempted = True
    
    password = st.text_input(
        "Enter admin password (press Enter)",
        type="password",
        key=f"admin_pw_{st.session_state.admin_pw_counter}",
        on_change=try_login
    )
    
    if st.session_state.get("login_attempted"):
        if password == ADMIN_PASSWORD:
            st.session_state.admin_authenticated = True
            del st.session_state.login_attempted
            st.rerun()
        else:
            st.error("Incorrect password")
            del st.session_state.login_attempted
            # Increment counter to force a new widget key (clears the field)
            st.session_state.admin_pw_counter += 1
            st.rerun()
    
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
    .upload-area {
        background: white;
        border: 2px dashed #FF922B;
        border-radius: 16px;
        padding: 40px;
        text-align: center;
        margin: 20px 0;
    }
   
div[data-testid="stFormSubmitButton"] ~ div {display: none !important;}

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
    products_count = len(supabase.table('products').select('id', count='exact').execute().data)

    # Today's leads
    today = datetime.now().date().isoformat()
    today_leads = len(supabase.table('leads').select('id').gte('timestamp', today).execute().data)

    col1, col2, col3, col4, col5 = st.columns(5)
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
    with col5:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{products_count}</div>
                <div class="metric-label">Products</div>
            </div>
        """, unsafe_allow_html=True)

except Exception as e:
    st.error(f"Error loading metrics: {e}")

st.markdown("---")

# --- TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["📝 Leads", "💬 Conversations", "📦 Products", "📈 Analytics"])

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
    st.markdown("### 📦 Product Catalog")

    # CSV Upload Section
    with st.container():
        st.markdown("""
            <div class="upload-area">
                <h3>📤 Upload Product Catalog</h3>
                <p>Upload a CSV file with your products. Required columns: name, price</p>
                <p>Optional: category, description, material, size_cm, in_stock, customisable, sku</p>
            </div>
        """, unsafe_allow_html=True)

        uploaded_file = st.file_uploader("Choose CSV file", type=['csv'], key="product_csv")

        if uploaded_file is not None:
            try:
                df = pd.read_csv(uploaded_file)
                st.success(f"✅ Loaded {len(df)} products from CSV")
                st.write("Preview:")
                st.dataframe(df.head(), use_container_width=True)

                if st.button("💾 Save to Database", type="primary"):
                    with st.spinner("Saving products..."):
                        # Clear existing products for this client
                        supabase.table('products').delete().eq('client_id', 'tedpro_client').execute()

                        # Insert new products
                        products = []
                        for _, row in df.iterrows():
                            product = {
                                'client_id': 'tedpro_client',
                                'name': str(row.get('name', '')),
                                'category': str(row.get('category', '')),
                                'price': float(row.get('price', 0)) if pd.notna(row.get('price')) else 0,
                                'currency': str(row.get('currency', 'ZAR')),
                                'in_stock': bool(row.get('in_stock', True)),
                                'description': str(row.get('description', '')),
                                'material': str(row.get('material', '')),
                                'size_cm': int(row.get('size_cm', 0)) if pd.notna(row.get('size_cm')) else 0,
                                'customisable': bool(row.get('customisable', False)),
                                'sku': str(row.get('sku', '')),
                            }
                            products.append(product)

                        # Batch insert
                        supabase.table('products').insert(products).execute()
                        st.success(f"✅ {len(products)} products saved!")
                        st.rerun()

            except Exception as e:
                st.error(f"Error processing CSV: {e}")

    # Show current products
    st.markdown("---")
    st.markdown("### Current Products")
    try:
        products = supabase.table('products').select('*').order('name').execute()
        if products.data:
            df = pd.DataFrame(products.data)
            df = df[['name', 'category', 'price', 'currency', 'in_stock', 'sku']]
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Download current catalog
            csv = df.to_csv(index=False)
            st.download_button("📥 Download Current Catalog", csv, "products.csv", "text/csv")
        else:
            st.info("No products in catalog yet. Upload a CSV above.")
    except Exception as e:
        st.error(f"Error loading products: {e}")

with tab4:
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
