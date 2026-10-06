# /opt/networkat_sdwan/core/web_app/fastapi_app/schemas/admin/peers.py
from typing import Optional, List
from pydantic import BaseModel, Field


class CustomerSummarySchema(BaseModel):
    id: str
    name: str
    username: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    plan: Optional[str] = None


class PeerSchema(BaseModel):
    id: str
    name: str
    hostname: Optional[str] = ""
    ip: Optional[str] = "—"
    connection_ip: Optional[str] = "—"
    connected: bool = False
    is_reachable: bool = False
    is_online: bool = False
    status_label: str = "Offline"
    last_seen: Optional[str] = ""
    os: Optional[str] = ""
    version: Optional[str] = ""
    vpn_only: bool = False
    customer: Optional[CustomerSummarySchema] = None


class PeerStatsSchema(BaseModel):
    total: int = 0
    online: int = 0
    offline: int = 0
    customers_count: int = 0
    online_pct: int = 0


class AdminPeersResponse(BaseModel):
    success: bool = True
    peers: List[PeerSchema] = Field(default_factory=list)
    stats: PeerStatsSchema = Field(default_factory=PeerStatsSchema)
    customers: List[CustomerSummarySchema] = Field(default_factory=list)
