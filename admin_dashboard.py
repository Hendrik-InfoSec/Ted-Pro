import streamlit as st
from pathlib import Path
import json
from main import TedPro
from utilities.track_queries import analyze_usage
from utilities.update_faqs import update_faqs
from utilities.email_alerts import notifier

st.set_page_config(layout="wide")
client_id = st.sidebar.selectbox(
    "Select Client",
    [f.name for f in Path("clients").iterdir() if f.is_dir()]
)
bot = TedPro(client_id)

st.title(f"TedPro Admin - {client_id}")
tab1, tab2, tab3 = st.tabs(["Chat", "Knowledge", "Analytics"])

with tab1:
    if user_input := st.chat_input("Type a message..."):
        response = bot.respond(user_input)
        st.write(f"**User:** {user_input}")
        st.write(f"**TedPro:** {response}")

with tab2:
    st.subheader("FAQ Knowledge Base")
    with open(f"clients/{client_id}/knowledge/faq.json") as f:
        st.json(json.load(f))
    new_q, new_a = st.text_input("New Question"), st.text_input("Answer")
    if st.button("Add FAQ"):
        update_faqs(client_id, {new_q: new_a})
        st.rerun()

with tab3:
    analyze_usage(client_id, 30)
    with open(f"clients/{client_id}/usage_report.json") as f:
        st.bar_chart(json.load(f)["query_breakdown"])
    if st.button("⚠️ Test Alert"):
        notifier.send_alert(client_id, "TEST: System check")
        st.success("Alert sent!")