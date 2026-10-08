# /opt/networkat_sdwan/core/web_app/fastapi_app/schemas/admin/staff.py
import re
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


class StaffSummarySchema(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role: str = "admin"
    is_active: bool = True
    is_2fa_enabled: bool = False
    last_login: Optional[str] = None
    created_at: Optional[str] = None


class StaffListResponse(BaseModel):
    success: bool = True
    total: int
    staff: List[StaffSummarySchema]


class StaffCreateSchema(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, description="Unique username")
    email: str = Field(..., min_length=5, max_length=255, description="Staff corporate email")
    full_name: str = Field(..., min_length=2, max_length=150, description="Full name")
    password: str = Field(..., min_length=6, max_length=128, description="Initial password")
    role: str = Field(default="sales", description="Role: admin, support, sales")

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        clean = v.strip()
        if not re.match(r"^[a-zA-Z0-9_-]{3,32}$", clean):
            raise ValueError("Username must be 3-32 characters (letters, numbers, _ and - only)")
        return clean

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if "@" not in clean or "." not in clean:
            raise ValueError("Invalid email address")
        return clean

    @field_validator("full_name")
    @classmethod
    def validate_fullname(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Full name cannot be empty")
        return clean

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        clean = v.strip().lower()
        valid_roles = {"admin", "support", "sales"}
        if clean not in valid_roles:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}")
        return clean


class StaffUpdateSchema(BaseModel):
    email: str = Field(..., min_length=5, max_length=255, description="Staff corporate email")
    full_name: str = Field(..., min_length=2, max_length=150, description="Full name")
    role: str = Field(default="sales", description="Role: admin, support, sales")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if "@" not in clean or "." not in clean:
            raise ValueError("Invalid email address")
        return clean

    @field_validator("full_name")
    @classmethod
    def validate_fullname(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Full name cannot be empty")
        return clean

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        clean = v.strip().lower()
        valid_roles = {"admin", "support", "sales"}
        if clean not in valid_roles:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}")
        return clean


class StaffPasswordResetSchema(BaseModel):
    password: str = Field(..., min_length=6, max_length=128, description="New password")


class StaffToggleStatusResponse(BaseModel):
    success: bool = True
    is_active: bool
    message: str = "Status updated"


class StaffActionResponse(BaseModel):
    success: bool = True
    message: str = "Operation completed"
    staff: Optional[StaffSummarySchema] = None


class Staff2FASetupResponse(BaseModel):
    success: bool = True
    secret: str
    qr_code: str


class Staff2FAConfirmSchema(BaseModel):
    secret: Optional[str] = Field(None, description="TOTP secret from setup session")
    code: str = Field(..., min_length=6, max_length=6, description="6-digit authenticator code")


class Staff2FAConfirmResponse(BaseModel):
    success: bool = True
    recovery_codes: List[str]
    message: str = "Two-factor authentication enabled"


class Staff2FADisableSchema(BaseModel):
    password: Optional[str] = Field(None, description="Password confirmation if disabled by user themselves")
