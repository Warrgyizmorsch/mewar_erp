import time
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.services.love_brain import check_license
from app.db.database import get_db
from app.schemas.chat import ChatRequest
import re
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
import difflib
#from rapidfuzz import process, fuzz
#import jellyfish
import json
from app.services.ollama_engine import ask_ollama

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

# ==========================================
#        FAISS Setup & Model
# ==========================================
print("⏳ Loading Semantic Search Model... (10-15 seconds)")

# ==========================================
# 🧠 FAISS SEMANTIC SEARCH ENGINE SETUP
# ==========================================
semantic_model = None
inv_names_list = []
sup_names_list = []
inv_faiss_index = None
sup_faiss_index = None
is_faiss_loaded = False
proj_names_list = []
proj_faiss_index = None

# 1. Sabse upar variables mein ye naya set add karein:
#generic_inv_words = set(["item", "items", "stock", "maal", "inventory", "nag", "quantity", "qty", "piece", "pieces"])
# generic_inv_words = set()
# generic_sup_words = set()   # 🆕
# generic_proj_words = set()  # 🆕 

def load_faiss_once(db: Session):
    global semantic_model, inv_names_list, sup_names_list, inv_faiss_index, sup_faiss_index, is_faiss_loaded, proj_names_list, proj_faiss_index
    
    if is_faiss_loaded: return
    
    print("⏳ Loading Semantic Search Model... (10-15 seconds) - Ye sirf Server Start par 1 baar hoga!")
    semantic_model = SentenceTransformer('all-MiniLM-L6-v2')
    
    print("🛠️ Building FAISS Memory from Database...")
    try:
        # 1. Inventory Indexing
        inv_data = db.execute(text("SELECT name FROM inventories WHERE name IS NOT NULL")).fetchall()
        inv_names_list = [row[0] for row in inv_data if row[0]]
        if inv_names_list:
            inv_embeddings = semantic_model.encode(inv_names_list).astype('float32')
            inv_faiss_index = faiss.IndexFlatL2(inv_embeddings.shape[1])
            inv_faiss_index.add(inv_embeddings)
            
            # # 🧠 THE MAGIC: DYNAMIC ITEM DICTIONARY GENERATOR
            # # Bot khud database ke items padh kar list banayega (e.g., 'round bar', 'oil seal')
            # for name in inv_names_list:
            #     clean_name = re.sub(r'[^a-zA-Z\s]', '', str(name)).lower()
            #     words = clean_name.split()
            #     if words:
            #         if len(words[0]) > 2: # Single words (e.g., 'round', 'oil', 'tape')
            #             generic_inv_words.add(words[0]) 
            #         if len(words) > 1 and len(words[0]) > 1: # Double words (e.g., 'round bar', 'oil seal')
            #             generic_inv_words.add(f"{words[0]} {words[1]}")

        # 2. Supplier Indexing
        sup_data = db.execute(text("SELECT supplier_name FROM suppliers WHERE supplier_name IS NOT NULL")).fetchall()
        sup_names_list = [row[0] for row in sup_data if row[0]]
        if sup_names_list:
            sup_embeddings = semantic_model.encode(sup_names_list).astype('float32')
            sup_faiss_index = faiss.IndexFlatL2(sup_embeddings.shape[1])
            sup_faiss_index.add(sup_embeddings)

            # for name in sup_names_list:
            #     words = re.findall(r'\w+', str(name).lower())
            #     if words: 
            #         generic_sup_words.update([w for w in words if len(w) > 2])

        # 3. 🏗️ PROJECT INDEXING
        proj_data = db.execute(text("SELECT name FROM projects WHERE name IS NOT NULL AND is_deleted = 0")).fetchall()
        proj_names_list = [row[0] for row in proj_data if row[0]]
        if proj_names_list:
            proj_embeddings = semantic_model.encode(proj_names_list).astype('float32')
            proj_faiss_index = faiss.IndexFlatL2(proj_embeddings.shape[1])
            proj_faiss_index.add(proj_embeddings)

            # for name in proj_names_list:
            #     words = re.findall(r'\w+', str(name).lower())
            #     if words: 
            #         generic_proj_words.update([w for w in words if len(w) > 2])   
            
        is_faiss_loaded = True
        print(f"✅ FAISS Ready! Indexed {len(inv_names_list)} Items, {len(sup_names_list)} Suppliers & {len(proj_names_list)} Projects.")
    except Exception as e:
        print(f"⚠️ FAISS Load Error: {e}")

def smart_match(query_text, category="inventory"):
    if not query_text or len(query_text) < 2 or not is_faiss_loaded: return query_text
    try:
        query_vector = semantic_model.encode([query_text]).astype('float32')
        
        if category == "inventory" and inv_faiss_index:
            distances, indices = inv_faiss_index.search(query_vector, 3)
            if distances[0][0] < 0.7:  # Threshold for inventory matching (Stricter)   
                return inv_names_list[indices[0][0]]
                
        elif category == "supplier" and sup_faiss_index:
            distances, indices = sup_faiss_index.search(query_vector, 3)
            if distances[0][0] < 0.7:
                return sup_names_list[indices[0][0]]

        # 🟢 FIX 2: Project ke liye FAISS check add kiya
        elif category == "project" and proj_faiss_index:
            distances, indices = proj_faiss_index.search(query_vector, 3)
            if distances[0][0] < 1.0:
                return proj_names_list[indices[0][0]]
                
    except Exception as e: 
        pass
    
    return query_text
# ==========================================

# 🛠️ THE SLANG LIBRARY
def translate_slang(text: str):
    slang_map = {
        r'\bmaal\b': 'inventory',
        r'\bstock\b': 'inventory',
        r'\bkharcha\b': 'budget',
        r'\brokra\b': 'balance_amount',
        r'\bpaisa\b': 'amount',
        r'\bkitna\b': 'total_stock',
        r'\bitem\b': 'inventory',
    }
    for slang, official in slang_map.items():
        text = re.sub(slang, official, text, flags=re.IGNORECASE)
    return text

# 🌟 YAHAN PASTE KAREIN (Above @router.post("/"))
def advanced_intent_detector(query: str):
    q = query.lower()
    score = {"po_search": 0, "supplier_search": 0, "project_search": 0, "search": 0}

    # 1. Scoring Logic
    po_words = ["po", "order", "orders", "purchase", "transit", "raste", "pending", "dispatch", "delivery"]
    sup_words = ["supplier", "vendor", "party", "contact", "mobile", "number", "account", "details", "profile"]
    proj_words = ["project", "site", "crusher", "running", "urgent", "completed", "refurbish"]
    inv_words = ["stock", "maal", "item", "inventory", "quantity", "kitna", "qty", "nag", "available"]

    for w in po_words: 
        if w in q: score["po_search"] += 2
    for w in sup_words: 
        if w in q: score["supplier_search"] += 2
    for w in proj_words: 
        if w in q: score["project_search"] += 2
    for w in inv_words: 
        if w in q: score["search"] += 2

    if any(w in q for w in ["stock", "maal", "kitna"]) and any(w in q for w in ["supplier", "party"]):
        score["search"] += 3 

    best_intent = max(score, key=score.get)
    return best_intent if score[best_intent] > 0 else "search"

def clean_target_ultimate(target: str):
    noise = ["dikhao", "batao", "check", "ka", "ki", "ke", "mein", "inventory", "stock", "orders", "po", "list", "mujhe", "hai", "bhai", "details", "contact"]
    words = target.split()
    cleaned = [w for w in words if w.lower() not in noise]
    return " ".join(cleaned) if cleaned else target

# --- Existing helpers ---
def log_query(query, intent, result):
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "intent": intent,
        "is_fail": any(w in str(result).lower() for w in ["nahi mila", "not found", "error", "samajh nahi"]) or not result
    }
    try:
        with open("logs.json", "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"❌ Logging Error: {e}")

@router.post("/")
def chatbot(request: ChatRequest, db: Session = Depends(get_db)):
    raw_q = request.query.strip()
    low_q = raw_q.lower()
    
    # 🎯 STEP 1: FAST-TRACK ID (Seatbelt 1 - Exact Numeric)
    if low_q.isdigit() and len(low_q) < 8:
        try:
            inv = db.execute(text("SELECT id, name, classification, placement FROM inventories WHERE id = :id"), {"id": int(low_q)}).fetchone()
            if inv:
                stock_res = db.execute(text("SELECT SUM(CASE WHEN LOWER(txn_type) = 'in' THEN quantity ELSE -quantity END) FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).scalar()
                total_qty = float(stock_res or 0)
                cls = str(inv.classification).lower() if inv.classification else ""
                m, f, sf = (total_qty, 0, 0) if "machining" in cls else (0, 0, total_qty) if "semi" in cls else (0, total_qty, 0)
                return {"results": [{"type": "result", "inventory": {"id": inv.id, "name": inv.name, "category": cls.upper(), "placement": inv.placement or "N/A"}, "total_stock": total_qty, "finish_stock": f, "semi_finish_stock": sf, "machining_stock": m}]}
        except: pass

    # 🚀 STEP 2: PURE AI ENGINE (Let AI Drive)
    try:
        try:
            ai_data = ask_ollama(raw_q, getattr(request, "history", []))
        except:
            time.sleep(1) # Rate limit buffer
            ai_data = ask_ollama(raw_q, getattr(request, "history", []))
            
        print("🤖 PURE AI BRAIN DECISION:", ai_data)
        ai_intent = ai_data.get("intent", "search")
    except Exception as e:
        print(f"❌ AI CRASHED: {str(e)}")
        log_query(raw_q, "unknown", {"error": str(e)})
        return {"results": [{"type": "chat", "message": "Bhai, mera AI brain abhi connect nahi ho pa raha. Kripya thodi der mein try karein. 🙏"}]}

    intent = ai_intent
    original_target = str(ai_data.get("search_target") or "").strip()

    # 🛡️ THE LIGHT SEATBELT (ChatGPT's Final Golden Rule)
    # Agar AI confuse hoke target kha jaye, toh seedha pucho. Dropdown spam nahi.
    if not original_target and intent in ["supplier_search", "project_search"]:
        # PO aur Inventory search empty ho sakte hain (e.g., "latest po", "all items")
        # Isliye unhe is restriction se bahar rakha hai.
        return {"results": [{"type": "chat", "message": "Bhai, kripya thoda clear batao ki aap kis company ya project ki baat kar rahe ho? 🙂"}]}

    # 🧹 THE NOISE CLEANER (Safai Abhiyan)
    import re
    noise_words = ["supplier", "vendor", "party", "details", "contact", "profile", "ki", "ka", "ke", "project", "site", "machine"]
    for word in noise_words:
        original_target = re.sub(rf'\b{word}\b', '', original_target, flags=re.IGNORECASE).strip()

    ai_data["search_target"] = original_target

    # 🛑 MINIMAL ID OVERRIDE (Only for Supplier Code pattern like sup-10)
    if re.match(r'^sup[-\s]?\d+$', original_target.lower()):
        intent = "supplier_search"

    print(f"✅ FINAL ROUTER DECISION: {intent} | TARGET: {original_target}")

    # 🎛️ FILTERS SYNC (UI takes priority)
    filters = ai_data.get("filters", {})
    ui_filters = getattr(request, "ui_filters", {}) or {}
    for key, value in ui_filters.items():
        if value: filters[key] = value
    limit = filters.get("limit", 5) or 5

    
    
    ## 📁 STEP 3: PROJECT LOGIC (UI + Sentence Based AI 🚀)
    if intent == "project_search":
        try:
            limit = filters.get("limit") or 10
            target = original_target.strip()
            
            # 1. AI/UI Filter Acquisition
            active_status = str(filters.get("status") or "").lower().strip()
            active_priority = str(filters.get("priority") or "").lower().strip()
            machine_filter = str(filters.get("machine") or "").lower().strip()

            # 2. Base Query Construction
            query = "SELECT * FROM projects WHERE is_deleted = 0"
            params = {}

            # --- UI Filter Sync (Priority) ---
            if active_priority and active_priority != "all":
                query += " AND LOWER(priority) = :pr"
                params["pr"] = active_priority
            
            # --- UI Filter Sync (Status) ---
            if active_status and active_status != "all":
                if active_status == "refurbished": 
                    query += " AND refurbish = 1"
                else: 
                    query += " AND LOWER(status) = :st"
                    params["st"] = active_status
            
            # --- Machine Filter (Name + Comment) ---
            if machine_filter and machine_filter != "all":
                query += " AND (LOWER(name) LIKE :mch OR LOWER(comment) LIKE :mch)"
                params["mch"] = f"%{machine_filter}%"

            # 3. 🧠 SMART SENTENCE SEARCH (Word-by-word AND Logic)
            if target and target.lower() not in ["all", "list", "projects", "latest"]:
                words = target.lower().split()
                # Har word name ya comment mein hona chahiye (Smart Matching)
                target_conds = " AND ".join([f"(LOWER(name) LIKE :t{i} OR LOWER(comment) LIKE :t{i})" for i in range(len(words))])
                query += f" AND ({target_conds})"
                for i, w in enumerate(words):
                    params[f"t{i}"] = f"%{w}%"

            # 4. Execute Search
            projs = db.execute(text(query + f" ORDER BY id DESC LIMIT :limit"), {**params, "limit": limit}).fetchall()

            # 5. 🔍 FAISS FALLBACK (If SQL fails, check spelling/typo)
            if not projs and target and len(target) > 3:
                print(f"⚠️ Project SQL Failed for '{target}', checking FAISS...")
                corrected_name = smart_match(target, category="project")
                if corrected_name and corrected_name.lower() != target.lower():
                    # Retry SQL with FAISS suggestion
                    projs = db.execute(text(f"SELECT * FROM projects WHERE is_deleted = 0 AND LOWER(name) LIKE :cn LIMIT :limit"), 
                                     {"cn": f"%{corrected_name.lower()}%", "limit": limit}).fetchall()
                    if projs:
                        print(f"🧠 Project FAISS Success: Found '{corrected_name}'")

            if not projs:
                return {"results": [{"type": "chat", "message": f"Bhai, '{target or 'is filter'}' wala koi project nahi mila. 🧐"}]}

            # 6. UI Mapping (Match with Screenshot Design 🖼️)
            proj_results = []
            for p in projs:
                # Type Tag logic based on refurbish flag
                type_tag = "Refurbished" if getattr(p, 'refurbish', 0) == 1 else "New Machine"
                
                # Auto-Progress calculation based on Status (Screenshot style)
                status_now = str(p.status).lower()
                auto_stage = "0%"
                if status_now == "completed": auto_stage = "100%"
                elif status_now == "in progress": auto_stage = "50%"
                elif status_now == "hold": auto_stage = "Hold"
                
                proj_results.append({
                    "type": "project",
                    "project_name": str(p.name),
                    "category": f"{type_tag} | {str(p.status).capitalize()}",
                    "amount": float(p.budget or 0),
                    "start_date": str(p.start_date) if p.start_date else "N/A",
                    "end_date": str(p.end_date or p.deadline or "N/A"),
                    "comments": str(p.comment or "No details available."),
                    "stage": getattr(p, 'stage', auto_stage),
                    "priority": str(p.priority).upper()
                })
            return {"results": proj_results}

        except Exception as e:
            return {"results": [{"type": "chat", "message": f"Project Error: {str(e)}"}]}
        

   # 🏭 STEP 4: SUPPLIER LOGIC (V11 - Smart LIKE & Safe FAISS)
    if intent == "supplier_search":
        try:
            # 1. 🧠 TARGET & FILTER ACQUISITION
            original_target = str(ai_data.get("search_target") or "").strip()
            target_lower = original_target.lower()
            
            limit = filters.get("limit") or 10
            city_filter = filters.get("city") or filters.get("location")
            cat_filter = filters.get("category")
            email_filter = filters.get("email")
            mobile_filter = filters.get("mobile")
            code_filter = filters.get("supplier_code")
            
            all_keywords = ["all", "saare", "sabhi", "list", "supplier", "suppliers", "party"]
            is_all_request = not original_target and not city_filter and not cat_filter and any(w in low_q for w in all_keywords)

            sups = []
            
            # 📊 2. DATABASE SEARCH (THE WATERFALL PIPELINE)
            if is_all_request:
                sups = db.execute(text("SELECT * FROM suppliers ORDER BY id DESC LIMIT :l"), {"l": limit}).fetchall()

            elif city_filter or cat_filter or email_filter or mobile_filter or code_filter:
                query = "SELECT * FROM suppliers WHERE 1=1"
                params = {"l": limit}
                
                if city_filter: 
                    query += " AND LOWER(city) LIKE :c"; params["c"] = f"%{str(city_filter).lower()}%"
                if cat_filter: 
                    query += " AND LOWER(category) LIKE :cat"; params["cat"] = f"%{str(cat_filter).lower()}%"
                if email_filter: 
                    query += " AND LOWER(email) LIKE :e"; params["e"] = f"%{str(email_filter).lower()}%"
                if mobile_filter: 
                    query += " AND mobile LIKE :m"; params["m"] = f"%{str(mobile_filter)}%"
                if code_filter: 
                    query += " AND LOWER(supplier_code) LIKE :sc"; params["sc"] = f"%{str(code_filter).lower()}%"
                    
                sups = db.execute(text(query + " LIMIT :l"), params).fetchall()

            else:
                # 1️⃣ ID / Code Check
                if re.match(r'^sup[-\s]?\d+$', target_lower):
                    code_search = re.sub(r'^sup[-\s]?', '', target_lower)
                    sups = db.execute(text("SELECT * FROM suppliers WHERE supplier_code = :c OR id = :c LIMIT 1"), {"c": code_search}).fetchall()
                
                # WATERFALL SEARCH
                if not sups and original_target:
                    # 2️⃣ EXACT MATCH
                    sups = db.execute(text("""
                        SELECT * FROM suppliers 
                        WHERE LOWER(supplier_name) = :q 
                        LIMIT 1
                    """), {"q": target_lower}).fetchall()
                    
                    # 3️⃣ SMART LIKE JOIN (ChatGPT's Masterstroke 🔥)
                    if not sups:
                        words = target_lower.split()
                        # Creates: (name LIKE %w1% OR mobile LIKE %w1%) AND (name LIKE %w2% OR mobile LIKE %w2%)
                        like_conditions = " AND ".join([f"(LOWER(supplier_name) LIKE :w{i} OR mobile LIKE :w{i})" for i in range(len(words))])
                        params = {f"w{i}": f"%{w}%" for i, w in enumerate(words)}
                        params["l"] = limit
                        
                        sups = db.execute(text(f"""
                            SELECT * FROM suppliers 
                            WHERE {like_conditions} 
                            LIMIT :l
                        """), params).fetchall()
                    
                    # 4️⃣ FAISS (LAST RESORT - With Safe Validation)
                    if not sups and len(original_target) > 4: 
                        print(f"⚠️ SQL Failed for '{original_target}', falling back to FAISS...")
                        
                        # ✨ Word Count Limit Removed! Let FAISS check everything.
                        corrected = smart_match(original_target, category="supplier")
                        
                        # ✨ THE REAL VALIDATION (Typo-safe)
                        #import difflib
                        def is_valid_match(a, b):
                            # 0.5 means at least 50% spelling should match. 
                            return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.5

                        if corrected and corrected != original_target and is_valid_match(original_target, corrected):
                            print(f"🧠 FAISS Suggested: '{corrected}'")
                            c_words = corrected.lower().split()
                            # Reuse Smart LIKE for corrected word
                            c_like_conds = " AND ".join([f"(LOWER(supplier_name) LIKE :w{i} OR mobile LIKE :w{i})" for i in range(len(c_words))])
                            c_params = {f"w{i}": f"%{w}%" for i, w in enumerate(c_words)}
                            c_params["l"] = limit

                            sups = db.execute(text(f"""
                                SELECT * FROM suppliers 
                                WHERE {c_like_conds} 
                                LIMIT :l
                            """), c_params).fetchall()

            # 3. 🚨 NO MATCH & DROPDOWN HANDLING
            if not sups: 
                return {"results": [{"type": "chat", "message": f"Bhai, '{original_target}' naam ka koi Supplier nahi mila. 🧐"}]}
            
            if len(sups) > 1: 
                return {"results": [
                    {"type": "chat", "message": f"📊 Mujhe {len(sups)} suppliers mile hain:"},
                    {"type": "dropdown", "message": "Select a supplier for details:", "items": [{"id": str(getattr(s, 'supplier_name', 'Unknown')), "name": str(getattr(s, 'supplier_name', 'Unknown'))} for s in sups]}
                ]}
            
            # 4. 💳 SINGLE MATCH (Interceptor + Stock Details)
            s = sups[0]
            sup_name = str(getattr(s, 'supplier_name', 'Unknown'))
            is_asking_details = any(w in low_q for w in ["detail", "details", "contact", "number", "profile", "hisab", "account"])
            
            if not is_asking_details and not is_all_request and "sup-" not in target_lower and not target_lower.isdigit():
                msg = f"Bhai, mujhe **{sup_name}** system mein mil gaye hain. Aap inka kya dekhna chahte hain?\n\n" \
                      f"📦 Type **'Orders'** (Purchase Orders ke liye)\n" \
                      f"👤 Type **'Details'** (Contact Info ke liye)"
                return {"results": [{"type": "chat", "message": msg}]}

            # 5. ✅ FINAL CARD LOAD
            inv_items = db.execute(text("""
                SELECT i.name, SUM(CASE WHEN LOWER(t.txn_type) = 'in' THEN t.quantity ELSE -t.quantity END) as stock 
                FROM inventories i JOIN stock_transactions t ON i.id = t.inventory_id 
                WHERE t.supplier_id = :sid GROUP BY i.id, i.name HAVING stock != 0
            """), {"sid": s.id}).fetchall()
            
            return {"results": [
                {
                    "type": "result", 
                    "supplier": {
                        "id": s.id, "name": sup_name, 
                        "code": str(getattr(s, 'supplier_code', 'N/A') or 'N/A'), 
                        "mobile": str(getattr(s, 'mobile', 'N/A') or 'N/A'), 
                        "city": str(getattr(s, 'city', 'N/A') or 'N/A'), 
                        "email": str(getattr(s, 'email', 'N/A') or 'N/A'),
                        "gstin": str(getattr(s, 'gstin', 'N/A') or 'N/A')
                    }, 
                    "items": [{"name": str(row.name), "stock": float(row.stock)} for row in inv_items]
                }, 
                {"type": "chat", "message": f"💡 **Tip:** Type *'Orders of {sup_name}'* unke POs dekhne ke liye."}
            ]}
            
        except Exception as e: 
            print(f"❌ SUPPLIER ERROR: {str(e)}")
            return {"results": [{"message": f"Supplier Error: {str(e)}"}]}

    # 🧾 STEP 5: PO LOGIC (Aapka 100% Mapping + Sniper Search 🎯)
    if intent == "po_search":
        try:
            # 1. Dynamic Limit Logic
            limit = filters.get("limit") or 20
            if any(w in low_q for w in ["all", "saare", "sabhi", "pure", "poore", "sab"]):
                limit = 100
            elif any(w in low_q for w in ["last", "latest", "nayan", "abhi wala"]):
                limit = 1

            # 🧠 2. DIRECT AI TARGETING & STICKY MEMORY (Aapka Pure Logic)
            raw_target = ai_data.get("filters", {}).get("supplier") or ai_data.get("search_target")
            clean_target = str(raw_target).lower().strip() if raw_target else ""
            
            is_all_request = any(w in low_q for w in ["all", "saare", "sabhi", "pure", "poore", "sab"])
            if is_all_request: clean_target = ""
            
            history = getattr(request, "history", [])
            if not clean_target and history and not is_all_request:
                follow_up_words = ["uska", "uske", "uski", "inka", "inke", "inki", "iski", "iska", "bhi", "aur"]
                is_follow_up = any(w in low_q for w in follow_up_words)
                
                last_bot_msg = ""
                for msg in reversed(history):
                    if str(msg.get("role", "")).lower() in ["assistant", "ai", "bot"]:
                        last_bot_msg = str(msg.get("content") or msg.get("message") or "")
                        if len(last_bot_msg) > 10: break 
                
                is_choice_prompt = "kya dekhna chahte hain" in last_bot_msg.lower() or "orders of" in last_bot_msg.lower()
                
                if is_follow_up or is_choice_prompt:
                    patterns = [r"Orders of (.*?)'", r'\*\*(.*?)\*\*', r'mujhe\s+(.*?)\s+system']
                    for pat in patterns:
                        match = re.search(pat, last_bot_msg, re.IGNORECASE)
                        if match:
                            temp_mem = re.sub(r'[*_]|<[^>]+>', '', match.group(1)).strip()
                            if temp_mem.lower() not in ["orders", "projects", "details", "", "po", "chat", "message"]:
                                clean_target = temp_mem
                                break
                    if not clean_target and is_choice_prompt:
                        return {"results": [{"type": "chat", "message": "Bhai, aap kis party ke orders dekhna chahte hain? 🧐"}]}

            # Cleanup
            clean_target = re.sub(r'[?\'"!.,]', ' ', clean_target).strip()
            clean_target = re.sub(r'\s+', ' ', clean_target).strip()

            # 📊 3. Database Query (Sync with UI Screenshot)
            query = """
                SELECT p.*, s.supplier_name 
                FROM purchase_orders p 
                JOIN suppliers s ON p.supplier_id = s.id 
                WHERE 1=1
            """
            params = {"l": limit}
            
            # Transit Logic
            if any(w in low_q for w in ["transit", "raste mein", "dispatched"]):
                query += " AND (LOWER(p.delivery_status) LIKE '%transit%' OR LOWER(p.delivery_status) LIKE '%dispatched%')"
                limit = 100 
                clean_target = clean_target.replace("transit", "").strip()
                active_status = ""           
                filters["from_date"], filters["to_date"] = None, None

            # Filters (Date & Status)
            if filters.get("from_date") and filters.get("to_date"):
                query += " AND p.po_date BETWEEN :start AND :end"
                params["start"], params["end"] = filters['from_date'], filters['to_date']
            
            active_status = str(filters.get("status") or "").lower().strip()
            if active_status:
                query += " AND LOWER(p.status) = :pst"; params["pst"] = active_status

            # 🎯 Sniper Search (Word-by-word)
            if clean_target and len(clean_target) > 1:
                words = [w for w in clean_target.split() if len(w) > 1]
                if words:
                    search_conds = " AND ".join([f"(LOWER(s.supplier_name) LIKE :s{i} OR LOWER(p.po_number) LIKE :s{i})" for i in range(len(words))])
                    query += f" AND ({search_conds})"
                    for i, w in enumerate(words): params[f"s{i}"] = f"%{w}%"

            # Execute & FAISS
            pos = db.execute(text(query + " ORDER BY p.po_date DESC, p.id DESC LIMIT :l"), params).fetchall()

            if not pos and clean_target and len(clean_target) > 3:
                corrected = smart_match(clean_target, category="supplier")
                if corrected and corrected.lower() != clean_target.lower():
                    import difflib
                    if difflib.SequenceMatcher(None, clean_target.lower(), corrected.lower()).ratio() > 0.5:
                        retry_query = "SELECT p.*, s.supplier_name FROM purchase_orders p JOIN suppliers s ON p.supplier_id = s.id WHERE LOWER(s.supplier_name) LIKE :cn ORDER BY p.po_date DESC LIMIT :l"
                        pos = db.execute(text(retry_query), {"cn": f"%{corrected.lower()}%", "l": limit}).fetchall()

            if not pos:
                return {"results": [{"type": "chat", "message": f"Bhai, '{clean_target}' ke liye koi orders nahi mile. 🧐"}]}

            # 🖼️ 4. FULL UI MAPPING (As requested, nothing hidden!)
            po_results = []
            total_count = len(pos)
            
            # Chat Message logic
            if total_count > 1:
                msg = f"Mujhe kul **{total_count}** orders mile hain. List niche dekhein: 👇"
                if total_count == limit and limit < 100:
                    msg = f"Top **{total_count}** orders ki list. Saare dekhne ke liye 'all' bole."
                po_results.append({"type": "chat", "message": msg})
            else:
                po_results.append({"type": "chat", "message": "Mujhe ye **1** Purchase Order mila hai: 👇"})

            for po in pos:
                # Aapke exact variables aur aliases
                po_num = str(po.po_number) or "N/A"
                total = float(po.total_amount or 0)
                advance = float(po.advance_amount or 0)
                balance = float(po.balance_amount or 0)
                subtotal = float(po.subtotal_discount_amount or po.subtotal or 0)
                tax = float(po.tax_amount or 0)
                status = str(po.status).capitalize() if po.status else "Draft"
                
                po_results.append({
                    "type": "po",
                    "po_number": po_num,
                    "po_no": po_num, # Alias safe
                    "supplier": str(po.supplier_name),
                    "date": str(po.po_date),
                    "expected_date": str(po.expected_delivery) if po.expected_delivery else "N/A",
                    "subtotal": subtotal,
                    "tax_amount": tax,
                    "total_amount": total,
                    "amount": total, # Alias safe
                    "advance_amount": advance,
                    "advance": advance, # Alias safe
                    "balance_amount": balance,
                    "balance": balance, # Alias safe
                    "status": status,
                    "delivery_status": str(getattr(po, 'delivery_status', 'Pending')), # From Screenshot
                    "remarks": str(po.remarks) if po.remarks else ""
                })

            return {"results": po_results}

        except Exception as e:
            print(f"❌ PO ERROR: {str(e)}")
            return {"results": [{"message": f"PO Error: {str(e)}"}]}
        
  # 📦 STEP 6: INVENTORY SEARCH (The Final Decision Engine - 100% AI Driven)
    if intent == "search":
        try:
            # 1. NLP Context Check (Business Logic - NOT Noise Removal)
            is_asking_total = any(word in low_q for word in ["how many", "total", "kitna", "kitne", "stock", "nag", "maal", "count"])
            
            # 2. 🧠 DIRECT TARGETING (Router V7 ne theek kiya hai)
            raw_target = str(ai_data.get("search_target") or "").lower().strip()
            
            # Agar AI ne target nahi diya, ya fallback list pass kari hai
            if not raw_target:
                spec_items = ai_data.get("specific_items", [])
                raw_target = spec_items[0] if spec_items else low_q

            # 🛑 3. Location Guard: AI data se nikalo, text se nahi
            loc = filters.get("placement") or filters.get("location") or filters.get("city")
            if not loc:
                if "mhel" in low_q: loc = "mhel"
                elif "main" in low_q: loc = "main"
            
            # Location aur Punctuation hatao taaki FAISS properly target ko match kare
            clean_target = raw_target
            if loc: 
                clean_target = clean_target.replace(loc.lower(), "").strip()
            
            clean_target = re.sub(r'[?\'"!.,]', '', clean_target).strip()
            clean_target = re.sub(r'\s+', ' ', clean_target).strip()

            clean_targets = []
            
            # 🚀 4. FAISS MAGIC: INVENTORY AUTO-CORRECT
            if len(clean_target) > 1: 
                corrected_inv = smart_match(clean_target, category="inventory")
                print(f"🧠 INVENTORY FAISS: '{clean_target}' -> '{corrected_inv}'")
                clean_targets.append(corrected_inv)
                print(f"🎯 Final Search Term: '{corrected_inv}'")
            
            # Fallback if everything got stripped
            if not clean_targets and ("bearing" in low_q or "belt" in low_q): 
                clean_targets = ["bearing" if "bearing" in low_q else "belt"]

            all_inv_names = [row.name.lower() for row in db.execute(text("SELECT name FROM inventories")).fetchall() if row.name]
            final_results = []

            for t in clean_targets:
                # 🔍 5. SQL SEARCH: Name + Model
                query_str = "SELECT id, name, model, type, classification, placement FROM inventories WHERE (LOWER(name) LIKE :q OR LOWER(model) LIKE :q)"
                params = {"q": f"%{t}%"}
                
                # Dynamic Location Filter
                if loc:
                    query_str += " AND (LOWER(placement) LIKE :loc OR LOWER(placement) LIKE :loc_full)"
                    params["loc"] = f"%{loc.lower().replace('store', '').strip()}%"
                    params["loc_full"] = f"%{loc.lower()}%"
                
                items = db.execute(text(query_str + " LIMIT 30"), params).fetchall()
                
                # --- LAYER 2: FUZZY FALLBACK (For Model Numbers etc) ---
                if not items:
                    closest = difflib.get_close_matches(t, all_inv_names, n=1, cutoff=0.65)
                    if closest: 
                        params["q"] = f"%{closest[0]}%"
                        items = db.execute(text(query_str + " LIMIT 30"), params).fetchall()
                        t = closest[0]

                if not items: continue

                # --- 🧠 6. THE DECISION ENGINE (Same Output Format) ---
                ids = tuple([i.id for i in items])
                
                # 1️⃣ Case: MULTIPLE ITEMS FOUND (Dropdown Mode)
                # "bearing" ya "conveyor belt" yahan aayenge
                if len(items) > 1:
                    total_sum = db.execute(text("SELECT SUM(CASE WHEN LOWER(txn_type) = 'in' THEN quantity ELSE -quantity END) FROM stock_transactions WHERE inventory_id IN :ids"), {"ids": ids}).scalar() or 0
                    
                    breakdown = db.execute(text("SELECT i.placement, SUM(CASE WHEN LOWER(t.txn_type) = 'in' THEN t.quantity ELSE -t.quantity END) as qty FROM inventories i JOIN stock_transactions t ON i.id = t.inventory_id WHERE i.id IN :ids GROUP BY i.placement"), {"ids": ids}).fetchall()
                    loc_str = ", ".join([f"{r.qty:.2f} in {r.placement or 'Main Store'}" for r in breakdown if r.qty != 0])
                    
                    final_results.append({
                        "type": "chat", 
                        "message": f"📊 **Total {t.upper()} Stock:** {total_sum:.2f} units ({loc_str if loc_str else 'Global'})."
                    })
                    final_results.append({
                        "type": "dropdown", 
                        "message": f"I found {len(items)} matching items. Select one for details:", 
                        "items": [{"id": i.id, "name": f"{i.name} {i.model or ''}"} for i in items]
                    })

                # 2️⃣ Case: EXACTLY ONE ITEM FOUND (Card Mode)
                # "Bearing 608 ZZ" ya "KCC900" yahan aayenge
                elif len(items) == 1:
                    i = items[0]
                    stock = float(db.execute(text("SELECT SUM(CASE WHEN LOWER(txn_type) = 'in' THEN quantity ELSE -quantity END) FROM stock_transactions WHERE inventory_id = :id"), {"id": i.id}).scalar() or 0)
                    
                    disp_cat = i.type if i.type else "Raw Material"
                    disp_loc = i.placement if i.placement else "Main Store"
                    disp_class = str(i.classification).upper() if i.classification else "FINISH"
                    f, sf, m = (stock, 0, 0) if disp_class == "FINISH" else (0, stock, 0) if "SEMI" in disp_class else (0, 0, stock)
                    
                    final_results.append({
                        "type": "result", 
                        "inventory": {"id": i.id, "name": f"{i.name} {i.model or ''}", "category": disp_cat, "placement": disp_loc}, 
                        "total_stock": stock, "finish_stock": f, "semi_finish_stock": sf, "machining_stock": m
                    })

            if final_results: return {"results": final_results[:limit]}
            return {"results": [{"type": "chat", "message": "Bhai, ye item mere system mein nahi mila. 🧐"}]}

        except Exception as e:
            print(f"❌ ERROR IN STEP 6: {str(e)}")
            return {"results": [{"message": f"Inventory Error: {str(e)}"}]}

    # 🛑 7. FALLBACK / UNKNOWN INTENT (Safety Net)
    else:
        user_msg = low_q.lower()
        
        # Smart Suggestions based on keywords
        if "project" in user_msg or "site" in user_msg:
            suggestion_text = "Mujhe lagta hai aap **Projects** ki jankari chahte hain. Kripya us project ka naam batayein."
        elif "paisa" in user_msg or "balance" in user_msg or "hisab" in user_msg:
            suggestion_text = "Kya aap kisi Supplier ka **Balance** check karna chahte hain? Kripya likhein: 'Supplier Name ka status'."
        else:
            suggestion_text = "Maaf kijiye, main abhi aapki baat samajh nahi paaya. 😅\n\nAap inme se kuch poochna chahte hain?\n1. **Purchase Orders** (e.g., 'Latest PO')\n2. **Inventory** (e.g., 'Bearing stock')\n3. **Supplier Details**"

        fallback_res = {"results": [{"type": "chat", "message": suggestion_text}]}
        log_query(raw_q, intent, fallback_res)
        return fallback_res