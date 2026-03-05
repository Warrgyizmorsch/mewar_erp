import json
import re
import os
from dotenv import load_dotenv
from openai import OpenAI  # 🚀 Fixes the Vercel crash

load_dotenv()

MODEL_NAME = "gemma3:4b"

# --- 1. SETUP CLOUD CLIENT ---
try:
    ollama_api_key = os.getenv("OLLAMA_API_KEY")
    client = OpenAI(
        base_url="https://api.ollama.com/v1", 
        api_key=ollama_api_key
    )
    print("☁️ Connected to Ollama Cloud!")
except Exception as e:
    print(f"⚠️ Warning: Could not connect to Ollama. {e}")
    client = None

# --- 2. YOUR ORIGINAL HELPER FUNCTIONS ---
def clean_json_string(text: str):
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return match.group(0) if match else text

def ask_ollama(user_text: str):
    SYSTEM_PROMPT = """
    You are an ERP Assistant. Extract the USER INTENT and a LIST of exact PRODUCT/SUPPLIER NAMES.
    1. VALID INTENTS: "stock", "search", "supplier_list", "supplier_search", "greet".
    2. EXTRACTION: Extract exact names. DO NOT drop sizes (e.g., '10x50').
    OUTPUT JSON FORMAT: {"intent": "...", "products": ["item1"]}
    """
    if not client:
        return {"intent": "search", "products": [user_text]}
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text}
            ],
            response_format={ "type": "json_object" } 
        )
        raw_text = response.choices[0].message.content
        cleaned_text = clean_json_string(raw_text)
        return json.loads(cleaned_text)
    except Exception as e:
        print(f"🔴 AI Error: {e}")
        return {"intent": "search", "products": [user_text]}