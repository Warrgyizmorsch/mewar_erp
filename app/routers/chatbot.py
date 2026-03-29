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
    
    # 🎯 STEP 1: ID-ONLY FAST-TRACK (Inventory Priority - with Placement)
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
                    "id": inv.id, "name": inv.name, "classification": cls.upper(), 
                    "placement": getattr(inv, 'placement', 'Not Assigned')
                },
                "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m + f + sf)
            }]}

    # 🚀 STEP 2: AI INTENT DETECTION
    ai_data = ask_ollama(raw_q, getattr(request, "history", []))
    intent = ai_data.get("intent", "search")
    
    if intent == "chat" and "message" in ai_data:
        return {"results": [{"type": "chat", "message": ai_data["message"]}]}

    # 📊 MANAGER ANALYTICS
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

    final_output = []

    # 🏭 STEP 3: PROFESSIONAL SUPPLIER LOGIC (The Smart Gate)
    suppliers_found = []
    supplier_keywords = ["supplier", "vendor", "party", "company", "active", "suplier", "supllier"]
    
    is_supplier_intent = any(k in low_q for k in supplier_keywords) or intent in ["supplier_search", "supplier_list"]
    
    if not is_supplier_intent and len(low_q) > 2:
        all_s = db.execute(text("SELECT supplier_name FROM suppliers")).fetchall()
        s_names = [s.supplier_name.lower() for s in all_s]
        if any(low_q in name for name in s_names):
            is_supplier_intent = True
        elif difflib.get_close_matches(low_q, s_names, n=1, cutoff=0.6):
            is_supplier_intent = True

    exact_supplier = db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_name) = :q LIMIT 1"), {"q": low_q}).fetchall()
    if exact_supplier:
        is_supplier_intent = True

    if is_supplier_intent:
        noise = r'\b(bhai|ki|hai|aaj|details|ka|ke|batao|do|show|me|supplier|suppliers|suplier|supllier|active|list|all|kon|directory)\b'
        clean_s = re.sub(noise, '', low_q).strip()
        clean_s = re.sub(r'[^\w\s-]', '', clean_s).strip()

        if not clean_s or len(clean_s) < 2:
            all_s = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers ORDER BY supplier_name ASC")).fetchall()
            return {"results": [{"type": "supplier_list", "message": "📋 Active Supplier Directory:", "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code})"} for s in all_s]}]}

        suppliers_found = exact_supplier if exact_supplier else db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_name) LIKE :q"), {"q": f"%{clean_s}%"}).fetchall()
        
        if not suppliers_found and len(clean_s) > 2:
            all_s = db.execute(text("SELECT id, supplier_name FROM suppliers")).fetchall()
            s_map = {s.supplier_name.lower(): s.id for s in all_s}
            matches = difflib.get_close_matches(clean_s, s_map.keys(), n=1, cutoff=0.5)
            if matches:
                suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE id = :id"), {"id": s_map[matches[0]]}).fetchall()

        if suppliers_found:
            for s in suppliers_found:
                inv_items = db.execute(text("""
                    SELECT i.name, SUM(CASE WHEN LOWER(t.txn_type) = 'in' THEN t.quantity ELSE -t.quantity END) as current_stock
                    FROM inventories i JOIN stock_transactions t ON i.id = t.inventory_id
                    WHERE t.supplier_id = :sid GROUP BY i.id, i.name HAVING current_stock != 0
                """), {"sid": s.id}).fetchall()

                final_output.append({
                    "type": "result", 
                    "supplier": {
                        "id": s.id, "name": s.supplier_name, "code": s.supplier_code,
                        "email": getattr(s, 'email', 'N/A') if getattr(s, 'email', None) else 'N/A', 
                        "gstin": getattr(s, 'gstin', 'N/A') if getattr(s, 'gstin', None) else 'N/A',
                        "state": getattr(s, 'state', 'N/A') if getattr(s, 'state', None) else 'N/A', 
                        "city": getattr(s, 'city', 'N/A') if getattr(s, 'city', None) else 'N/A', 
                        "mobile": getattr(s, 'mobile', 'N/A') if getattr(s, 'mobile', None) else 'N/A'
                    },
                    "items": [{"name": row.name, "stock": float(row.current_stock)} for row in inv_items]
                })

    # 🧾 STEP 3.5: PURCHASE ORDER (PO) LOGIC
    po_keywords = ["po", "purchase order", "order", "mhel/po"]
    is_po_intent = any(k in low_q for k in po_keywords) or intent == "po_search"

    if is_po_intent:
        noise = r'\b(bhai|ki|hai|dikhao|show|me|purchase|order|po|details|ka|ke|latest)\b'
        clean_po = re.sub(noise, '', low_q).strip()
        
        if not clean_po or len(clean_po) < 2:
            query = text("""
                SELECT p.purchase_order_date, p.purchase_order_no, s.supplier_name, p.total_amount, p.advance, p.balance_amount
                FROM purchase_orders p
                LEFT JOIN suppliers s ON p.supplier_id = s.id
                ORDER BY p.purchase_order_date DESC LIMIT 5
            """)
            po_results = db.execute(query).fetchall()
        else:
            query = text("""
                SELECT p.purchase_order_date, p.purchase_order_no, s.supplier_name, p.total_amount, p.advance, p.balance_amount
                FROM purchase_orders p
                LEFT JOIN suppliers s ON p.supplier_id = s.id
                WHERE LOWER(p.purchase_order_no) LIKE :q OR LOWER(s.supplier_name) LIKE :q
                ORDER BY p.purchase_order_date DESC LIMIT 5
            """)
            po_results = db.execute(query, {"q": f"%{clean_po}%"}).fetchall()

        if po_results:
            results = []
            for p in po_results:
                results.append({
                    "type": "po_result",
                    "po_no": p.purchase_order_no,
                    "date": str(p.purchase_order_date),
                    "supplier": p.supplier_name or "Unknown",
                    "total": float(p.total_amount or 0),
                    "advance": float(p.advance or 0),
                    "balance": float(p.balance_amount or 0)
                })
            return {"results": results}

    # 📁 STEP 3.6: PROJECT LOGIC
    project_keywords = ["project", "projects"]
    is_project_intent = any(k in low_q for k in project_keywords) or intent == "project_search"

    if is_project_intent:
        noise = r'\b(bhai|ki|hai|dikhao|show|me|project|projects|details|ka|ke|latest)\b'
        clean_proj = re.sub(noise, '', low_q).strip()
        
        if not clean_proj or len(clean_proj) < 2:
            query = text("SELECT * FROM projects ORDER BY start_date DESC LIMIT 5")
            proj_results = db.execute(query).fetchall()
        else:
            query = text("SELECT * FROM projects WHERE LOWER(project_name) LIKE :q ORDER BY start_date DESC LIMIT 5")
            proj_results = db.execute(query, {"q": f"%{clean_proj}%"}).fetchall()

        if proj_results:
            results = []
            for p in proj_results:
                results.append({
                    "type": "project_result",
                    "project_name": getattr(p, 'project_name', 'Unknown Project'),
                    "category": getattr(p, 'category', 'N/A'),
                    "amount": float(getattr(p, 'estimated_amount', 0)),
                    "start_date": str(getattr(p, 'start_date', 'N/A')),
                    "end_date": str(getattr(p, 'end_date', 'N/A')),
                    "client": str(getattr(p, 'client', 'N/A')) 
                })
            return {"results": results}

    # 🎯 STEP 4.1: EXACT MATCH OVERRIDE (Fixes number stripping loop)
    exact_inv = db.execute(text("SELECT id, name, classification, placement FROM inventories WHERE LOWER(name) = :q LIMIT 1"), {"q": low_q}).fetchone()
    
    if exact_inv:
        txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": exact_inv.id}).fetchall()
        m, f, sf = 0, 0, 0
        cls = str(exact_inv.classification).lower() if exact_inv.classification else ""
        for t in txns:
            val = float(t.quantity or 0) * (1 if str(t.txn_type).lower() == "in" else -1)
            if "machining" in cls: m += val
            elif "semi" in cls: sf += val
            else: f += val
        
        final_output.append({
            "type": "result",
            "inventory": {
                "id": exact_inv.id, "name": exact_inv.name, "classification": cls.upper(),
                "placement": getattr(exact_inv, 'placement', 'Not Assigned')
            },
            "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m + f + sf)
        })
        return {"results": final_output} 

    # 🚀 STEP 4.2: GENERAL INVENTORY SEARCH (Fuzzy & Multi-Item)
    raw_targets = ai_data.get("specific_items", [])
    
    ai_exclusions = ["supplier", "suppliers", "details", "list", "all", "suplier", "suppler", "supllier", "vendor", "party", "po", "purchase order", "project"]
    search_targets = [t for t in raw_targets if str(t).lower() not in ai_exclusions]
    
    inv_noise = r'\b(chahiye|kya|ki|status|hai|aaj|what|is|the|stock|for|details|ka|ke|bata|batao|do|please|yaar|mujhe|of|show|me|our|item|supplier|suppliers|suplier|suppler|supllier|vendor|party|kon|list|all|project|po)\b'
    clean_q = re.sub(inv_noise, '', low_q).strip()
    clean_q = re.sub(r'\b\d+\b', '', clean_q)
    clean_q = re.sub(r'\s+', ' ', clean_q).strip()
    
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
                "inventory": {
                    "id": inv.id, "name": inv.name, "classification": cls.upper(),
                    "placement": getattr(inv, 'placement', 'Not Assigned')
                },
                "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m + f + sf)
            })
            
        elif len(inv_res) > 1:
            final_output.append({
                "type": "dropdown", "message": f"Select an item for '{target}':",
                "items": [{"id": i.id, "name": i.name} for i in inv_res]
            })

    # 🎉 RETURN ALL GATHERED DATA AT ONCE
    if final_output:
        return {"results": final_output}

    # 🆘 FALLBACK 2: TRUE RANDOM INVENTORY SUGGESTIONS
    all_suggestions = db.execute(text("SELECT id, name FROM inventories")).fetchall()
    
    if all_suggestions:
        suggestions = random.sample(all_suggestions, min(5, len(all_suggestions)))
        return {"results": [{
            "type": "dropdown",
            "message": "I couldn't find exactly what you typed. Did you mean one of these?",
            "items": [{"id": s.id, "name": s.name} for s in suggestions]
        }]}
        
    return {"results": [{"message": "I couldn't find that in the database."}]}