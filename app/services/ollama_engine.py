import json
import re
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

MODEL_NAME = "llama-3.3-70b-versatile"
groq_api_key = os.getenv("GROQ_API_KEY")

if not groq_api_key:
    client = None
else:
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_api_key.strip())

def clean_json_string(text: str):
    """Aggressively finds the JSON block in the AI response."""
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != 0:
            return text[start:end]
        return text
    except:
        return text

def ask_ollama(user_text: str, history: list = None):
    if history is None: history = []
    if not client: return {"intent": "search", "general_categories": [user_text], "specific_items": [], "products": [user_text]}

    # 🚀 THE PURE AI SYSTEM PROMPT
    SYSTEM_PROMPT = """
    You are the 'Mewar ERP Human Intelligence Layer'. You act like a smart warehouse teammate.

    CORE GOAL:
    Extract the EXACT product or supplier name from the user's input, ignoring ALL conversational noise, slang, grammar, or typos.

    CRITICAL EXTRACTION RULES (DO NOT FAIL THESE):
    1. STRIP ALL NOISE: Remove all verbs, pronouns, and connector words in English AND Hindi/Hinglish (like 'ka', 'ke', 'wala', 'bhai', 'dikhao', 'please', 'mujhe', 'show', 'me', 'email', 'details', 'number').
       - Bad: "Arawali ka" -> Good: "Arawali"
       - Bad: "show me bearing" -> Good: "bearing"
       - Bad: "mujhe 6205 wale chahiye" -> Good: "6205"
       - Bad: "yaar arawali ka email dikhao" -> Good: "Arawali"
    2. TYPO CORRECTION: If the user types 'beering' or 'baering', fix it to 'bearing'.
    3. DIMENSION PROTECTION: Never alter technical specs (e.g., '900mm X 4 Ply' stays exactly the same).

    INTENT TYPES:
    - 'search': Checking inventory (e.g., "beering dikhao", "v belt kahan hai").
    - 'supplier_search': Getting supplier info (e.g., "Arawali ka email", "find sup-100").
    - 'supplier_list': Viewing the directory (e.g., "all suppliers", "list dikhao").
    - 'analytical': Comparing data (e.g., "who has the most v belts?").

    OUTPUT ONLY VALID JSON: {"intent": "...", "general_categories": [], "specific_items": []}
    """

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in history[-4:]:
        if msg.get("role") in ["user", "assistant"]:
            messages.append({"role": msg["role"], "content": msg.get("content", "")})
    messages.append({"role": "user", "content": user_text})

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            response_format={ "type": "json_object" },
            temperature=0.0
        )
        data = json.loads(clean_json_string(response.choices[0].message.content))
        data["products"] = data.get("general_categories", []) + data.get("specific_items", [])
        return data
    except Exception as e:
        print(f"🔴 AI Error: {e}")
        return {"intent": "search", "general_categories": [user_text], "specific_items": [], "products": [user_text]}