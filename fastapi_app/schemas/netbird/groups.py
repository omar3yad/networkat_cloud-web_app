# fastapi_app/schemas/netbird_schema.py
from pydantic import BaseModel
from typing import Optional, List

class ResourceSchema(BaseModel):
    id: str
    type: str

class NetBirdGroupCreate(BaseModel):
    name: str
    peers: Optional[List[str]] = None
    resources: Optional[List[ResourceSchema]] = None

class GroupPeerResponse(BaseModel):
    id: str
    name: str

class NetBirdGroupResponse(BaseModel):
    id: str
    name: str
    peers_count: int
    resources_count: int
    issued: str
    # تعديل: جعل القوائم اختيارية وتقبل None بشكل افتراضي
    peers: Optional[List[GroupPeerResponse]] = None
    resources: Optional[List[ResourceSchema]] = None

class ResourceSchema(BaseModel):
    id: str
    type: str

class GroupPeerResponse(BaseModel):
    id: str
    name: str

# --- الـ Request Models (بيانات المدخلات) ---
class NetBirdGroupCreate(BaseModel):
    name: str
    peers: Optional[List[str]] = None
    resources: Optional[List[ResourceSchema]] = None

# --- الـ Response Models (بيانات المخرجات) ---
class NetBirdGroupResponse(BaseModel):
    id: str
    name: str
    peers_count: int
    resources_count: int
    issued: str
    # جعل القوائم اختيارية (Optional) وتقبل None لتجنب الـ ValidationError
    peers: Optional[List[GroupPeerResponse]] = None
    resources: Optional[List[ResourceSchema]] = None