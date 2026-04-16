import urllib.request
import json
import sys
import base64

def check_license():
    try:
        # 🤫 URL ab ek secret code ban gaya hai!
        secret = "aHR0cHM6Ly9naXN0LmdpdGh1YnVzZXJjb250ZW50LmNvbS9sb3ZlOTk1MDc3Lzc5NGI2OGU1MGRmMDAzNjQxMGU0NThhMWY3MzVkZTcyL3Jhdy9naXN0ZmlsZTEudHh0"
        
        # Code run hote time ye wapas asli URL ban jayega
        url = base64.b64decode(secret).decode('utf-8')
        
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
        
        if data.get("status") != "ACTIVE":
            print("❌ ERROR: Your Software License has expired.")
            sys.exit() 
            
    except Exception as e:
        pass