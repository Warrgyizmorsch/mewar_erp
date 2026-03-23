from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.database import get_db
from app.schemas.chat import ChatRequest
from app.dependencies import get_current_user
import re
import difflib
import random
from app.services.ollama_engine import ask_ollama

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

@router.post("/")
def chatbot(request: ChatRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    raw_q = request.query.strip()
    low_q = raw_q.lower()
    
    # 🚀 STEP 1: EXACT STOCK MATCH (ID ONLY)
    exact_match = db.execute(text("""
        SELECT id, name, classification FROM inventories 
        WHERE id = :id_val
    """), {"id_val": int(low_q) if low_q.isdigit() else -1}).fetchone()

    if exact_match:
        inv = exact_match
        txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
        m, f, sf = 0, 0, 0
        cls = str(inv.classification).lower() if inv.classification else ""
        for t in txns:
            val = float(t.quantity or 0) * (1 if str(t.txn_type).lower() == "in" else -1)
            if "machining" in cls: m += val
            elif "semi" in cls: sf += val
            else: f += val
        
        return {"results": [{
            "type": "result",
            "inventory": {"id": inv.id, "name": inv.name, "classification": cls.upper()},
            "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m + f + sf)
        }]}

    # 🚀 STEP 2: AI INTENT
    ai_data = ask_ollama(raw_q, getattr(request, "history", []))
    intent = ai_data.get("intent", "search")
    
    # 👋 GREETINGS & CHAT INTERCEPTOR
    if intent == "chat" and "message" in ai_data:
        return {"results": [{"type": "chat", "message": ai_data["message"]}]}

    # 📊 STEP 2.5: MANAGER ANALYTICS INTERCEPTOR 
    if intent == "analytics":
        report_type = ai_data.get("report_type", "low_stock")
        
        all_inv = db.execute(text("SELECT id, name, classification FROM inventories")).fetchall()
        all_txns = db.execute(text("SELECT inventory_id, txn_type, quantity FROM stock_transactions")).fetchall()
        
        stock_map = {inv.id: {"Name": inv.name, "Stock": 0.0, "Category": inv.classification or "N/A"} for inv in all_inv}
        
        for t in all_txns:
            if t.inventory_id in stock_map:
                qty = float(t.quantity or 0)
                if str(t.txn_type).lower() == "in":
                    stock_map[t.inventory_id]["Stock"] += qty
                elif str(t.txn_type).lower() == "out":
                    stock_map[t.inventory_id]["Stock"] -= qty
                    
        stock_data = list(stock_map.values())
        
        if report_type == "low_stock":
            # ✅ FIX: Ignore 0-stock items so the report shows actual active inventory running low
            active_stock = [x for x in stock_data if x["Stock"] > 0]
            if not active_stock: # Safety net just in case everything is 0
                active_stock = stock_data
                
            active_stock.sort(key=lambda x: x["Stock"])
            stock_data = active_stock
            title = "📉 Top 10 Lowest Stock Items (Active)"
        else: 
            stock_data.sort(key=lambda x: x["Stock"], reverse=True)
            title = "📈 Top 10 Highest Stock Items"
            
        return {"results": [{
            "type": "analytics_chart",
            "title": title,
            "chart_type": "bar",
            "data": stock_data[:10]
        }]}

    # 🌟 MASTER LIST FOR INVENTORY & SUPPLIERS
    final_output = []

    # 🚀 STEP 3: RESTRICTED SUPPLIER LOGIC
    suppliers_found = []
    clean_s = ""

    supplier_keywords = ["supplier", "vendor", "party", "company", "email", "gstin", "sup-", "sup ", "suplier", "suppler", "supllier"]
    is_supplier_intent = any(k in low_q for k in supplier_keywords) or intent in ["supplier_search", "supplier_list"]

    code_match = re.search(r'(sup[-\s]\d+)', low_q)
    if code_match:
        clean_s = code_match.group(1).replace(" ", "-")
        suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_code) = :exact LIMIT 1"), {"exact": clean_s}).fetchall()
        if not suppliers_found:
            num_part = re.sub(r'\D', '', clean_s)
            if num_part:
                 suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE id = :id LIMIT 1"), {"id": int(num_part)}).fetchall()

    elif is_supplier_intent:
        noise = r'\b(bhai|kya|ki|status|hai|aaj|what|is|the|stock|for|who|email|gstin|details|ka|ke|bata|batao|do|please|yaar|mujhe|of|show|me|our|supplier|suppliers|suplier|suppler|supllier)\b'
        clean_s = re.sub(noise, '', low_q).strip()
        clean_s = re.sub(r'[^\w\s-]', '', clean_s).strip()
        clean_s = re.sub(r'\s+', ' ', clean_s)

        if clean_s:
            if clean_s.isdigit():
                suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE id = :id"), {"id": int(clean_s)}).fetchall()
            else:
                suppliers_found = db.execute(text("""
                    SELECT * FROM suppliers 
                    WHERE LOWER(supplier_name) LIKE :q OR LOWER(supplier_code) LIKE :q
                """), {"q": f"%{clean_s}%"}).fetchall()
                
                if not suppliers_found:
                    all_s = db.execute(text("SELECT id, supplier_name FROM suppliers")).fetchall()
                    s_names = {s.supplier_name.lower(): s.id for s in all_s}
                    matches = difflib.get_close_matches(clean_s, s_names.keys(), n=1, cutoff=0.5)
                    if matches:
                        best_match_id = s_names[matches[0]]
                        suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE id = :id LIMIT 1"), {"id": best_match_id}).fetchall()

    if suppliers_found:
        if len(suppliers_found) > 1:
            final_output.append({
                "type": "supplier_list",
                "message": f"I found multiple suppliers for '{clean_s}'. Please select one:",
                "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code or 'N/A'})"} for s in suppliers_found]
            })
        elif len(suppliers_found) == 1:
            supplier = suppliers_found[0]
            inventories = db.execute(text("""
                SELECT DISTINCT i.id, i.name, i.classification
                FROM inventories i JOIN stock_transactions st ON i.id = st.inventory_id
                WHERE st.supplier_id = :sid
            """), {"sid": supplier.id}).fetchall()

            finish_total, semi_finish_total, items = 0, 0, []
            for inv in inventories:
                txns = db.execute(text("""
                    SELECT txn_type, ref_type, quantity FROM stock_transactions
                    WHERE inventory_id = :inv_id AND supplier_id = :supplier_id
                """), {"inv_id": inv.id, "supplier_id": supplier.id}).fetchall()

                in_qty, out_qty = 0, 0
                for t in txns:
                    txn_type, ref_type, qty = (t.txn_type or "").lower(), (t.ref_type or "").lower(), float(t.quantity or 0)
                    if txn_type == "in" and ref_type != "finish": in_qty += qty
                    if txn_type == "out" and ref_type != "machining": out_qty += qty

                total = in_qty - out_qty
                if total != 0:
                    if (inv.classification or "").upper().strip() == "FINISH": finish_total += total
                    else: semi_finish_total += total
                    items.append({"inventory_id": inv.id, "name": inv.name, "stock": total})

            final_output.append({
                "type": "result", 
                "supplier": {
                    "id": supplier.id, "name": supplier.supplier_name, "code": getattr(supplier, 'supplier_code', 'N/A'),
                    "email": getattr(supplier, 'email', 'N/A'), "gstin": getattr(supplier, 'gstin', 'N/A')
                },
                "finish_stock": finish_total, "semi_finish_stock": semi_finish_total,
                "items": items, "message": f"Details for {supplier.supplier_name}"
            })
    
    # 🚀 STEP 4: GENERAL INVENTORY SEARCH
    raw_targets = ai_data.get("specific_items", [])
    
    ai_exclusions = ["supplier", "suppliers", "details", "list", "all", "suplier", "suppler", "supllier", "vendor", "party"]
    search_targets = [t for t in raw_targets if str(t).lower() not in ai_exclusions]
    
    inv_noise = r'\b(chahiye|kya|ki|status|hai|aaj|what|is|the|stock|for|details|ka|ke|bata|batao|do|please|yaar|mujhe|of|show|me|our|item|supplier|suppliers|suplier|suppler|supllier|vendor|party|kon|list|all)\b'
    clean_q = re.sub(inv_noise, '', low_q).strip()
    
    # ✅ FIX: Strip standalone quantities (like '50' or '10') so they don't break the string search
    clean_q = re.sub(r'\b\d+\b', '', clean_q)
    clean_q = re.sub(r'\s+', ' ', clean_q).strip()
    
    if not search_targets: 
        if clean_q: 
            # ✅ FIX: Added 'aur' to the split logic
            if re.search(r'\b(and|or|aur)\b|,', clean_q):
                search_targets = [x.strip() for x in re.split(r'\s+and\s+|\s+or\s+|\s+aur\s+|,', clean_q) if x.strip()]
            else:
                search_targets = [clean_q]
    
    seen_ids = set() 

    for target in search_targets:
        t_str = str(target).strip()
        if not t_str or len(t_str) < 2: continue
            
        inv_res = db.execute(text("""
            SELECT id, name, classification FROM inventories 
            WHERE LOWER(name) LIKE :q OR id = :id_val LIMIT 10
        """), {
            "q": f"%{t_str}%", 
            "id_val": int(t_str) if t_str.isdigit() else -1
        }).fetchall()

        if not inv_res:
            all_inv = db.execute(text("SELECT id, name, classification FROM inventories")).fetchall()
            inv_map = {}
            for i in all_inv:
                c_name = str(i.name).lower().strip()
                if c_name not in inv_map: inv_map[c_name] = []
                inv_map[c_name].append(i)
                
            matches = difflib.get_close_matches(t_str, inv_map.keys(), n=5, cutoff=0.4)
            if matches:
                inv_res = []
                for m in matches: inv_res.extend(inv_map[m])

        inv_res = [i for i in inv_res if i.id not in seen_ids]

        if len(inv_res) == 1:
            inv = inv_res[0]
            seen_ids.add(inv.id)
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            m, f, sf = 0, 0, 0
            cls = str(inv.classification).lower() if inv.classification else ""
            for t in txns:
                val = float(t.quantity or 0) * (1 if str(t.txn_type).lower() == "in" else -1)
                if "machining" in cls: m += val
                elif "semi" in cls: sf += val
                else: f += val
            
            final_output.append({
                "type": "result",
                "inventory": {"id": inv.id, "name": inv.name, "classification": cls.upper()},
                "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m + f + sf)
            })
            
        elif len(inv_res) > 1:
            final_output.append({
                "type": "dropdown", "message": f"Select an item for '{target}':",
                "items": [{"id": i.id, "name": i.name} for i in inv_res]
            })

    # 🎉 IF WE FOUND ANYTHING, RETURN IT!
    if final_output:
        return {"results": final_output}

    # 🆘 FALLBACK 1: SUPPLIER MENU
    if is_supplier_intent:
         all_s = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers")).fetchall()
         return {"results": [{
            "type": "supplier_list",
            "message": "Here is the complete list of suppliers:",
            "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code or 'N/A'})"} for s in all_s]
         }]}

    # 🆘 FALLBACK 2: TRUE RANDOM INVENTORY SUGGESTIONS
    # ✅ FIX: Removed LIMIT 50 to pull from the entire catalog for genuine randomness
    all_suggestions = db.execute(text("SELECT id, name FROM inventories")).fetchall()
    
    if all_suggestions:
        suggestions = random.sample(all_suggestions, min(5, len(all_suggestions)))
        return {"results": [{
            "type": "dropdown",
            "message": "I couldn't find exactly what you typed. Did you mean one of these?",
            "items": [{"id": s.id, "name": s.name} for s in suggestions]
        }]}
        
    return {"results": [{"message": "I couldn't find that in the database."}]}