from pydantic import BaseModel, Field
from typing import List, Optional

# --- Request Models ---
class NetBirdSetupKeyCreate(BaseModel):
    name: str
    type: str = Field(description="Setup key type: 'one-off' or 'reusable'")
    expires_in: int = Field(
        ge=0, 
        le=31536000, 
        description="Expiration time in seconds (between 1 day and 365 days)"
    )
    auto_groups: List[str]
    usage_limit: int = Field(description="0 indicates unlimited usage")
    ephemeral: Optional[bool] = None
    allow_extra_dns_labels: Optional[bool] = None

class NetBirdSetupKeyUpdate(BaseModel):
    revoked: bool
    auto_groups: List[str]

# --- Response Models ---
class NetBirdSetupKeyResponse(BaseModel):
    id: str  # التوثيق يوضح أنه رقم، لكننا نستخدم str لتفادي أي مشاكل في المستقبل وسيقوم Pydantic بالتحويل
    name: str
    expires: str
    type: str
    valid: bool
    revoked: bool
    used_times: int
    last_used: Optional[str] = None
    state: str
    auto_groups: List[str] = []
    updated_at: str
    usage_limit: int
    ephemeral: bool
    allow_extra_dns_labels: bool
    key: str