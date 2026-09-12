"""
/opt/networkat_sdwan/core/web_app/fastapi_app/schemas/controller/commands.py
Pydantic models for the Controller module.
Interacts directly with peers via peer_id without client_id scoping.
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class CommandType(str, Enum):
    """Must stay in sync with agent/schemas.py CommandType."""
    SYSTEM_INFO = "system_info"
    PING_HOST = "ping_host"
    VPN_ONLY = "vpn_only"
    WAN_LINKS = "wan_links"
    FIREWALL_RULES = "firewall_rules"
    SERVICE_CONTROL = "service_control"



class CommandStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    REJECTED = "rejected"


class ExecuteCommandRequest(BaseModel):
    command_type: CommandType
    parameters: dict[str, Any] = Field(default_factory=dict)
    # Set by caller for audit purposes. Falls back to 'system' if not provided.
    requested_by: Optional[str] = None


class CommandResponse(BaseModel):
    id: uuid.UUID
    peer_id: str
    command_type: str
    status: CommandStatus
    reject_reason: Optional[str] = None
    output: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    requested_at: datetime
    executed_at: Optional[datetime] = None


class PeerStatusResponse(BaseModel):
    peer_id: str
    connected: bool
    ip: Optional[str] = None
    agent_healthy: Optional[bool] = None
    agent_version: Optional[str] = None
    # True only when NetBird says connected AND the agent answered /health.
    # NetBird's `connected` can lag behind reality (its relay/signal session
    # can outlive the peer's actual internet uplink) — this is the field
    # the Dashboard should treat as the peer's real status.
    is_reachable: bool = False


class PeerSummary(BaseModel):
    peer_id: str
    name: str
    connected: bool
    ip: Optional[str] = None


class HandshakeResponse(BaseModel):
    peer_id: str
    is_reachable: bool