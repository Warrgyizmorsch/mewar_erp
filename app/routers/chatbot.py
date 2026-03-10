from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.database import get_db
from app.schemas.chat import ChatRequest
from app.dependencies import get_current_user
import re

from app.services.ollama_engine import ask_ollama
from rapidfuzz import process, fuzz

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

@router.post("/")
def chatbot(request: ChatRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    raw_q = request.query.strip()
    low_q = raw_q.lower()

    # =========================================================
    # 1. SMART GREETING INTERCEPTOR
    # =========================================================
    greeting_phrases = ["hi", "hello", "hey", "namaste", "namaskar", "ram ram", "khamma ghani", "good morning", "good evening"]
    clean_greet = re.sub(r'\b(bhai|sir|ji|bro|ai|bot|yaar|please)\b', '', low_q).strip()
    
    if clean_greet in greeting_phrases or low_q in greeting_phrases:
        return {"message": "Ram Ram! 🙏 I am the Mewar ERP Intelligence Layer. Kya dekhna hai aaj? (What shall we look for today?)"}

    # =========================================================
    # 2. AI INTENT
    # =========================================================
    chat_history = getattr(request, "history", []) 
    ai_data = ask_ollama(raw_q, chat_history)
    intent = ai_data.get("intent", "search")
    specific = ai_data.get("specific_items", [])
    general = ai_data.get("general_categories", [])

    # =========================================================
    # FEATURE 1: ANALYTICAL
    # =========================================================
    if intent == "analytical":
        target = specific[0] if specific else (general[0] if general else None)
        if target:
            results = db.execute(text("""
                SELECT s.supplier_name, i.name as item_name, 
                       SUM(CASE WHEN LOWER(t.txn_type) = 'in' THEN t.quantity ELSE -t.quantity END) as total_stock
                FROM stock_transactions t
                JOIN suppliers s ON t.supplier_id = s.id
                JOIN inventories i ON t.inventory_id = i.id
                WHERE LOWER(i.name) LIKE LOWER(:q)
                GROUP BY s.id, i.id
                HAVING SUM(CASE WHEN LOWER(t.txn_type) = 'in' THEN t.quantity ELSE -t.quantity END) > 0
                ORDER BY total_stock DESC LIMIT 5
            """), {"q": f"%{target}%"}).fetchall()

            if results:
                return {
                    "type": "analytical_result",
                    "message": f"📊 Stock comparison for '{target}':",
                    "data": [{"supplier": r.supplier_name, "item": r.item_name, "stock": float(r.total_stock)} for r in results]
                }

    # =========================================================
    # FEATURE 2: SUPPLIER DIRECTORY & SMART FALLBACK
    # =========================================================
    supplier_keywords = ["supplier", "sup-", "email", "gstin", "phone", "contact"]
    
    if intent in ["supplier_list", "supplier_search"] or any(k in low_q for k in supplier_keywords):
        
        if intent == "supplier_list" or "all " in low_q or "list" in low_q:
            suppliers = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers LIMIT 50")).fetchall()
            return {
                "type": "supplier_list",
                "message": "📋 Active Suppliers Directory:",
                "suppliers": [{"id": s.id, "name": s.supplier_name, "code": s.supplier_code} for s in suppliers]
            }

        supplier = None

        if "who" in low_q or "their" in low_q:
            for msg in reversed(chat_history):
                if msg.get("role") == "user":
                    past_digits = re.findall(r'\b\d+\b', msg.get("content", ""))
                    if past_digits:
                        last_id = int(past_digits[-1])
                        sup_row = db.execute(text("""
                            SELECT s.* FROM suppliers s 
                            JOIN stock_transactions t ON s.id = t.supplier_id 
                            WHERE t.inventory_id = :id LIMIT 1
                        """), {"id": last_id}).fetchone()
                        if sup_row: supplier = sup_row
                        break

        if not supplier:
            all_suppliers = db.execute(text("SELECT * FROM suppliers")).fetchall()
            best_score = 0
            
            for sup in all_suppliers:
                name = str(sup.supplier_name).lower()
                code = str(sup.supplier_code).lower()
                
                if name.split()[0] in low_q or code in low_q:
                    supplier = sup
                    break
                    
                score = fuzz.token_set_ratio(low_q, name)
                if score > best_score:
                    best_score = score
                    if score >= 70: supplier = sup

        if not supplier:
            suppliers = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers LIMIT 50")).fetchall()
            return {
                "type": "supplier_list",
                "message": "🤷‍♂️ You didn't mention which company! Here is our supplier directory. Who are you looking for?",
                "suppliers": [{"id": s.id, "name": s.supplier_name, "code": s.supplier_code} for s in suppliers]
            }

        items = []
        finish_stock, semi_finish_stock = 0, 0
        inv_rows = db.execute(text("SELECT id, name, classification FROM inventories")).fetchall()
        for inv in inv_rows:
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :inv_id AND supplier_id = :sup_id"), {"inv_id": inv.id, "sup_id": supplier.id}).fetchall()
            total = sum(float(t.quantity or 0) if str(t.txn_type).lower() == "in" else -float(t.quantity or 0) for t in txns)
            if total != 0:
                items.append({"inventory_id": inv.id, "name": inv.name, "stock": total})
                c_type = str(inv.classification).lower() if inv.classification else "finish"
                if "semi" in c_type: semi_finish_stock += total
                else: finish_stock += total

        return {
            "type": "result", "message": f"Details for {supplier.supplier_name}:",
            "supplier": {"id": supplier.id, "name": supplier.supplier_name, "code": supplier.supplier_code, "email": supplier.email, "gstin": supplier.gstin},
            "finish_stock": finish_stock, "semi_finish_stock": semi_finish_stock, "items": items
        }

    # =========================================================
    # FEATURE 3: INVENTORY SEARCH (Now with Placements & Dimensions)
    # =========================================================
    final_output = []
    filtered_general = [g for g in general if not any(g in s for s in specific)]
    search_tasks = [{"name": p, "is_specific": True} for p in specific] + [{"name": p, "is_specific": False} for p in filtered_general]
    if not search_tasks: search_tasks = [{"name": low_q, "is_specific": False}]

    for task in search_tasks:
        target = str(task["name"]).strip().lower()
        is_specific = task["is_specific"]
        inventories = []
        
        clean_id = target.replace("id ", "").replace("#", "").strip()
        if clean_id.isdigit():
            inventories = db.execute(text("SELECT id, name, classification, unit, placement, height, width, thickness FROM inventories WHERE id = :id"), {"id": int(clean_id)}).fetchall()
            if inventories: is_specific = True

        if not inventories:
            inventories = db.execute(text("SELECT id, name, classification, unit, placement, height, width, thickness FROM inventories WHERE LOWER(name) REGEXP :q ORDER BY name LIMIT 15"), {"q": rf"\b{re.escape(target)}\b"}).fetchall()

        if not inventories:
            all_names = [r.name for r in db.execute(text("SELECT name FROM inventories")).fetchall()]
            best_match = process.extractOne(target, all_names, scorer=fuzz.WRatio)
            if best_match and best_match[1] >= 85:
                inventories = db.execute(text("SELECT id, name, classification, unit, placement, height, width, thickness FROM inventories WHERE name = :n"), {"n": best_match[0]}).fetchall()
                is_specific = True

        if len(inventories) > 1 and not is_specific:
            final_output.append({"product_requested": target, "type": "dropdown", "message": f"I found several matching '{target}':", "items": [{"id": i.id, "name": i.name} for i in inventories]})
        elif inventories:
            inv = inventories[0]
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            total = sum(float(t.quantity or 0) if str(t.txn_type).lower() == "in" else -float(t.quantity or 0) for t in txns)
            
            final_output.append({
                "type": "result", 
                "inventory": {
                    "id": inv.id, 
                    "name": inv.name, 
                    "classification": (inv.classification or "FINISH").upper(),
                    "unit": inv.unit or "NOS",
                    "placement": inv.placement or "N/A",
                    "height": inv.height or 0,
                    "width": inv.width or 0,
                    "thickness": inv.thickness or 0
                }, 
                "stock": {"total": total}
            })
        else:
            all_rows = db.execute(text("SELECT name FROM inventories")).fetchall()
            closest = process.extract(target, [r[0] for r in all_rows], limit=5)
            final_output.append({"type": "suggestion", "message": f"❌ '{target}' not found.", "suggestions": [m[0] for m in closest if m[1] > 50]})

    return {"results": final_output}