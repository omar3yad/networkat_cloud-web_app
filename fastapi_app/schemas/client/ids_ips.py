"""
Client-portal intrusion detection — request models.

Only the shape is checked here; every value is validated again by the peer
against the bounds it reports in `options` (agent docs/agent-api/ids-ips.md).
List items and the settings document go through as objects; what the client
may not send (prevention, community_id, certificate watchlists) is refused in
services/client/ids_ips_service.py.
"""
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Direction(str, Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"
    INTERNAL = "internal"
    EXTERNAL = "external"


class EnabledUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class SettingsReset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: Optional[str] = Field(None, pattern=r"^[a-z_]+$", max_length=40)


class RuleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disabled: Optional[bool] = None
    severity: Optional[Severity] = None


class CustomRulesOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] = Field(min_length=1, max_length=500)


class ListBatch(BaseModel):
    """Remove, change and add in one request (at most 100 items in all, checked by the peer)."""
    model_config = ConfigDict(extra="forbid")

    add: list[dict] = Field(default_factory=list, max_length=100)
    update: list[dict] = Field(default_factory=list, max_length=100)
    remove: list[Annotated[str, Field(pattern=r"^[0-9a-f]{1,64}$")]] = Field(default_factory=list, max_length=100)
