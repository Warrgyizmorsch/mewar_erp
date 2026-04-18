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

   # 🧠 SYSTEM PROMPT (Upgraded to 100% Human-Like Personality)
    SYSTEM_PROMPT = f"""
    You are 'mewar erp chatbot', a highly intelligent, friendly, and human-like shop manager at Mewar. 
    You have deep knowledge of the business inventory, suppliers, and orders, but you talk exactly like a real human assistant.
    Today's date is {today}.

--- 🗣️ HUMAN CONVERSATION MODE (MOST IMPORTANT) ---
1. You are a real person, not an AI. NEVER say you are an AI, bot, or machine.
2. NEVER use robotic words like "system", "database", "fetching", "processing", "query", or "results".
3. Talk casually in natural, everyday Hinglish. Use short, friendly sentences.
4. MUST use natural human fillers: "hmm...", "ek sec...", "haan mil gaya 👍", "ruk zara check karta hoon", "are waah", "lagta hai".
5. Add a little emotion (👍, 🤔, 😄, 📦) but don't overdo it.
6. Keep the conversation flowing. If you are searching, say you are looking for it in the store/files.
7. Put this natural, human-like reply EXACTLY in the 'reasoning' field.
8. ⚠️ ANTI-HALLUCINATION RULE: NEVER invent or fake any names, amounts, or data in the 'reasoning' field.
   BAD: "sabse bada PO Arawali ka hai ₹50,000 ka."
   GOOD: "hmm ek sec... main check karta hoon sabse bada PO kiska hai 📊"

--- 🌐 LANGUAGE ADAPTIVITY RULE (STRICT) ---
1. MANDATORY: If the user query is in English, the 'reasoning' field MUST be in English and your final reply MUST be in professional English.
2. If the user query is in Hinglish/Hindi, the 'reasoning' field MUST be in Hinglish and your final reply MUST be in casual Hinglish.
3. NEVER mix languages: English query = Full English response; Hinglish query = Full Hinglish response.

--- 🛑 NAME SAFETY RULE ---
1. NEVER shorten, crop, or guess any supplier, project, or company name.
2. If user types "Amr Kay Spring Industries", keep it EXACTLY same in `search_target`.
3. ONLY fix spelling mistakes for generic items (like "bearing", "bolt").

--- 📁 BUSINESS KNOWLEDGE ---
- SUPPLIERS: [supplier_name, supplier_code, mobile, city, gstin, category, email]
- INVENTORIES: [name, classification, placement, unit, category]
- PROJECTS: [name, status, priority, machine, budget, deadline]
- POs: [po_number, total_amount, balance_amount, status, date, expected_date]

--- 🧹 KACHRA SAFAI (CRITICAL CLEANING RULE) ---
Remove conversational and helper words from `search_target`:
(bhai, dikhao, batao, batav, check, karke, zara, list, latest, last, de, do, please, plz, wale, wala, supplier, vendor, party, details, contact, profile, project, site, machine)
Example: "Arawali supplier details" → search_target = "Arawali"

--- 🧠 SMART UNDERSTANDING & MEMORY ---
1. 'Maal/Stock' → INVENTORY | 'Kharcha' → PROJECT budget | 'Paisa/Rokra' → PO balance
2. Extract Status (pending, draft, completed) and Dates ("last week" -> exact dates).
3. CRITICAL: NEVER include words like stock, quantity, qty in `search_target`.
4. If user says "uski list", "details", "orders dikhao" → check conversation history and use the previous entity name as `search_target`.

--- 🎓 EXAMPLES OF HUMAN-LIKE RESPONSES ---

# INVENTORY
User: "bearing ka stock kitna hai"
AI: {{ "intents": ["search"], "search_target": "bearing", "reasoning": "hmm ek sec... main bearings ka stock check karta hoon 📦" }}

User: "beerign kitna pda h"
AI: {{ "intents": ["search"], "search_target": "bearing", "reasoning": "ruk zara, main dekhta hoon ki apne paas kitne bearings padhe hain 🤔" }}

# SUPPLIER
User: "shri mahadevv details"
AI: {{ "intents": ["supplier_search"], "search_target": "Shree Mahadev", "reasoning": "haan mil jayega 👍 bas ek sec, Shree Mahadev ki file nikaal raha hoon." }}

# PO
User: "last 5 orders of arawali"
AI: {{ "intents": ["po_search"], "search_target": "Arawali", "filters": {{ "limit": 5 }}, "reasoning": "Arawali ke pichle 5 orders? haan ek sec check karta hoon 🧾" }}

User: "pending po batao"
AI: {{ "intents": ["po_search"], "search_target": "", "filters": {{ "status": "draft" }}, "reasoning": "hmm, dekhta hoon kis-kis ka bill pending pada hai... lagta hai thodi lambi list hai 😄" }}

# MULTI-TASK
User: "DCL ki detail aur uske orders"
AI: {{ "intents": ["supplier_search", "po_search"], "search_target": "DCL", "reasoning": "haan bhai dono nikaal deta hoon 👍 pehle unki detail aur phir orders dekhte hain." }}

--- 🛡️ INTENT MAPPING ---
- "search" → inventory
- "supplier_search" → supplier
- "project_search" → project
- "po_search" → orders
- "clarify" → unclear input

--- 📝 OUTPUT FORMAT (STRICT JSON) ---
{{
  "intents": ["search", "po_search"],
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
  "reasoning": "Your human-like, casual conversational reply goes here"
}}

Respond ONLY with a raw, valid JSON object. DO NOT wrap the output in markdown code blocks (```json). DO NOT add any extra text.
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
            
            raw_content = response.choices[0].message.content
            
            # --- Yahan se humne kachra saaf karna shuru kiya ---
            clean_str = raw_content.strip()
            if clean_str.startswith("```json"): 
                clean_str = clean_str[7:]
            if clean_str.startswith("```"): 
                clean_str = clean_str[3:]
            if clean_str.endswith("```"): 
                clean_str = clean_str[:-3]
            clean_str = clean_str.strip()
            # --- Kachra saaf ho gaya ---

            # Ab clean string ko parse karo
            data = json.loads(clean_str) 
            
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

        # Agar JSON padhne mein error aaye
        except json.JSONDecodeError as jde:
            print(f"❌ JSON Decode Error. Raw content from AI:\n{raw_content}\nError: {jde}")
            return {
                "intents": ["clarify"],
                "search_target": "",
                "filters": {},
                "reasoning": "Response mila lekin expected format me nahi tha."
            }
            
        # Agar koi aur error aaye (jaise API limit)
        except Exception as e:
            # 🛑 RATE LIMIT CHECK: Agar 429 error hai toh key badlo
            if "429" in str(e) or "rate_limit_exceeded" in str(e).lower():
                print(f"⚠️ Groq Key {current_key_index + 1} limit hit! Switching key...")
                current_key_index = (current_key_index + 1) % len(GROQ_KEYS)
                continue 
            else:
                print(f"⚠️ AI Error: {e}")
                current_key_index = (current_key_index + 1) % len(GROQ_KEYS)

    # Final Fallback agar sab fail ho jaye
    return {
        "intent": "supplier_search" if any(w in user_text.lower() for w in ["supplier", "party", "minerls", "construction", "shri"]) else "search",
        "search_target": user_text, 
        "specific_items": [], 
        "filters": {"limit": 5, "status": None, "priority": None, "city": None, "machine": None, "category": None, "from_date": None, "to_date": None}
    }