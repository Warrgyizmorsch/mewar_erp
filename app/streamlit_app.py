import streamlit as st
import requests
import pandas as pd

# ==========================================
# 🚀 STRICTLY LOCALHOST CONFIGURATION
# ==========================================
API_BASE = "https://mewar-erp.vercel.app"
CHAT_URL = f"{API_BASE}/chatbot/"
LOGIN_URL = f"{API_BASE}/auth/login"

st.set_page_config(page_title="Mewar ERP AI", page_icon="🧠", layout="centered")

# --- SESSION STATE INITIALIZATION ---
if "token" not in st.session_state: st.session_state.token = None
if "messages" not in st.session_state: st.session_state.messages = []
if "next_query" not in st.session_state: st.session_state.next_query = None

def set_next_query(query_text):
    st.session_state.next_query = query_text

# ==========================================
# CENTRALIZED UI RENDERER
# ==========================================
def render_bot_response(data, msg_idx):
    if "error" in data:
        st.error(f"🔌 {data['error']}")
        return
    if "detail" in data:
        st.error(f"🔴 Access Error: {data['detail']}")
        return

    results_list = data.get("results", [data])

    for res in results_list:
        res_type = res.get("type")

        # 🟢 CASE 1: EXACT STOCK MATCH
        if res_type == "result" and "inventory" in res:
            inv = res["inventory"]
            st.success(f"📦 **{inv['name']}**")
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Stock", res.get("total_stock", 0))
            c2.metric("Finish", res.get("finish_stock", 0))
            c3.metric("Semi-Finish", res.get("semi_finish_stock", 0))
            c4.metric("Machining", res.get("machining_stock", 0))
            
            st.caption(f"Item ID: #{inv['id']} | Category: {inv.get('classification', 'N/A')}")
        
        # 🔵 CASE 2: SUPPLIER MATCH 
        elif res_type == "result" and "supplier" in res:
            sup = res["supplier"]
            st.info(f"🏭 **{sup['name']}**")
            
            email = sup.get('email') if sup.get('email') else 'N/A'
            gstin = sup.get('gstin') if sup.get('gstin') else 'N/A'
            st.markdown(f"**Email:** {email}  \n**GSTIN:** {gstin}")
            
            items = res.get("items", [])
            if items:
                st.write("---")
                st.write("**📦 Inventory from this Supplier:**")
                for item in items:
                    st.write(f"- {item.get('name')}: **{item.get('stock')}** in stock")
            
        # 🟡 CASE 3: DROPDOWN MENU
        elif res_type == "dropdown":
            st.warning(res.get("message", "Select an item:"))
            cols = st.columns(2)
            for i, item in enumerate(res.get("items", [])):
                cols[i % 2].button(
                    f"🔎 {item['name']}", 
                    key=f"btn_{item['id']}_{msg_idx}_{i}", 
                    on_click=set_next_query, 
                    args=(item['name'],)
                )
                
        # 🟡 CASE 4: SUPPLIER LIST MENU
        elif res_type == "supplier_list":
            st.warning(res.get("message", "Select a supplier:"))
            for i, s in enumerate(res.get("suppliers", [])):
                st.button(
                    f"🏭 {s['name']}", 
                    key=f"sup_{s['id']}_{msg_idx}_{i}", 
                    on_click=set_next_query, 
                    args=(s['name'],)
                )

        # 📊 CASE 5: MANAGER ANALYTICS CHARTS (NEW)
        elif res_type == "analytics_chart":
            st.subheader(res.get("title", "📊 Analytics Report"))
            
            df = pd.DataFrame(res.get("data", []))
            
            if not df.empty:
                # Show an interactive table
                st.dataframe(df, use_container_width=True, hide_index=True)
                
                # Draw the Bar Chart
                if res.get("chart_type") == "bar":
                    st.write("---")
                    st.bar_chart(df.set_index("Name")["Stock"])
            else:
                st.info("No data available for this report.")
        
        # 💬 CASE 6: Simple Text (Chat/Errors)
        elif "message" in res and not res_type:
            st.write(res["message"])
        elif res_type == "chat":
            st.write(res["message"])

# ==========================================
# PAGE 1: LOGIN SYSTEM
# ==========================================
if not st.session_state.token:
    st.title("🔐 Mewar ERP Access")
    
    with st.form("auth_form"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Authenticate"):
            try:
                res = requests.post(LOGIN_URL, data={"username": u, "password": p})
                if res.status_code == 200:
                    st.session_state.token = res.json().get("access_token")
                    st.rerun()
                else:
                    st.error("❌ Invalid Username or Password.")
            except Exception as e:
                st.error(f"📡 FastAPI Server is Offline. ({e})")
    st.stop()

# ==========================================
# PAGE 2: CHATBOT INTERFACE
# ==========================================
with st.sidebar:
    st.header("Admin Panel")
    st.write("Logged in as: **Admin**")
    if st.button("🚪 Logout"):
        st.session_state.token = None
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.caption("Mewar ERP AI - Enterprise Edition")

st.title("ERP Intelligence 🧠")

def ask_erp(query):
    headers = {"Authorization": f"Bearer {st.session_state.token}", "Content-Type": "application/json"}
    history = [{"role": m["role"], "content": m.get("raw_content", "")} for m in st.session_state.messages]
    try:
        r = requests.post(CHAT_URL, json={"query": query, "history": history}, headers=headers)
        if r.status_code == 401: return {"detail": "Session Expired. Please Logout."}
        return r.json()
    except: return {"error": "FastAPI Connection Failed."}

# Render Chat History
for idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant" and "data" in msg:
            render_bot_response(msg["data"], idx)
        else:
            st.markdown(msg.get("raw_content", ""))

u_input = st.chat_input("Ask me anything about your inventory...")
final_query = u_input or st.session_state.next_query

if final_query:
    st.session_state.next_query = None 
    
    with st.chat_message("user"):
        st.markdown(final_query)
    st.session_state.messages.append({"role": "user", "raw_content": final_query})
    
    data = ask_erp(final_query)
    
    with st.chat_message("assistant"):
        render_bot_response(data, len(st.session_state.messages))
        st.session_state.messages.append({
            "role": "assistant", 
            "data": data, 
            "raw_content": data.get("message", "Processed.")
        })