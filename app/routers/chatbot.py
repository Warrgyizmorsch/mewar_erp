from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.database import get_db
from app.schemas.chat import ChatRequest
from app.dependencies import get_current_user

# --- IMPORT OLLAMA ENGINE ---
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
    # 2. AI EXTRACTION
    # =========================================================
    ai_data = ask_ollama(raw_q)
    intent = ai_data.get("intent", "search")
    products = ai_data.get("products", [])

    # =========================================================
    # FEATURE 1: SHOW ALL SUPPLIERS
    # =========================================================
    if intent == "supplier_list" or low_q == "supplier":
        suppliers = db.execute(text("SELECT id, supplier_name FROM suppliers LIMIT 50")).fetchall()
        return {
            "type": "supplier_list",
            "message": "Active Suppliers Directory:",
            "suppliers": [{"id": s.id, "name": s.supplier_name} for s in suppliers]
        }

    if not products and not low_q.startswith("supplier "):
        return {"message": "Please specify the items or supplier you are looking for."}

    # =========================================================
    # FEATURE 2: SUPPLIER SMART SEARCH (YOUR CUSTOM LOGIC)
    # =========================================================
    if intent == "supplier_search" or low_q.startswith("supplier "):
        # Extract ID or Name safely
        q = str(products[0]).strip().lower() if products else low_q.replace("supplier", "").strip()
        if low_q.startswith("supplier ") and q == low_q:
            q = low_q.replace("supplier", "").strip()

        # Find the Supplier
        if q.isdigit():
            suppliers = db.execute(text("""
                SELECT id, supplier_name, supplier_code, email, gstin
                FROM suppliers WHERE id = :id LIMIT 10
            """), {"id": int(q)}).fetchall()
        else:
            suppliers = db.execute(text("""
                SELECT id, supplier_name, supplier_code, email, gstin
                FROM suppliers 
                WHERE LOWER(supplier_name) LIKE LOWER(:q) OR LOWER(supplier_code) LIKE LOWER(:q)
                ORDER BY supplier_name LIMIT 10
            """), {"q": f"%{q}%"}).fetchall()

        # Handle Multiple or None
        if len(suppliers) > 1:
            return {
                "type": "dropdown",
                "items": [{"id": s.id, "name": s.supplier_name, "code": s.supplier_code} for s in suppliers]
            }
        
        if not suppliers:
            return {"message": f"Supplier '{q}' not found."}

        # --- YOUR EXACT SUPPLIER INVENTORY LOOP LOGIC ---
        supplier = suppliers[0]
        supplier_id = supplier.id

        inventories = db.execute(text("SELECT id, name, classification FROM inventories ORDER BY name")).fetchall()
        
        finish_total = 0
        semi_finish_total = 0
        items = []

        for inv in inventories:
            txns = db.execute(text("""
                SELECT txn_type, ref_type, quantity FROM stock_transactions
                WHERE inventory_id = :inv_id AND supplier_id = :supplier_id
            """), {"inv_id": inv.id, "supplier_id": supplier_id}).fetchall()

            in_qty, out_qty, finish_in, machining_out = 0, 0, 0, 0
            for t in txns:
                txn_type = (t.txn_type or "").lower()
                ref_type = (t.ref_type or "").lower()
                qty = float(t.quantity or 0)
                
                if txn_type == "in" and ref_type != "finish": in_qty += qty
                if txn_type == "out" and ref_type != "machining": out_qty += qty
                if txn_type == "in" and ref_type == "finish": finish_in += qty
                if txn_type == "out" and ref_type == "machining": machining_out += qty

            classification = (inv.classification or "").upper().strip()
            total = in_qty - out_qty
            
            # FILTER ZERO STOCK
            if total != 0:
                if classification == "FINISH" or classification in ["", "NULL"]:
                    finish_total += total
                else:
                    semi_finish_total += total
                
                items.append({
                    "inventory_id": inv.id,
                    "name": inv.name,
                    "stock": total
                })

        return {
            "type": "result",
            "supplier": {
                "id": supplier.id,
                "name": supplier.supplier_name,
                "code": supplier.supplier_code,
                "email": supplier.email,
                "gstin": supplier.gstin
            },
            "finish_stock": finish_total,
            "semi_finish_stock": semi_finish_total,
            "items": items
        }

    # =========================================================
    # FEATURE 3: STANDARD INVENTORY MULTI-SEARCH (WITH ID SEARCH)
    # =========================================================
    final_output = []
    
    for p_name in products:
        target = str(p_name).strip().lower()
        
        # 🟢 EXACT ID SEARCH
        if target.isdigit():
            inventories = db.execute(text("""
                SELECT id, name, classification, unit, placement, height, width, thikness
                FROM inventories WHERE id = :id
            """), {"id": int(target)}).fetchall()
            
        # 🔵 STANDARD NAME SEARCH
        else:
            inventories = db.execute(text("""
                SELECT id, name, classification, unit, placement, height, width, thikness
                FROM inventories WHERE LOWER(name) LIKE LOWER(:q) ORDER BY name LIMIT 5
            """), {"q": f"%{target}%"}).fetchall()

            # FUZZY SEARCH FALLBACK (Auto-corrects minor typos like "diamoud")
            if not inventories:
                all_rows = db.execute(text("SELECT name FROM inventories")).fetchall()
                names = [r[0] for r in all_rows]
                match = process.extractOne(target, names, scorer=fuzz.token_set_ratio)
                if match and match[1] >= 70:
                    inventories = db.execute(text("""
                        SELECT id, name, classification, unit, placement, height, width, thikness
                        FROM inventories WHERE name = :n
                    """), {"n": match[0]}).fetchall()

        # =========================================================
        # PROCESS RESULTS FOR THIS ITEM
        # =========================================================
        if len(inventories) > 1:
            final_output.append({
                "product_requested": target,
                "type": "dropdown",
                "message": f"Multiple matches found for '{target}':",
                "items": [{"id": i.id, "name": i.name} for i in inventories]
            })
        elif len(inventories) == 1:
            inv = inventories[0]
            txns = db.execute(text("SELECT txn_type, ref_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()

            in_qty, out_qty, finish_in, machining_out = 0, 0, 0, 0
            for t in txns:
                tt, rt, qty = (t[0] or "").lower(), (t[1] or "").lower(), float(t[2] or 0)
                if tt == "in" and rt != "finish": in_qty += qty
                if tt == "out" and rt != "machining": out_qty += qty
                if tt == "in" and rt == "finish": finish_in += qty
                if tt == "out" and rt == "machining": machining_out += qty

            cls = (inv.classification or "").upper().strip()
            m_stock, sf_stock, f_stock = 0, 0, 0
            total = in_qty - out_qty

            if cls in ["", "FINISH", "NULL"]: f_stock = total
            elif cls == "SEMI_FINISH":
                mc, fn = (machining_out - finish_in), (finish_in - out_qty)
                m_stock, f_stock = mc, fn
                sf_stock = total - mc - fn
            else: f_stock = in_qty - finish_in

            final_output.append({
                "type": "result",
                "inventory": {"id": inv.id, "name": inv.name, "classification": cls},
                "stock": {"machining": m_stock, "finish": f_stock, "semi_finish": sf_stock, "total": total}
            })
            
        # ✅ YOUR NEW SMART SUGGESTIONS BLOCK ✅
        else:
            # =========================================================
            # 🚀 SMART SUGGESTIONS (INSTEAD OF JUST "NOT FOUND")
            # =========================================================
            all_rows = db.execute(text("SELECT name FROM inventories")).fetchall()
            names = [r[0] for r in all_rows]
            
            # Find the top 5 closest matches in the database, even if the score is low
            closest_matches = process.extract(target, names, scorer=fuzz.token_set_ratio, limit=5)
            
            # Extract just the names from the RapidFuzz tuple
            suggested_names = [m[0] for m in closest_matches] if closest_matches else names[:5]

            final_output.append({
                "product_requested": target,
                "message": f"❌ '{target}' not found. Did you mean one of these?",
                "suggestions": suggested_names
            })

    return {"results": final_output}