from pydantic import BaseModel, Field
from typing import Optional

# --- Request Model ---
class NetBirdTokenCreate(BaseModel):
    name: str
    expires_in: int = Field(ge=1, le=365, description="Expiration in days (between 1 and 365)")

# --- Response Models ---
class NetBirdTokenResponse(BaseModel):
    id: str
    name: str
    expiration_date: str
    created_by: str
    created_at: str
    last_used: Optional[str] = None # قد تكون القيمة غير موجودة إذا لم يُستخدم التوكن بعد

class NetBirdTokenCreateResponse(BaseModel):
    plain_token: str
    personal_access_token: NetBirdTokenResponse