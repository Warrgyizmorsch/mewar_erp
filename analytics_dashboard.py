import streamlit as st
import json
import pandas as pd
from collections import Counter

st.set_page_config(page_title="Mewar AI Analytics", layout="wide")

# Custom CSS for "Mewar" look
st.markdown("""
    <style>
    .main { background-color: #f5f5f5; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border-left: 5px solid #f1c40f; }
    </style>
    """, unsafe_allow_html=True)

st.title("🛡️ Mewar AI Brain Monitor")
st.write("Real-time performance of your V11 Hybrid Router")

def load_logs():
    data = []
    try:
        with open("logs.json", "r") as f:
            for line in f:
                data.append(json.loads(line))
    except FileNotFoundError:
        st.info("Bhai abhi koi logs nahi hain. Bot se thodi baatein karo! 🤖")
        return []
    return data

logs = load_logs()

if logs:
    df = pd.DataFrame(logs)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # --- TOP METRICS ---
    total = len(df)
    fails = df[df['is_fail'] == True]
    accuracy = ((total - len(fails)) / total) * 100

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Hits", total)
    m2.metric("Accuracy", f"{accuracy:.1f}%")
    m3.metric("Failed Queries", len(fails))

    # --- CHARTS ---
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🧠 Intent Popularity")
        intent_counts = df['intent'].value_counts()
        st.bar_chart(intent_counts)

    with col2:
        st.subheader("❌ Top 5 'Dard' (Failures)")
        if not fails.empty:
            top_fails = fails['query'].value_counts().head(5)
            st.table(top_fails)
        else:
            st.success("Bhai ek bhi failure nahi hai! 100% Party time! 🥳")

    # --- SEARCHABLE LOGS ---
    st.subheader("🔍 Deep Dive into Logs")
    search = st.text_input("Kisi specific query ya intent ko dhoondhein...")
    if search:
        filtered_df = df[df['query'].str.contains(search, case=False) | df['intent'].str.contains(search, case=False)]
        st.dataframe(filtered_df.sort_values(by='timestamp', ascending=False), use_container_width=True)
    else:
        st.dataframe(df.sort_values(by='timestamp', ascending=False).head(20), use_container_width=True)