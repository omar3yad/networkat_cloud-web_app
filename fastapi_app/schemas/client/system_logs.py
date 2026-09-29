"""
Client-portal system logs — request/response models.

Mirrors the client side of the peer agent's system logs (agent docs/logs.md).
Only client fields exist here: an entry never carries `source`,
`admin_message` or `admin_data`, even if the agent sent them.
"""
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class LogLevel(str, Enum):
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ServiceState(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


# Everything a client may see of one entry. Anything else is dropped
# (services/client/system_logs_service.client_entry).
CLIENT_ENTRY_FIELDS = (
    "id", "time", "level", "category", "code", "subject", "actor",
    "message", "data", "repeat_count",
)


class LogEntry(BaseModel):
    id: int
    time: str
    level: str
    category: str
    code: Optional[str] = None
    subject: Optional[str] = None
    actor: Optional[str] = None
    message: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    repeat_count: int = 1


class LogPage(BaseModel):
    limit: int
    count: int
    has_more: bool
    next_before_id: Optional[int] = None


class SystemLogsResponse(BaseModel):
    entries: list[LogEntry]
    page: LogPage
    last_id: Optional[int] = None
    is_gated: bool = False
    gated_count: int = 0
    trial_log_limit: Optional[int] = None


class LogCategoryConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_days: Optional[int] = None
    max_entries: Optional[int] = None
    min_level: Optional[LogLevel] = None
    enabled: Optional[bool] = None
    pause_minutes: Optional[int] = None


class LogConfigUpdate(BaseModel):
    """Partial: any subset of categories and fields. Bounds are the agent's (GET config → `bounds`)."""
    model_config = ConfigDict(extra="forbid")

    categories: dict[str, LogCategoryConfigUpdate] = Field(min_length=1)


class LogServiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ServiceState
