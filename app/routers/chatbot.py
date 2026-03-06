from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.database import get_db
from app.schemas.chat import ChatRequest
from app.dependencies import get_current_user

# --- IMPORT OLLAMA ENGINE & FUZZY TOOLS ---
from app.services.ollama_engine import ask_ollama
from rapidfuzz import process, fuzz

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

GREETINGS = ["hi", "hello", "hey", "namaste", "namaskar", "ram ram"]

@router.post("/")
def chatbot(request: ChatRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    raw_q = request.query.strip()
    low_q = raw_q.lower()

    # =========================================================
    # 1. GREETING CHECK
    # =========================================================
    words = low_q.split()
    if any(g in words for g in GREETINGS) and len(words) <= 2:
        return {"message": "Hello! 🙏 I am the Mewar ERP AI. How can I help you today?"}

    # =========================================================
    # 2. SMART AI UNDERSTANDING (Gemma 3)
    # =========================================================
    ai_data = ask_ollama(raw_q)
    intent = ai_data.get("intent", "search")
    
    general = ai_data.get("general_categories", [])
    specific = ai_data.get("specific_items", [])

    # =========================================================
    # FEATURE 1: SUPPLIER LIST & SEARCH
    # =========================================================
    if intent == "supplier_list" or low_q == "supplier":
        suppliers = db.execute(text("SELECT id, supplier_name FROM suppliers LIMIT 50")).fetchall()
        return {
            "type": "supplier_list",
            "message": "Active Suppliers Directory:",
            "suppliers": [{"id": s.id, "name": s.supplier_name} for s in suppliers]
        }

    if intent == "supplier_search" or low_q.startswith("supplier "):
        q = specific[0] if specific else (general[0] if general else low_q.replace("supplier", "").strip())
        smart_q = q.replace(" ", "%") # Smart Wildcard for supplier names
        
        suppliers = db.execute(text("""
            SELECT id, supplier_name, supplier_code FROM suppliers 
            WHERE LOWER(supplier_name) LIKE LOWER(:q) OR LOWER(supplier_code) LIKE LOWER(:q)
            LIMIT 10
        """), {"q": f"%{smart_q}%"}).fetchall()

        if len(suppliers) > 1:
            return {
                "type": "dropdown",
                "items": [{"id": s.id, "name": s.supplier_name, "code": s.supplier_code} for s in suppliers]
            }
        
        if not suppliers:
            return {"message": f"Supplier '{q}' not found."}

        # --- GET SUPPLIER INVENTORY STOCK ---
        supplier = suppliers[0]
        items = []
        inv_rows = db.execute(text("SELECT id, name FROM inventories")).fetchall()
        
        for inv in inv_rows:
            txns = db.execute(text("""
                SELECT txn_type, quantity FROM stock_transactions 
                WHERE inventory_id = :inv_id AND supplier_id = :sup_id
            """), {"inv_id": inv.id, "sup_id": supplier.id}).fetchall()
            
            total = sum(float(t.quantity or 0) if str(t.txn_type).lower() == "in" else -float(t.quantity or 0) for t in txns)
            if total != 0:
                items.append({"inventory_id": inv.id, "name": inv.name, "stock": total})

        return {
            "type": "result",
            "supplier": {"id": supplier.id, "name": supplier.supplier_name},
            "items": items
        }

    # =========================================================
    # FEATURE 2: SMART INVENTORY SEARCH (Multi-Item & Hindi)
    # =========================================================
    final_output = []
    
    search_tasks = [{"name": p, "is_specific": False} for p in general] + \
                   [{"name": p, "is_specific": True} for p in specific]

    if not search_tasks:
        search_tasks = [{"name": low_q, "is_specific": False}]

    for task in search_tasks:
        raw_target = str(task["name"]).strip().lower()
        is_specific = task["is_specific"]

        # Final safety net for filler words in case AI missed them
        filler_words = ["mujhe", "chahiye", "dikhao", "kya", "hai", "dikha", "do", "i", "want", "show"]
        target_words = [w for w in raw_target.split() if w not in filler_words]
        target = " ".join(target_words) if target_words else raw_target

        # 🚀 SMART WILDCARD LOGIC: Changes "bearing 2216" to "%bearing%2216%"
        smart_target = target.replace(" ", "%")

        limit_val = 1 if is_specific else 15 
        inventories = db.execute(text("""
            SELECT id, name, classification 
            FROM inventories WHERE LOWER(name) LIKE LOWER(:q) 
            ORDER BY name LIMIT :limit
        """), {"q": f"%{smart_target}%", "limit": limit_val}).fetchall()

        if len(inventories) > 1 and not is_specific:
            # 🟢 Case A: General Dropdown
            final_output.append({
                "product_requested": target,
                "type": "dropdown",
                "message": f"I found several matching '{target}'. Which one are you looking for?",
                "items": [{"id": i.id, "name": i.name} for i in inventories]
            })

        elif len(inventories) >= 1:
            # 🔵 Case B: Specific Direct Result
            inv = inventories[0]
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            
            total = sum(float(t.quantity or 0) if str(t.txn_type).lower() == "in" else -float(t.quantity or 0) for t in txns)
            
            final_output.append({
                "type": "result",
                "inventory": {"id": inv.id, "name": inv.name, "classification": (inv.classification or "FINISH").upper()},
                "stock": {"total": total}
            })

        else:
            # 🔴 Case C: Spell Check / Suggestions
            all_rows = db.execute(text("SELECT name FROM inventories")).fetchall()
            names = [r[0] for r in all_rows]
            
            # Using RapidFuzz to find the closest matches even if spelled terribly
            closest = process.extract(target, names, limit=5)
            
            final_output.append({
                "product_requested": target,
                "type": "suggestion",
                "message": f"❌ '{target}' not found. Did you mean:",
                "suggestions": [m[0] for m in closest]
            })

    return {"results": final_output}