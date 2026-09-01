from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

# --- Sub-Schemas ---
class UserPermissionsModules(BaseModel):
    networks: Dict[str, bool]
    peers: Dict[str, bool]

class UserPermissions(BaseModel):
    is_restricted: Dict[str, Any]
    modules: UserPermissionsModules

# --- Response Models ---
class NetBirdUserResponse(BaseModel):
    id: str
    email: Optional[str] = None
    password: Optional[str] = None
    name: str
    role: str
    status: str
    last_login: Optional[str] = None
    auto_groups: List[str] = []
    is_current: bool
    is_service_user: bool
    is_blocked: bool
    pending_approval: bool
    issued: Optional[str] = None
    idp_id: Optional[str] = None
    permissions: Optional[UserPermissions] = None

class InviteResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    auto_groups: List[str] = []
    expires_at: str
    created_at: str
    expired: bool
    invite_token: str

class InviteInfoResponse(BaseModel):
    email: str
    name: str
    expires_at: str
    valid: bool
    invited_by: str

class InviteRegenerateResponse(BaseModel):
    invite_token: str
    invite_expires_at: str

# --- Request Models ---
class NetBirdUserCreate(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    role: str
    auto_groups: List[str]
    is_service_user: bool

class NetBirdUserUpdate(BaseModel):
    role: str
    auto_groups: List[str]
    is_blocked: bool

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class InviteCreateRequest(BaseModel):
    email: str
    name: str
    role: str
    auto_groups: List[str]
    expires_in: Optional[int] = Field(default=259200, description="Expiration in seconds (default 72 hours)")

class InviteRegenerateRequest(BaseModel):
    expires_in: Optional[int] = Field(default=259200, description="Expiration in seconds")

class AcceptInviteRequest(BaseModel):
    password: str = Field(min_length=8, description="Min 8 chars, 1 uppercase, 1 digit, 1 special char")