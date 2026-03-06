import json
import re
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

MODEL_NAME = "gemma3:4b"

# --- 1. SETUP CLOUD CLIENT ---
ollama_api_key = os.getenv("OLLAMA_API_KEY")

if not ollama_api_key:
    print("❌ Critical Error: OLLAMA_API_KEY not found!")
    client = None
else:
    try:
        client = OpenAI(
            base_url="https://api.ollama.com/v1", 
            api_key=ollama_api_key.strip()
        )
        print("☁️ Connected to Ollama Cloud!")
    except Exception as e:
        print(f"⚠️ Warning: Could not connect to Ollama. {e}")
        client = None

def clean_json_string(text: str):
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return match.group(0) if match else text

def manual_hindi_cleaner(text: str):
    """Failsafe: Strips Hindi filler AND splits multiple items based on 'aur' / 'and'."""
    # First, replace conjunctions with commas to split items
    text = text.lower().replace(" aur ", ",").replace(" and ", ",").replace(" ya ", ",")
    filler = ["mujhe", "chahiye", "dikhao", "kya", "hai", "dikha", "do", "i", "want", "show", "please", "the", "a"]
    
    extracted_products = []
    # Split by the commas we just created
    for part in text.split(","):
        words = part.split()
        cleaned_words = [w for w in words if w not in filler]
        if cleaned_words:
            extracted_products.append(" ".join(cleaned_words))
            
    return extracted_products if extracted_products else [text]

def ask_ollama(user_text: str):
    # --- FAILSAFE: IF AI IS UNAUTHORIZED OR DOWN ---
    if not client:
        cleaned_list = manual_hindi_cleaner(user_text)
        print(f"🔴 AI Offline. Manual Clean Extracted: {cleaned_list}")
        return {
            "intent": "search", 
            "general_categories": cleaned_list, 
            "specific_items": [],
            "products": cleaned_list
        }

    SYSTEM_PROMPT = """
    You are the 'Mewar ERP Intelligence Layer.' Your job is to extract clean product names from messy human language.
    
    RULES:
    1. Strip ALL Hindi/English filler: 'mujhe', 'chahiye', 'dikhao', 'kya', 'i want', 'show me', etc.
    2. Correct common spelling mistakes (e.g., 'baering' -> 'bearing', 'vbelt' -> 'v belt').
    3. If the user asks for multiple items (using 'aur', 'and', or commas), split them into separate array strings.
    
    EXAMPLES:
    User: "mujhe bearing aur v belt chahiye"
    Output: {"intent": "search", "general_categories": ["bearing", "v belt"], "specific_items": []}
    
    User: "baering 2216 dikha do please"
    Output: {"intent": "search", "general_categories": [], "specific_items": ["bearing 2216"]}
    
    OUTPUT ONLY VALID JSON.
    """

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
        data = json.loads(clean_json_string(raw_text))
        data["products"] = data.get("general_categories", []) + data.get("specific_items", [])
        return data

    except Exception as e:
        print(f"🔴 AI Error: {e}")
        cleaned_list = manual_hindi_cleaner(user_text)
        return {
            "intent": "search", 
            "general_categories": cleaned_list, 
            "specific_items": [],
            "products": cleaned_list
        }