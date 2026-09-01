"""
Pydantic schemas for the public client authentication API.
"""
from pydantic import BaseModel, Field
from typing import Optional, List


class SetupKeyRequest(BaseModel):
    """Request body for retrieving a client's NetBird Setup Key."""
    username: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="The client portal username."
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="The client portal password."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "omar3yad",
                "password": "123456"
            }
        }
    }


class AccountMeta(BaseModel):
    """Non-sensitive account metadata returned alongside the Setup Key."""
    full_name:    Optional[str] = Field(None, description="Client full name.")
    company_name: Optional[str] = Field(None, description="Client company / organisation name.")
    email:        Optional[str] = Field(None, description="Account email address.")
    country:      Optional[str] = Field(None, description="Country associated with the account.")
    subscription: Optional[str] = Field(None, description="Current subscription plan (e.g. basic, pro).")
    member_since: Optional[str] = Field(None, description="Account creation date (ISO 8601 UTC).")
    active_keys:  int            = Field(0,    description="Number of active setup keys on this account.")


class ClientSetupKeyInfo(BaseModel):
    """Details of a single NetBird Setup Key linked to the client."""
    valid:          bool           = Field(..., description="Whether the key is valid.")
    used_times:     int            = Field(..., description="Number of times this key has been used.")
    usage_limit:    int            = Field(..., description="Maximum number of times this key can be used.")
    remaining_uses: Optional[int]  = Field(None, description="Remaining uses left for this key.")
    key:            str            = Field(..., description="The setup key token value (masked or prefix).")


class SetupKeyResponse(BaseModel):
    """Successful response containing the account metadata and all client setup keys."""
    username:   str                     = Field(..., description="The authenticated username.")
    account:    AccountMeta             = Field(..., description="Non-sensitive metadata about the account.")
    setup_keys: List[ClientSetupKeyInfo] = Field(default=[], description="All NetBird Setup Keys linked to this account.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "username":  "john_doe",
                "account": {
                    "full_name":    "John Doe",
                    "company_name": "Acme Corp",
                    "email":        "john@acme.com",
                    "country":      "Egypt",
                    "subscription": "pro",
                    "member_since": "2025-01-15T10:30:00",
                    "active_keys":  1
                },
                "setup_keys": [
                    {
                        "valid": True,
                        "used_times": 17,
                        "usage_limit": 20,
                        "remaining_uses": 3,
                        "key": "DC78D-XXXX-XXXX-XXXX-XXXX"
                    }
                ]
            }
        }
    }


class ErrorResponse(BaseModel):
    """Standard error response."""
    error:   str = Field(..., description="Short error identifier.")
    message: str = Field(..., description="Human-readable error description.")
