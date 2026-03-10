from pydantic import BaseModel
from typing import List, Dict, Optional

class ChatRequest(BaseModel):
    query: str
    # 🚀 NEW: This allows the frontend to send previous messages
    history: Optional[List[Dict[str, str]]] = []