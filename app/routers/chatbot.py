from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.database import get_db
from app.schemas.chat import ChatRequest
import re
import difflib
import random
from app.services.ollama_engine import ask_ollama

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

@router.post("/")
def chatbot(request: ChatRequest, db: Session = Depends(get_db)):
    raw_q = request.query.strip()
    low_q = raw_q.lower()
    
    # 🎯 STEP 1: ID-ONLY FAST-TRACK (Inventory Priority)
    if low_q.isdigit():
        inv = db.execute(text("SELECT id, name, classification, placement FROM inventories WHERE id = :id"), {"id": int(low_q)}).fetchone()
        if inv:
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
                "inventory": {
                    "id": inv.id, 
                    "name": inv.name, 
                    "classification": cls.upper() if cls else "N/A", 
                    "placement": getattr(inv, 'placement', None) or "Not Assigned"
                },
                "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m + f + sf)
            }]}

    # STEP 2: AI INTENT DETECTION
    ai_data = ask_ollama(raw_q, getattr(request, "history", []))
    intent = ai_data.get("intent", "search")
    
    # ==========================================
    # ADD THIS FIX: HARD KEYWORD OVERRIDES
    # Prevents AI from misclassifying explicit requests
    # ==========================================
    if re.search(r'\b(po|purchase order|mhel/po)\b', low_q):
        intent = "po_search"
    elif re.search(r'\b(project|projects)\b', low_q):
        intent = "project_search"
    # ==========================================

    if intent == "chat" and "message" in ai_data:
        return {"results": [{"type": "chat", "message": ai_data["message"]}]}

    # ==========================================
    # THE NEW GIBBERISH BLOCKER
    # ==========================================
    if intent == "unknown":
        msg = ai_data.get("message", "I didn't understand. Are you looking for Inventory, POs, Suppliers, or Projects?")
        return {"results": [{"type": "chat", "message": msg}]}
    # ==========================================

    # 📊 STEP 3: MANAGER ANALYTICS
    if intent == "analytics":
        report_type = ai_data.get("report_type", "low_stock")
        all_inv = db.execute(text("SELECT id, name, classification FROM inventories")).fetchall()
        all_txns = db.execute(text("SELECT inventory_id, txn_type, quantity FROM stock_transactions")).fetchall()
        stock_map = {inv.id: {"Name": inv.name, "Stock": 0.0, "Category": inv.classification or "N/A"} for inv in all_inv}
        for t in all_txns:
            if t.inventory_id in stock_map:
                qty = float(t.quantity or 0)
                if str(t.txn_type).lower() == "in": stock_map[t.inventory_id]["Stock"] += qty
                elif str(t.txn_type).lower() == "out": stock_map[t.inventory_id]["Stock"] -= qty
        stock_data = list(stock_map.values())
        if report_type == "low_stock":
            active_stock = [x for x in stock_data if x["Stock"] > 0]
            if not active_stock: active_stock = stock_data
            active_stock.sort(key=lambda x: x["Stock"])
            stock_data = active_stock
            title = "📉 Top 10 Lowest Stock Items (Active)"
        else: 
            stock_data.sort(key=lambda x: x["Stock"], reverse=True)
            title = "📈 Top 10 Highest Stock Items"
        return {"results": [{"type": "analytics_chart", "title": title, "chart_type": "bar", "data": stock_data[:10]}]}
# 🧾 STEP 4: PURCHASE ORDER (PO) LOGIC
    if intent == "po_search":
        ai_target = ai_data.get("search_target", "").strip()
        
        # We use a JOIN here to get the actual Supplier Name (like "Arawali Minerals" in your screenshot)
        base_query = """
            SELECT p.*, s.supplier_name 
            FROM purchase_orders p
            LEFT JOIN suppliers s ON p.supplier_id = s.id
        """
        
        if not ai_target:
            query = text(base_query + " ORDER BY p.id DESC LIMIT 5")
            po_results = db.execute(query).fetchall()
        else:
            # We search against purchase_order_no based on your screenshot
            query = text(base_query + " WHERE LOWER(p.purchase_order_no) LIKE :q ORDER BY p.id DESC LIMIT 5")
            po_results = db.execute(query, {"q": f"%{ai_target.lower()}%"}).fetchall()

        if po_results:
            results = []
            for p in po_results:
                results.append({
                    "type": "po_result",
                    # Mapped to "PURCHASE ORDER NO"
                    "po_no": str(getattr(p, 'purchase_order_no', 'N/A')),
                    # Mapped to "PURCHASE ORDER DATE"
                    "date": str(getattr(p, 'purchase_order_date', 'N/A')),
                    # Grabbing the joined supplier name
                    "supplier": str(getattr(p, 'supplier_name', 'Unknown Supplier')), 
                    # Mapped to amounts in your screenshot
                    "total": float(getattr(p, 'total_amount', 0)),
                    "advance": float(getattr(p, 'advance', 0)),
                    "balance": float(getattr(p, 'balance_amount', 0))
                })
            return {"results": results}


    # 📁 STEP 5: PROJECT LOGIC
    if intent == "project_search":
        ai_target = ai_data.get("search_target", "").strip()
        
        if not ai_target:
            query = text("SELECT * FROM projects ORDER BY id DESC LIMIT 5")
            proj_results = db.execute(query).fetchall()
        else:
            # Mapped to the "NAME" column in your screenshot
            query = text("SELECT * FROM projects WHERE LOWER(name) LIKE :q ORDER BY id DESC LIMIT 5")
            proj_results = db.execute(query, {"q": f"%{ai_target.lower()}%"}).fetchall()

        if proj_results:
            results = []
            for p in proj_results:
                results.append({
                    "type": "project_result",
                    # Mapped to "NAME"
                    "project_name": str(getattr(p, 'name', 'Unknown')),
                    # Mapped to "PROJECT STATUS" and "PRIORITY"
                    "category": f"{getattr(p, 'project_status', 'New')} / {getattr(p, 'priority', 'Normal')}",
                    "amount": float(getattr(p, 'estimated_amount', getattr(p, 'budget', 0))), # Kept as fallback
                    # Mapped to "Start Date" and "End Date" inside PROJECT DATE
                    "start_date": str(getattr(p, 'start_date', 'N/A')),
                    "end_date": str(getattr(p, 'end_date', 'N/A')),
                    "client": str(getattr(p, 'client', 'Internal')) 
                })
            return {"results": results}

    # 🏭 STEP 6: EXPLICIT SUPPLIER REQUESTS
    supplier_keywords = ["supplier", "vendor", "party", "company", "active", "suplier", "supllier", "directory"]
    is_explicit_supplier = any(k in low_q for k in supplier_keywords) or intent in ["supplier_search", "supplier_list"]
    
    if is_explicit_supplier:
        noise = r'\b(bhai|ki|hai|aaj|details|ka|ke|batao|do|show|me|supplier|suppliers|suplier|supllier|active|list|all|kon|directory)\b'
        clean_s = re.sub(noise, '', low_q).strip()
        clean_s = re.sub(r'[^\w\s-]', '', clean_s).strip()

        if not clean_s or len(clean_s) < 2:
            all_s = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers ORDER BY supplier_name ASC")).fetchall()
            return {"results": [{"type": "supplier_list", "message": "📋 Active Supplier Directory:", "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code})"} for s in all_s]}]}

        suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_name) LIKE :q"), {"q": f"%{clean_s}%"}).fetchall()
        
        if suppliers_found:
            supplier_output = []
            for s in suppliers_found:
                inv_items = db.execute(text("""
                    SELECT i.name, SUM(CASE WHEN LOWER(t.txn_type) = 'in' THEN t.quantity ELSE -t.quantity END) as current_stock
                    FROM inventories i JOIN stock_transactions t ON i.id = t.inventory_id
                    WHERE t.supplier_id = :sid GROUP BY i.id, i.name HAVING current_stock != 0
                """), {"sid": s.id}).fetchall()

                supplier_output.append({
                    "type": "result", 
                    "supplier": {
                        "id": s.id, "name": s.supplier_name, "code": s.supplier_code,
                        "email": getattr(s, 'email', None) or 'N/A', 
                        "gstin": getattr(s, 'gstin', None) or 'N/A',
                        "state": getattr(s, 'state', None) or 'N/A', 
                        "city": getattr(s, 'city', None) or 'N/A', 
                        "mobile": getattr(s, 'mobile', None) or 'N/A'
                    },
                    "items": [{"name": row.name, "stock": float(row.current_stock)} for row in inv_items]
                })
            return {"results": supplier_output}

    # 📦 STEP 7: INVENTORY PRIORITY GATE
    inv_output = []
    
    # 7.2 General Inventory Search (Fuzzy & Multi-Item)
    raw_targets = ai_data.get("specific_items", [])
    ai_exclusions = ["supplier", "suppliers", "details", "list", "all", "suplier", "suppler", "supllier", "vendor", "party", "po", "purchase order", "project"]
    search_targets = [t for t in raw_targets if str(t).lower() not in ai_exclusions]
    
    inv_noise = r'\b(chahiye|kya|ki|status|hai|aaj|what|is|the|stock|for|details|ka|ke|bata|batao|do|please|yaar|mujhe|of|show|me|our|item|kon|all)\b'
    clean_q = re.sub(inv_noise, '', low_q).strip()
    clean_q = re.sub(r'\b\d+\b', '', clean_q)
    clean_q = re.sub(r'\s+', ' ', clean_q).strip()
    
    # Split multi-item searches based on "and", "or", "aur", or commas
    if not search_targets: 
        if clean_q: 
            if re.search(r'\b(and|or|aur)\b|,', clean_q):
                search_targets = [x.strip() for x in re.split(r'\s+and\s+|\s+or\s+|\s+aur\s+|,', clean_q) if x.strip()]
            else:
                search_targets = [clean_q]
    
    seen_ids = set() 
    for target in search_targets:
        t_str = str(target).strip()
        if not t_str or len(t_str) < 2: continue
            
        inv_res = db.execute(text("""
            SELECT id, name, classification, placement FROM inventories 
            WHERE LOWER(name) LIKE :q OR id = :id_val LIMIT 10
        """), {
            "q": f"%{t_str}%", 
            "id_val": int(t_str) if t_str.isdigit() else -1
        }).fetchall()

        if not inv_res:
            all_inv = db.execute(text("SELECT id, name, classification, placement FROM inventories")).fetchall()
            inv_map = {}
            for i in all_inv:
                c_name = str(i.name).lower().strip()
                if c_name not in inv_map: inv_map[c_name] = []
                inv_map[c_name].append(i)
                
            # Cutoff 0.7 to prevent Supplier vs Inventory typos
            matches = difflib.get_close_matches(t_str, inv_map.keys(), n=5, cutoff=0.7)
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
            
            inv_output.append({
                "type": "result",
                "inventory": {
                    "id": inv.id, 
                    "name": inv.name, 
                    "classification": cls.upper() if cls else "N/A",
                    "placement": getattr(inv, 'placement', None) or "Not Assigned"
                },
                "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m + f + sf)
            })
            
        elif len(inv_res) > 1:
            inv_output.append({
                "type": "dropdown", "message": f"Select an item for '{target}':",
                "items": [{"id": i.id, "name": i.name} for i in inv_res]
            })

    if inv_output:
        return {"results": inv_output}

    # 🏭 STEP 8: SUPPLIER FALLBACK
    if len(low_q) > 2:
        all_s = db.execute(text("SELECT supplier_name FROM suppliers")).fetchall()
        s_names = [s.supplier_name.lower() for s in all_s]
        
        is_implicit_supplier = False
        if any(low_q in name for name in s_names):
            is_implicit_supplier = True
        elif difflib.get_close_matches(low_q, s_names, n=1, cutoff=0.6):
            is_implicit_supplier = True
            
        if is_implicit_supplier:
            suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_name) LIKE :q"), {"q": f"%{low_q}%"}).fetchall()
            if not suppliers_found:
                s_map = {s.supplier_name.lower(): s.supplier_name for s in all_s}
                matches = difflib.get_close_matches(low_q, s_map.keys(), n=1, cutoff=0.5)
                if matches:
                    suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_name) = :q"), {"q": matches[0]}).fetchall()
                    
            if suppliers_found:
                supplier_output = []
                for s in suppliers_found:
                    inv_items = db.execute(text("""
                        SELECT i.name, SUM(CASE WHEN LOWER(t.txn_type) = 'in' THEN t.quantity ELSE -t.quantity END) as current_stock
                        FROM inventories i JOIN stock_transactions t ON i.id = t.inventory_id
                        WHERE t.supplier_id = :sid GROUP BY i.id, i.name HAVING current_stock != 0
                    """), {"sid": s.id}).fetchall()

                    supplier_output.append({
                        "type": "result", 
                        "supplier": {
                            "id": s.id, "name": s.supplier_name, "code": s.supplier_code,
                            "email": getattr(s, 'email', None) or 'N/A', 
                            "gstin": getattr(s, 'gstin', None) or 'N/A',
                            "state": getattr(s, 'state', None) or 'N/A', 
                            "city": getattr(s, 'city', None) or 'N/A', 
                            "mobile": getattr(s, 'mobile', None) or 'N/A'
                        },
                        "items": [{"name": row.name, "stock": float(row.current_stock)} for row in inv_items]
                    })
                return {"results": supplier_output}

    # 🆘 STEP 9: TRUE RANDOM INVENTORY SUGGESTIONS
    all_suggestions = db.execute(text("SELECT id, name FROM inventories")).fetchall()
    if all_suggestions:
        suggestions = random.sample(all_suggestions, min(5, len(all_suggestions)))
        return {"results": [{
            "type": "dropdown",
            "message": "I couldn't find exactly what you typed. Did you mean one of these?",
            "items": [{"id": s.id, "name": s.name} for s in suggestions]
        }]}
        
    return {"results": [{"message": "I couldn't find that in the database."}]}