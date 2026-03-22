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
    
    # 🚀 FIX 1: BETTER ID SEARCH (Runs first, very fast)
    # This catches "718", "#718", or "item 718"
    id_match = re.search(r'(\d+)', low_q)
    if id_match:
        target_id = int(id_match.group(1))
        inv = db.execute(text("SELECT id, name, classification FROM inventories WHERE id = :id"), {"id": target_id}).fetchone()
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
                "inventory": {"id": inv.id, "name": inv.name, "classification": cls.upper()},
                "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m + f + sf)
            }]}

    # 🚀 STEP 2: AI INTENT
    ai_data = ask_ollama(raw_q, getattr(request, "history", []))
    intent = ai_data.get("intent", "search")
    
    if intent == "chat" and "message" in ai_data:
        return {"results": [{"type": "chat", "message": ai_data["message"]}]}

    # 📊 STEP 2.5: MANAGER ANALYTICS (Fast Mode)
    if intent == "analytics" or any(x in low_q for x in ["low stock", "kam stock", "highest stock"]):
        all_inv = db.execute(text("SELECT id, name, classification FROM inventories")).fetchall()
        all_txns = db.execute(text("SELECT inventory_id, txn_type, quantity FROM stock_transactions")).fetchall()
        stock_map = {inv.id: {"Name": inv.name, "Stock": 0.0, "Category": inv.classification or "N/A"} for inv in all_inv}
        for t in all_txns:
            if t.inventory_id in stock_map:
                qty = float(t.quantity or 0)
                if str(t.txn_type).lower() == "in": stock_map[t.inventory_id]["Stock"] += qty
                else: stock_map[t.inventory_id]["Stock"] -= qty
        stock_data = list(stock_map.values())
        if "high" in low_q or ai_data.get("report_type") == "high_stock":
            stock_data.sort(key=lambda x: x["Stock"], reverse=True)
            title = "📈 Top 10 Highest Stock Items"
        else:
            stock_data.sort(key=lambda x: x["Stock"])
            title = "📉 Top 10 Lowest Stock Items"
        return {"results": [{"type": "analytics_chart", "title": title, "chart_type": "bar", "data": stock_data[:10]}]}

    final_output = []

    # 🚀 FIX 2: IMPROVED SUPPLIER LOGIC (Shows "All" if asked)
    is_supplier_intent = any(k in low_q for k in ["supplier", "vendor", "party", "kon kon", "list", "details", "sup-"])
    
    if is_supplier_intent:
        # If they ask "who" or "list", show a larger directory (up to 20)
        if any(x in low_q for x in ["kon kon", "list", "all", "sare"]):
            suppliers = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers ORDER BY supplier_name ASC LIMIT 20")).fetchall()
            return {"results": [{
                "type": "supplier_list",
                "message": "📋 Mewar ERP Supplier Directory:",
                "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code or 'N/A'})"} for s in suppliers]
            }]}
        
        # Otherwise, try to find a specific one
        clean_s = re.sub(r'\b(supplier|details|kon|hai|batao|dikhao|show|me)\b', '', low_q).strip()
        if clean_s:
            s_res = db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_name) LIKE :q OR LOWER(supplier_code) LIKE :q LIMIT 5"), {"q": f"%{clean_s}%"}).fetchall()
            if s_res:
                for s in s_res:
                    final_output.append({"type": "result", "supplier": {"id": s.id, "name": s.supplier_name, "code": s.supplier_code, "email": s.email or "N/A", "gstin": s.gstin or "N/A"}})
                return {"results": final_output}

    # 🚀 STEP 4: INVENTORY SEARCH (With Typo Protection)
    raw_targets = ai_data.get("specific_items", [])
    search_targets = [t for t in raw_targets if not str(t).lower().startswith("suppl") and str(t).lower() not in ["kon", "hai", "details"]]
    
    if not search_targets and not is_supplier_intent:
        clean_q = re.sub(r'\b(chahiye|kya|hai|show|me|stock|item|inventory)\b', '', low_q).strip()
        if len(clean_q) > 1: search_targets = [clean_q]

    for target in search_targets:
        inv_res = db.execute(text("SELECT id, name, classification FROM inventories WHERE LOWER(name) LIKE :q LIMIT 10"), {"q": f"%{target}%"}).fetchall()
        if not inv_res:
            # Fuzzy match only if no direct LIKE match
            all_names = db.execute(text("SELECT name FROM inventories")).fetchall()
            matches = difflib.get_close_matches(target, [r.name.lower() for r in all_names], n=3, cutoff=0.5)
            if matches:
                inv_res = db.execute(text("SELECT id, name, classification FROM inventories WHERE LOWER(name) IN :m"), {"m": tuple(matches)}).fetchall()

        for inv in inv_res:
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            m, f, sf = 0, 0, 0
            cls = (inv.classification or "").lower()
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

    if final_output:
        return {"results": final_output}
    
    # Final Fallback
    return {"results": [{"type": "chat", "message": "I couldn't find that ID, Item, or Supplier. Try searching by name (e.g., 'Bearing') or asking for 'low stock'."}]}