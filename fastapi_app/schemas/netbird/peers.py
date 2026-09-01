from pydantic import BaseModel, Field
from typing import List, Optional, Any

# --- Sub-Schemas ---
class PeerGroup(BaseModel):
    id: str
    name: str
    peers_count: int
    resources_count: int
    issued: Optional[str] = None

class DisapprovalReason(BaseModel):
    description: str
    type: str

class LocalFlags(BaseModel):
    rosenpass_enabled: Optional[bool] = None
    rosenpass_permissive: Optional[bool] = None
    server_ssh_allowed: Optional[bool] = None
    disable_client_routes: Optional[bool] = None
    disable_server_routes: Optional[bool] = None
    disable_dns: Optional[bool] = None
    disable_firewall: Optional[bool] = None
    block_lan_access: Optional[bool] = None
    block_inbound: Optional[bool] = None
    lazy_connection_enabled: Optional[bool] = None

# --- Request Models ---
class NetBirdPeerUpdate(BaseModel):
    name: str
    ssh_enabled: bool
    login_expiration_enabled: bool
    inactivity_expiration_enabled: bool
    approval_required: Optional[bool] = None
    ip: Optional[str] = None
    ipv6: Optional[str] = None

class TemporaryAccessRequest(BaseModel):
    name: str
    wg_pub_key: str
    rules: List[str]

# --- Response Models ---
class NetBirdPeerResponse(BaseModel):
    id: str
    name: str
    created_at: str
    ip: str
    ipv6: Optional[str] = None
    connection_ip: Optional[str] = None
    connected: bool
    last_seen: str
    os: str
    kernel_version: Optional[str] = None
    geoname_id: Optional[int] = None
    version: str
    groups: List[PeerGroup] = []
    ssh_enabled: bool
    user_id: str
    hostname: str
    ui_version: Optional[str] = None
    dns_label: str
    login_expiration_enabled: bool
    login_expired: bool
    last_login: str
    inactivity_expiration_enabled: bool
    approval_required: bool
    disapproval_reason: Optional[DisapprovalReason] = None
    country_code: Optional[str] = None
    city_name: Optional[str] = None
    serial_number: Optional[str] = None
    extra_dns_labels: List[str] = []
    ephemeral: bool
    local_flags: Optional[LocalFlags] = None
    accessible_peers_count: Optional[int] = None

class AccessiblePeerResponse(BaseModel):
    id: str
    name: str
    ip: str
    ipv6: Optional[str] = None
    dns_label: str
    user_id: str
    os: str
    country_code: Optional[str] = None
    city_name: Optional[str] = None
    geoname_id: Optional[int] = None
    connected: bool
    last_seen: str

class TemporaryAccessResponse(BaseModel):
    name: str
    id: str
    rules: List[str]