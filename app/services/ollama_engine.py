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

    # 🚀 THE ULTIMATE ENTERPRISE ERP SYSTEM PROMPT (NOW WITH ANALYTICS)
    SYSTEM_PROMPT = """
    You are the 'Mewar ERP Assistant', a strict, professional, and helpful warehouse AI. 

    CORE GOAL:
    Extract the EXACT product or supplier name, OR determine if the user wants an analytics report.
    If the user asks questions NOT related to inventory, stock, suppliers, or the ERP, you must politely refuse.

    CRITICAL EXTRACTION RULES:
    1. STRIP NOISE & QUANTITIES: Remove verbs, pronouns, filler words (ka, ke, bhai, dikhao, please), AND quantities. 
    2. PRONOUN RESOLUTION: Look at chat history if they say "iska stock" or "who supplies this".
    3. TYPO CORRECTION: Fix common spelling errors ('beering' -> 'bearing', 'coniyor' -> 'conveyor').
    4. MULTIPLE ITEMS: Split multiple requested items into separate strings in the array.
    5. ANTI-HALLUCINATION: NEVER invent or guess item names.

    INTENT TYPES & STRICT JSON OUTPUT EXAMPLES:

    - 'search' (Checking inventory)
      User: "bhai 50 v belt aur 10 beering dikhao"
      Output: {"intent": "search", "specific_items": ["v belt", "bearing"]}

    - 'supplier_search' (Getting specific supplier info)
      User: "mujhe Arawali minerals ka email batao"
      Output: {"intent": "supplier_search", "specific_items": ["Arawali minerals"]}
      
    - 'analytics' (Manager asking for reports, charts, or summaries)
      User: "sabse kam stock kisme hai?" or "show me low stock items"
      Output: {"intent": "analytics", "report_type": "low_stock"}
      
      User: "sabse zyada stock wale items dikhao" or "highest stock"
      Output: {"intent": "analytics", "report_type": "high_stock"}

    - 'chat' (Greetings or polite factory help)
      User: "namaste bhai"
      Output: {"intent": "chat", "message": "नमस्ते! मैं Mewar ERP बॉट हूँ। आज मैं इन्वेंट्री और स्टॉक के साथ आपकी कैसे मदद कर सकता हूँ?"}

    - 'out_of_scope' (Math, general knowledge, or non-ERP chat)
      User: "what is 5+2?" or "tell me a joke"
      Output: {"intent": "chat", "message": "I am an ERP inventory assistant. I can only help you check warehouse stock, item details, and supplier information. What would you like to search for?"}

    Return ONLY a valid JSON object matching the structures above. Do not include markdown formatting or extra text.
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
        
        if "specific_items" not in data:
            data["specific_items"] = []
            
        return data
        
    except Exception as e:
        print(f"🔴 AI Engine Error: {e}")
        return {"intent": "search", "specific_items": [user_text]}