# /opt/networkat_sdwan/core/web_app/fastapi_app/schemas/adguard.py
from typing import Any, Optional
from pydantic import BaseModel, Field


class ProtectionToggleRequest(BaseModel):
    enabled: bool
    duration: int = Field(0, description="Duration in milliseconds. 0 means indefinitely.")


class DNSRewriteRule(BaseModel):
    domain: str = Field(..., example="internal.sdwan.local")
    answer: str = Field(..., example="100.123.0.1")


class FilteringRulesRequest(BaseModel):
    rules: list[str] = Field(..., example=["||malicious-site.com^", "@@||whitelisted.com^"])


class AdGuardStatusResponse(BaseModel):
    protection_enabled: bool
    version: str
    dns_addresses: list[str]
    dns_port: int


class GenericAdGuardResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None

class BlockedServicesRequest(BaseModel):
    ids: list[str]