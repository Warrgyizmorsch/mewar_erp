import json
import re
import os
import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)
MODEL_NAME = "llama-3.3-70b-versatile"

# 🔑 API KEYS POOL (Dono keys ko yahan list mein daala hai)
GROQ_KEYS = [
    os.getenv("GROQ_API_KEY_1"),
    os.getenv("GROQ_API_KEY_2")
]
# Track karne ke liye ki abhi kaunsi key use ho rahi hai
current_key_index = 0

def clean_json_string(text: str):
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*', '', text, flags=re.MULTILINE)
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != 0:
            return text[start:end]
        return text
    except:
        return text

def ask_ollama(user_text: str, history: list = None):
    global current_key_index # Global index use karenge rotation ke liye
    if history is None: 
        history = []
    
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    # 🧠 SYSTEM PROMPT (Bilkul wahi jo aapne diya tha)
# 🧠 SYSTEM PROMPT (Fixed for Python f-string with Double Brackets)
    SYSTEM_PROMPT = f"""
    You are the 'Mewar ERP Master AI', a highly intelligent shopkeeper-style assistant. 
    You have deep knowledge of the business database and can extract complex filters from human speech.
    Today's date is {today}.

--- PERSONALITY RULES ---
1. Always respond in a helpful, conversational Hinglish tone.
2. If the user mentions an item (e.g., 'bearing', 'v belt', 'bolt'), set intent to 'search'. 
   DO NOT ask "Kaunsa?" if you can search for it.
3. Use the 'reasoning' field to be friendly while the results load.
   Example: "Zaroor bhai, bearings ki list check karta hoon..."
4. Only use 'clarify' if the user input is unclear, empty, or unrelated.

--- 🛑 NAME SAFETY RULE (VERY IMPORTANT) ---
1. NEVER shorten, crop, or guess any supplier, project, or company name.
2. If user types "Amr Kay Spring Industries", keep it EXACTLY same in `search_target`.
3. ONLY fix spelling mistakes for generic items (like "bearing", "bolt").
   NEVER modify names of suppliers, projects, or companies.

--- 📁 DATABASE KNOWLEDGE ---
- SUPPLIERS: [supplier_name, supplier_code, mobile, city, gstin, category, email]
- INVENTORIES: [name, classification, placement, unit, category]
- PROJECTS: [name, status, priority, machine, budget, deadline]
- POs: [po_number, total_amount, balance_amount, status, date, expected_date]

--- 🧹 KACHRA SAFAI (CRITICAL CLEANING RULE) ---
Remove conversational and helper words from `search_target`, such as:
(bhai, dikhao, batao, batav, check, karke, zara, list, latest, last, de, do, please, plz, wale, wala, supplier, vendor, party, details, contact, profile, project, site, machine)

Example:
"Arawali supplier details" → search_target = "Arawali"

--- 🗣️ SMART UNDERSTANDING RULES ---
1. 'Maal/Stock' → INVENTORY
2. 'Kharcha' → PROJECT budget
3. 'Paisa/Rokra' → PO balance
4. Extract:
   - STATUS: new, in progress, completed, pending, refurbished
   - PRIORITY: high, normal, urgent
   - MACHINE: lathe, crusher, etc.
5. DATE understanding:
   - "last week", "is month" → convert to from_date and to_date
6. CRITICAL:
   NEVER include words like stock, quantity, qty in search_target
   Example: "bearing kitna hai" → target = "bearing"

--- 🧠 CONTEXT MEMORY RULE ---
1. Always check previous conversation history.
2. If user says:
   - "uski list"
   - "orders dikhao"
   - "details"
   → use previous entity name as search_target

--- 🎓 EXAMPLES ---

# INVENTORY
User: "bearing ka stock kitna hai"
AI: {{ "intent": "search", "search_target": "bearing" }}

User: "beerign kitna pda h"
AI: {{ "intent": "search", "search_target": "bearing" }}

# SUPPLIER
User: "shri mahadevv details"
AI: {{ "intent": "supplier_search", "search_target": "Shree Mahadev" }}

User: "Spring industries amr kay"
AI: {{ "intent": "supplier_search", "search_target": "Spring industries amr kay" }}

# PO
User: "last po dikhao"
AI: {{ "intent": "po_search", "search_target": "", "filters": {{ "limit": 1 }} }}

User: "last 5 orders of arawali"
AI: {{ "intent": "po_search", "search_target": "Arawali", "filters": {{ "limit": 5 }} }}

User: "pending po batao"
AI: {{ "intent": "po_search", "search_target": "", "filters": {{ "status": "draft" }} }}

# PROJECT
User: "in progress project batao"
AI: {{ "intent": "project_search", "search_target": "", "filters": {{ "status": "in progress" }} }}

# CONTEXT
User: "uski list dikhao"
AI: {{ "intent": "po_search", "search_target": "<previous entity>" }}

--- 🛡️ INTENT MAPPING ---
- "search" → inventory
- "supplier_search" → supplier
- "project_search" → project
- "po_search" → orders
- "clarify" → unclear input

--- 📝 OUTPUT FORMAT (STRICT JSON) ---
{{
  "intent": "search/po_search/project_search/supplier_search/clarify",
  "search_target": "clean name",
  "specific_items": [],
  "filters": {{
    "status": null,
    "priority": null,
    "city": null,
    "machine": null,
    "category": null,
    "from_date": null,
    "to_date": null,
    "limit": 5
  }},
  "reasoning": "friendly message"
}}

Respond ONLY in JSON.
"""

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in history[-6:]:
        content = msg.get("content") or msg.get("raw_content", "")
        messages.append({"role": msg["role"], "content": content})
    messages.append({"role": "user", "content": user_text})

    # 🔄 ROTATION LOGIC: Loop tab tak chalega jab tak success na mile ya keys khatam na ho
    for attempt in range(len(GROQ_KEYS)):
        try:
            active_key = GROQ_KEYS[current_key_index].strip()
            client = OpenAI(
                base_url="https://api.groq.com/openai/v1", 
                api_key=active_key,
                timeout=10.0
            )

            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                response_format={ "type": "json_object" },
                temperature=0.0 
            )
            
            data = json.loads(clean_json_string(response.choices[0].message.content))
            
            # Default filters management
            default_filters = {
                "limit": 5, "status": None, "priority": None, "city": None, 
                "machine": None, "category": None, "from_date": None, "to_date": None
            }
            if "filters" not in data:
                data["filters"] = default_filters
            else:
                for key, val in default_filters.items():
                    if key not in data["filters"]:
                        data["filters"][key] = val
            
            return data

        except Exception as e:
            # 🛑 RATE LIMIT CHECK: Agar 429 error hai toh key badlo
            if "429" in str(e) or "rate_limit_exceeded" in str(e).lower():
                print(f"⚠️ Groq Key {current_key_index + 1} limit hit! Switching key...")
                current_key_index = (current_key_index + 1) % len(GROQ_KEYS)
                # Loop skip nahi hoga, doosri key ke saath 'attempt' dobara hoga
                continue 
            else:
                print(f"⚠️ AI Error: {e}")
                # Kisi doosre error (e.g. timeout) par bhi doosri key try kar sakte hain
                current_key_index = (current_key_index + 1) % len(GROQ_KEYS)

    # Final Fallback agar sab fail ho jaye
    return {
        "intent": "supplier_search" if any(w in user_text.lower() for w in ["supplier", "party", "minerls", "construction", "shri"]) else "search",
        "search_target": user_text, 
        "specific_items": [], 
        "filters": {"limit": 5, "status": None, "priority": None, "city": None, "machine": None, "category": None, "from_date": None, "to_date": None}
    }