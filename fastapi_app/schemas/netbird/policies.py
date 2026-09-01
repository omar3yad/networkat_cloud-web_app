from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

# --- Sub-Schemas ---
class PortRange(BaseModel):
    start: int
    end: int

class ResourceRef(BaseModel):
    id: str
    type: str

class GroupReference(BaseModel):
    id: str
    name: str
    peers_count: int
    resources_count: Optional[int] = None
    issued: Optional[str] = None

# --- Rule Models ---
class RuleRequest(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    enabled: bool
    action: str
    bidirectional: bool
    protocol: str
    ports: Optional[List[str]] = None
    port_ranges: Optional[List[PortRange]] = None
    authorized_groups: Optional[Dict[str, Any]] = None
    sources: Optional[List[str]] = None  # IDs in request
    sourceResource: Optional[ResourceRef] = None
    destinations: Optional[List[str]] = None  # IDs in request
    destinationResource: Optional[ResourceRef] = None

class RuleResponse(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    enabled: bool
    action: str
    bidirectional: bool
    protocol: str
    ports: Optional[List[str]] = None
    port_ranges: Optional[List[PortRange]] = None
    authorized_groups: Optional[Dict[str, Any]] = None
    sources: Optional[List[GroupReference]] = None  # Objects in response
    sourceResource: Optional[ResourceRef] = None
    destinations: Optional[List[GroupReference]] = None  # Objects in response
    destinationResource: Optional[ResourceRef] = None

# --- Policy Models ---
class NetBirdPolicyCreateUpdate(BaseModel):
    name: str
    description: Optional[str] = None
    enabled: bool
    source_posture_checks: Optional[List[str]] = None
    rules: List[RuleRequest]

class NetBirdPolicyResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    enabled: bool
    source_posture_checks: Optional[List[str]] = None
    rules: List[RuleResponse] = []