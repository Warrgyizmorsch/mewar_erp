import streamlit as st
import requests
import pandas as pd

# --- CONFIGURATION ---
API_BASE = "http://localhost:8000"
CHAT_URL = f"{API_BASE}/chatbot/"
LOGIN_URL = f"{API_BASE}/auth/login"

st.set_page_config(page_title="Mewar ERP AI", page_icon="🧠", layout="centered")

# --- STYLING ---
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { border-radius: 5px; background-color: #007bff; color: white; width: 100%; height: 45px; font-weight: bold; }
    .login-box { max-width: 450px; margin: auto; padding: 40px; background: white; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); }
    .metric-card { background: white; padding: 15px; border-radius: 10px; border: 1px solid #eee; text-align: center; }
    </style>
""", unsafe_allow_html=True)

# --- SESSION STATE INITIALIZATION ---
if "token" not in st.session_state:
    st.session_state.token = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "next_query" not in st.session_state:
    st.session_state.next_query = None

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

    # CASE 1: Supplier Directory Table
    if data.get("type") == "supplier_list":
        st.info(data["message"])
        df_sup = pd.DataFrame(data["suppliers"])
        st.dataframe(df_sup, use_container_width=True, hide_index=True)

    # CASE 2: Supplier Profile Card
    elif data.get("type") == "result" and "supplier" in data:
        sup = data["supplier"]
        st.success(f"🏭 **{sup['name']}** ({sup['code']})")
        st.markdown(f"**Email:** {sup['email']} | **GSTIN:** {sup['gstin']}")
        
        col_f, col_s = st.columns(2)
        col_f.metric("Finish Stock Balance", f"{data['finish_stock']} units")
        col_s.metric("Semi-Finish Balance", f"{data['semi_finish_stock']} units")
        
        with st.expander("Detailed Item Ledger"):
            df_items = pd.DataFrame(data["items"])
            st.dataframe(df_items, use_container_width=True, hide_index=True)

    # CASE 3: ANALYTICAL COMPARISON (Bar Chart)
    elif data.get("type") == "analytical_result":
        st.info(data["message"])
        df_analysis = pd.DataFrame(data["data"])
        st.bar_chart(data=df_analysis, x="supplier", y="stock", color="#17a2b8")
        with st.expander("View Numerical Comparison"):
            st.dataframe(df_analysis, use_container_width=True, hide_index=True)

    # CASE 4: Inventory Results (With Technical Details & Location)
    elif "results" in data:
        for res in data["results"]:
            if res["type"] == "result":
                inv = res["inventory"]
                st.success(f"📦 **{inv['name']}**")
                
                c1, c2, c3 = st.columns(3)
                with c1: st.metric("Current Stock", f"{res['stock']['total']} {inv.get('unit', 'units')}")
                with c2: st.metric("Item ID", f"#{inv['id']}")
                with c3: st.metric("Category", inv.get('classification', 'FINISH'))
                
                st.markdown(f"""
                <div style="background-color: #f1f8ff; padding: 12px; border-radius: 8px; margin-top: 10px; border-left: 4px solid #007bff;">
                    <p style="margin: 0; font-size: 14px; color: #333;">
                        📍 <b>Store Location:</b> {inv.get('placement', 'N/A')} &nbsp; | &nbsp; 
                        📐 <b>Dimensions (H x W x T):</b> {inv.get('height', 0)} x {inv.get('width', 0)} x {inv.get('thickness', 0)}
                    </p>
                </div>
                """, unsafe_allow_html=True)
            
            elif res["type"] == "dropdown":
                st.warning(res["message"])
                cols = st.columns(2)
                for i, item in enumerate(res["items"]):
                    cols[i % 2].button(
                        f"Check {item['name']}", 
                        key=f"btn_{item['id']}_{msg_idx}", 
                        on_click=set_next_query, 
                        args=(item['name'],)
                    )

            elif res["type"] == "suggestion":
                st.error(res["message"])
                st.write("Suggested matches from database:")
                for sug in res["suggestions"]:
                    st.button(
                        sug, 
                        key=f"sug_{sug}_{msg_idx}", 
                        on_click=set_next_query, 
                        args=(sug,)
                    )

    # CASE 5: Simple Text (Greetings)
    elif "message" in data:
        st.write(data["message"])
    else:
        st.warning("Unknown response format. Raw data:")
        st.json(data)

# ==========================================
# PAGE 1: LOGIN SYSTEM
# ==========================================
if not st.session_state.token:
    st.markdown('<div class="login-box">', unsafe_allow_html=True)
    st.title("🔐 Mewar ERP Access")
    st.caption("Enter your credentials to connect to the Intelligence Layer.")
    
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
                    st.error("Invalid Username or Password.")
            except Exception as e:
                st.error(f"FastAPI Server is Offline. ({e})")
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# ==========================================
# PAGE 2: CHATBOT INTERFACE
# ==========================================
with st.sidebar:
    st.header("Admin Panel")
    st.write(f"Logged in as: **Admin**")
    if st.button("🚪 Logout"):
        st.session_state.token = None
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.caption("Mewar ERP AI - Smart UI Version")

st.title("ERP Intelligence 🧠")

def ask_erp(query):
    headers = {"Authorization": f"Bearer {st.session_state.token}", "Content-Type": "application/json"}
    history = [{"role": m["role"], "content": m.get("raw_content", "")} for m in st.session_state.messages]
    try:
        r = requests.post(CHAT_URL, json={"query": query, "history": history}, headers=headers)
        if r.status_code == 401: return {"detail": "Session Expired. Please Logout."}
        return r.json()
    except: return {"error": "FastAPI Connection Failed."}

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