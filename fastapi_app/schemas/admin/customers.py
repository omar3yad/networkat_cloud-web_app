# /opt/networkat_sdwan/core/web_app/fastapi_app/schemas/admin/customers.py
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


class CustomerSummarySchema(BaseModel):
    id: str
    username: str
    name: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    plan_id: Optional[int] = None
    plan_name: Optional[str] = None
    status: str = "active"
    is_active: bool = True
    peers_count: int = 0
    online_count: int = 0
    allowed_peers_count: int = 5
    renewal_date: Optional[str] = None
    billing_cycle: Optional[str] = None
    is_trial: bool = False
    created_at: Optional[str] = None


class CustomerListResponse(BaseModel):
    success: bool = True
    total: int
    page: int
    per_page: int
    customers: List[CustomerSummarySchema]


class CustomerDetailResponse(BaseModel):
    success: bool = True
    customer: CustomerSummarySchema
    subscription: Dict[str, Any] = Field(default_factory=dict)
    peers: List[Dict[str, Any]] = Field(default_factory=list)


class CustomerStatusUpdateSchema(BaseModel):
    status: str = Field(..., description="Target status: active, grace_period, limit_control, inactive")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        valid_statuses = {"active", "grace_period", "limit_control", "inactive"}
        clean = v.strip().lower()
        if clean not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(sorted(valid_statuses))}")
        return clean


class CustomerPlanUpdateSchema(BaseModel):
    plan_id: int = Field(..., description="Subscription plan ID")
    billing_cycle: Optional[str] = Field(None, description="'monthly' or 'yearly'")
    allowed_peers_count: Optional[int] = Field(None, ge=1, description="Custom peer device limit override")
    renewal_date: Optional[str] = Field(None, description="ISO format renewal date (YYYY-MM-DD)")
    is_trial: Optional[bool] = Field(None, description="Flag indicating if customer is in free trial")
    status: Optional[str] = Field(None, description="Optional target subscription status")

    @field_validator("billing_cycle")
    @classmethod
    def validate_cycle(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = v.strip().lower()
        if clean in ("monthly", "yearly"):
            return clean
        return "monthly"


class CustomerResetPasswordSchema(BaseModel):
    password: str = Field(..., min_length=6, max_length=128, description="New password for customer or portal user")
    user_id: Optional[str] = Field(None, description="Optional portal user ID if not resetting main client")


class CustomerActionResponse(BaseModel):
    success: bool = True
    message: str = "Operation completed"
    subscription: Optional[Dict[str, Any]] = None
