"""
Pydantic schemas for the public client authentication API.
"""
from pydantic import BaseModel, Field
from typing import Optional


class InstallPeerRequest(BaseModel):
    """Request body for installing a new peer (mints a one-off setup key)."""
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


class SubscriptionMeta(BaseModel):
    """Subscription quota snapshot for the account."""
    plan:                  Optional[str] = Field(None, description="Current subscription plan (e.g. starter, pro).")
    allowed_peers_count:   int = Field(0, description="Maximum peers allowed under the current plan.")
    remaining_peers_count: int = Field(0, description="Peer slots still free (allowed - installed).")
    installed_peers_count: int = Field(0, description="Peers currently enrolled.")


class AccountMeta(BaseModel):
    """Non-sensitive account metadata returned alongside the setup key."""
    full_name:    Optional[str] = Field(None, description="Client full name.")
    company_name: Optional[str] = Field(None, description="Client company / organisation name.")
    country:      Optional[str] = Field(None, description="Country associated with the account.")
    subscription: SubscriptionMeta = Field(default_factory=SubscriptionMeta, description="Subscription quota snapshot.")


class InstallPeerResponse(BaseModel):
    """Successful response: account metadata plus a fresh one-off setup key."""
    username:      str = Field(..., description="The authenticated username.")
    account:       AccountMeta = Field(..., description="Non-sensitive metadata about the account.")
    setup_key:     str = Field(..., description="One-off NetBird setup key to enroll the new peer.")
    install_token: str = Field(..., description="Short-lived token to fetch the installer tarball.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "omar3yad",
                "account": {
                    "full_name": "Omar Ahmed",
                    "company_name": "3yad",
                    "country": "Egypt",
                    "subscription": {
                        "plan": "pro",
                        "allowed_peers_count": 5,
                        "remaining_peers_count": 3,
                        "installed_peers_count": 2
                    }
                },
                "setup_key": "CC7D51F4-4F6F-4D8F-B542-51891E5F2CC4",
                "install_token": "b21hcjN5YWQ..."
            }
        }
    }


class ErrorResponse(BaseModel):
    """Standard error response."""
    error:   str = Field(..., description="Short error identifier.")
    message: str = Field(..., description="Human-readable error description.")
