import json
import re
import os
from dotenv import load_dotenv
from openai import OpenAI

# ==========================================
# CONFIGURATION & INITIALIZATION
# ==========================================
load_dotenv(override=True)

MODEL_NAME = "llama-3.3-70b-versatile"
groq_api_key = os.getenv("GROQ_API_KEY")

if not groq_api_key:
    print("⚠️ WARNING: GROQ_API_KEY is missing. AI extraction will use fallback mode.")
    client = None
else:
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_api_key.strip())

def clean_json_string(text: str):
    """Aggressively finds and extracts the JSON block from the AI's raw text response."""
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
    if history is None: 
        history = []
    
    if not client: 
        return {"intent": "search", "specific_items": [user_text]}

    # 🚀 THE ULTIMATE ENTERPRISE ERP SYSTEM PROMPT
    SYSTEM_PROMPT = """
    You are the 'Mewar ERP Assistant', a strict, professional, and helpful warehouse AI. 

    CORE GOAL:
    Extract the EXACT product, supplier, project, or PO name, OR determine if the user wants an analytics report.
    If the user asks questions NOT related to the ERP (inventory, suppliers, POs, projects), you must politely refuse.

    CRITICAL EXTRACTION RULES:
    1. STRIP HINGLISH NOISE & QUANTITIES: Remove verbs, pronouns, filler words (ka, ke, ki, bhai, dikhao, please, batao, hai, kon, se, list, all, show, me, the), AND quantities. 
    2. PRONOUN RESOLUTION: Look at chat history if they say "iska stock" or "who supplies this".
    3. TYPO CORRECTION: Fix common spelling errors ('beering' -> 'bearing', 'coniyor' -> 'conveyor').
    4. MULTIPLE ITEMS: Split multiple requested items into separate strings in the array (only for inventory).
    5. THE "BLANK" RULE: If a user asks for a general list without naming a specific thing (e.g., 'project kon kon se hai', 'latest po', 'show all suppliers'), leave the specific target or array completely blank.

    INTENT TYPES & STRICT JSON OUTPUT EXAMPLES:

    - 'search' (Checking inventory)
      User: "bhai 50 v belt aur 10 beering dikhao"
      Output: {"intent": "search", "specific_items": ["v belt", "bearing"]}

    - 'supplier_search' / 'supplier_list' (Supplier info)
      User: "mujhe Arawali minerals ki details batao"
      Output: {"intent": "supplier_search", "search_target": "Arawali minerals"}
      User: "supplier kon kon hai?" or "show all vendors"
      Output: {"intent": "supplier_list", "search_target": ""}
      
    - 'po_search' (Purchase Orders)
      User: "latest po dikhao" or "show po"
      Output: {"intent": "po_search", "search_target": ""}
      User: "po number 1234 ki details do" or "mhel/po 1234"
      Output: {"intent": "po_search", "search_target": "1234"}
      
    - 'project_search' (Projects)
      User: "project kon kon se chal rahe hai" or "list projects"
      Output: {"intent": "project_search", "search_target": ""}
      User: "Mahadev project ki details batao"
      Output: {"intent": "project_search", "search_target": "Mahadev"}

    - 'analytics' (Manager asking for reports, charts, or summaries)
      User: "sabse kam stock kisme hai?" or "show me low stock items"
      Output: {"intent": "analytics", "report_type": "low_stock"}
      User: "sabse zyada stock wale items dikhao" or "highest stock"
      Output: {"intent": "analytics", "report_type": "high_stock"}

    - 'chat' / 'out_of_scope' (Greetings or non-ERP chat)
      User: "namaste bhai"
      Output: {"intent": "chat", "message": "Hello! I am the Mewar ERP bot. How can I help you with inventory, suppliers, POs, or projects today?"}
      User: "what is 5+2?" or "tell me a joke"
      Output: {"intent": "chat", "message": "I am an ERP assistant. I can only help you check warehouse stock, item details, POs, projects, and supplier information. What would you like to search for?"}
    
    - 'unknown' (Gibberish or impossible to understand)
      User: "asdfghj" or "kuch bhi"
      Output: {"intent": "unknown", "message": "I couldn't understand that. Are you looking for Inventory, POs, Suppliers, or Projects?"}
      
    Return ONLY a valid JSON object matching the structures above. Do not include markdown formatting, backticks, or extra text.
    """

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    for msg in history[-4:]:  
        if msg.get("role") in ["user", "assistant"]:
            content = msg.get("content") or msg.get("raw_content", "")
            messages.append({"role": msg["role"], "content": content})
            
    messages.append({"role": "user", "content": user_text})

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            response_format={ "type": "json_object" },
            temperature=0.0 
        )
        
        raw_output = response.choices[0].message.content
        data = json.loads(clean_json_string(raw_output))
        
        # Only enforce specific_items if it's a search intent
        if data.get("intent") in ["search", "supplier_search"] and "specific_items" not in data:
            data["specific_items"] = []
            
        return data
        
    except Exception as e:
        print(f"🔴 AI Engine Error: {e}")
        return {"intent": "search", "specific_items": [user_text]}