import streamlit as st

st.write("Hello Streamlit")
if st.button("Rerun"):
    st.experimental_rerun()
