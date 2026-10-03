# /opt/networkat_sdwan/core/web_app/fastapi_app/schemas/plans.py
from typing import Optional, List, Union
from pydantic import BaseModel, Field, field_validator


class PlanBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="Unique plan slug (e.g. starter, pro)")
    display_name: str = Field(..., min_length=1, max_length=100, description="Human-friendly name (e.g. Starter Plan)")
    allowed_peers_count: int = Field(..., ge=1, description="Maximum number of allowed peer devices")
    billing_cycle: str = Field("monthly,yearly", description="Allowed billing cycles: 'monthly', 'yearly', or 'monthly,yearly'")
    price_monthly: Optional[float] = Field(None, ge=0, description="Monthly price in USD")
    price_annual: Optional[float] = Field(None, ge=0, description="Annual price in USD")
    is_active: bool = Field(True, description="Whether the plan is active and available")

    @field_validator("name")
    @classmethod
    def validate_name_slug(cls, v: str) -> str:
        clean = v.strip().lower().replace(" ", "_")
        if not clean:
            raise ValueError("Plan name cannot be empty")
        return clean

    @field_validator("billing_cycle")
    @classmethod
    def validate_billing_cycle(cls, v: str) -> str:
        valid_cycles = {"monthly", "yearly", "monthly,yearly", "yearly,monthly"}
        clean = v.strip()
        if clean not in valid_cycles:
            return "monthly,yearly"
        return clean


class PlanCreate(PlanBase):
    pass


class PlanUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=100)
    allowed_peers_count: Optional[int] = Field(None, ge=1)
    billing_cycle: Optional[str] = None
    price_monthly: Optional[float] = Field(None, ge=0)
    price_annual: Optional[float] = Field(None, ge=0)
    is_active: Optional[bool] = None

    @field_validator("billing_cycle")
    @classmethod
    def validate_billing_cycle(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        valid_cycles = {"monthly", "yearly", "monthly,yearly", "yearly,monthly"}
        clean = v.strip()
        if clean in valid_cycles:
            return clean
        return "monthly,yearly"


class PlanResponseItem(BaseModel):
    id: int
    name: str
    display_name: str
    allowed_peers_count: int
    billing_cycle: List[str]
    price_monthly: Optional[float] = None
    price_annual: Optional[float] = None
    is_active: bool
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


class PlanListResponse(BaseModel):
    success: bool = True
    plans: List[PlanResponseItem]


class PlanSingleResponse(BaseModel):
    success: bool = True
    plan: PlanResponseItem


class PlanToggleResponse(BaseModel):
    success: bool = True
    is_active: bool


class PlanDeleteResponse(BaseModel):
    success: bool = True
    message: Optional[str] = "Plan deleted"


class TrialDurationUpdate(BaseModel):
    trial_days: int = Field(..., ge=1, le=365, description="Number of trial days (1 to 365)")


class TrialDurationResponse(BaseModel):
    success: bool = True
    trial_days: int
