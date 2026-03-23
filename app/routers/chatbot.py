from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.database import get_db
from app.schemas.chat import ChatRequest
from app.dependencies import get_current_user
import re
import difflib
from app.services.ollama_engine import ask_ollama

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

@router.post("/")
def chatbot(request: ChatRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    raw_q = request.query.strip()
    low_q = raw_q.lower()
    
    # 🎯 STEP 1: FAST-TRACK (EXACT ID & SUPPLIER CODE)
    # ---------------------------------------------------------
    # Check for Supplier Code (e.g., sup-100, sup100)
    sup_match = re.search(r'sup[- \s]?(\d+)', low_q)
    if sup_match:
        num = sup_match.group(1)
        supplier = db.execute(text("""
            SELECT * FROM suppliers 
            WHERE LOWER(supplier_code) IN (:c1, :c2) OR id = :id LIMIT 1
        """), {"c1": f"sup-{num}", "c2": f"sup{num}", "id": int(num)}).fetchone()
        
        if supplier:
            return {"results": [{
                "type": "result", 
                "supplier": {"id": supplier.id, "name": supplier.supplier_name, "code": supplier.supplier_code, "email": supplier.email or "N/A", "gstin": supplier.gstin or "N/A"}
            }]}

    # Check for exact Inventory ID (e.g., 718)
    if low_q.isdigit():
        inv = db.execute(text("SELECT id, name, classification FROM inventories WHERE id = :id"), {"id": int(low_q)}).fetchone()
        if inv:
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            m, f, sf = 0, 0, 0
            cls = (inv.classification or "").lower()
            for t in txns:
                val = float(t.quantity or 0) * (1 if str(t.txn_type).lower() == "in" else -1)
                if "machining" in cls: m += val
                elif "semi" in cls: sf += val
                else: f += val
            return {"results": [{"type": "result", "inventory": {"id": inv.id, "name": inv.name, "classification": (inv.classification or "N/A").upper()}, "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m+f+sf)}]}

    # 🚀 STEP 2: AI INTENT & ANALYTICS
    # ---------------------------------------------------------
    ai_data = ask_ollama(raw_q, getattr(request, "history", []))
    intent = ai_data.get("intent", "search")

    # Fast Analytics (Low/High Stock)
    if intent == "analytics" or any(x in low_q for x in ["low stock", "kam stock", "highest stock"]):
        all_inv = db.execute(text("SELECT id, name, classification FROM inventories")).fetchall()
        all_txns = db.execute(text("SELECT inventory_id, txn_type, quantity FROM stock_transactions")).fetchall()
        stock_map = {inv.id: {"Name": inv.name, "Stock": 0.0} for inv in all_inv}
        for t in all_txns:
            if t.inventory_id in stock_map:
                qty = float(t.quantity or 0)
                if str(t.txn_type).lower() == "in": stock_map[t.inventory_id]["Stock"] += qty
                else: stock_map[t.inventory_id]["Stock"] -= qty
        stock_data = list(stock_map.values())
        if "high" in low_q:
            stock_data.sort(key=lambda x: x["Stock"], reverse=True)
            title = "📈 Top 10 Highest Stock Items"
        else:
            stock_data.sort(key=lambda x: x["Stock"])
            title = "📉 Top 10 Lowest Stock Items"
        return {"results": [{"type": "analytics_chart", "title": title, "chart_type": "bar", "data": stock_data[:10]}]}

    # 🚀 STEP 3: MULTI-ITEM ACCUMULATOR & SMART UI
    # ---------------------------------------------------------
    final_output = []
    seen_ids = set()

    # Determine what to search for
    raw_targets = ai_data.get("specific_items", [])
    search_targets = [t for t in raw_targets if not str(t).lower().startswith("suppl") and str(t).lower() not in ["kon", "hai", "details"]]
    
    if not search_targets:
        clean_q = re.sub(r'\b(chahiye|hai|batao|dikhao|show|me|stock|and|aur)\b', '', low_q).strip()
        search_targets = re.split(r',| and | aur ', clean_q) if any(x in clean_q for x in [",", " and ", " aur "]) else [clean_q]

    for target in search_targets:
        target = target.strip()
        if len(target) < 2: continue
        
        # Search DB
        inv_res = db.execute(text("SELECT id, name, classification FROM inventories WHERE LOWER(name) LIKE :q LIMIT 11"), {"q": f"%{target.lower()}%"}).fetchall()
        
        if not inv_res:
            all_i = db.execute(text("SELECT name FROM inventories")).fetchall()
            matches = difflib.get_close_matches(target, [i.name.lower() for i in all_i], n=1, cutoff=0.5)
            if matches:
                inv_res = db.execute(text("SELECT id, name, classification FROM inventories WHERE LOWER(name) = :n"), {"n": matches[0]}).fetchall()

        # 💎 SMART UI LOGIC GATE
        if len(inv_res) == 1:
            inv = inv_res[0]
            if inv.id in seen_ids: continue
            seen_ids.add(inv.id)
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            m, f, sf = 0, 0, 0
            for t in txns:
                val = float(t.quantity or 0) * (1 if str(t.txn_type).lower() == "in" else -1)
                cls = (inv.classification or "").lower()
                if "machining" in cls: m += val
                elif "semi" in cls: sf += val
                else: f += val
            final_output.append({"type": "result", "inventory": {"id": inv.id, "name": inv.name, "classification": (inv.classification or "N/A").upper()}, "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m+f+sf)})
        
        elif 1 < len(inv_res) <= 10:
            final_output.append({"type": "dropdown", "message": f"Found multiple items for '{target}':", "items": [{"id": i.id, "name": i.name} for i in inv_res]})
        
        elif len(inv_res) > 10:
            final_output.append({"type": "chat", "message": f"Too many matches for '{target}'. Please be more specific (e.g. 'Bearing 6205')."})

    # 🚀 STEP 4: SUPPLIER DIRECTORY FALLBACK
    # ---------------------------------------------------------
    if any(x in low_q for x in ["supplier", "vendor", "kon kon"]):
        if not final_output:
            suppliers = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers LIMIT 10")).fetchall()
            return {"results": [{"type": "supplier_list", "message": "📋 Supplier Directory:", "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code})"} for s in suppliers]}]}

    if final_output:
        return {"results": final_output}

    return {"results": [{"type": "chat", "message": "I couldn't find that. Try an ID (718), a Code (sup-100), or a name (Bearing)."}]}