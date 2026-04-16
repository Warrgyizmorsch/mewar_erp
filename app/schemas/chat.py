from pydantic import BaseModel
from typing import List, Dict, Optional, Any

class ChatRequest(BaseModel):
    query: str
    # 🚀 This allows the frontend to send previous messages
    history: Optional[List[Dict[str, str]]] = []
    
    # 🚀 NEW: Frontend se dropdown filters lene ke liye
    ui_filters: Optional[Dict[str, Any]] = {}