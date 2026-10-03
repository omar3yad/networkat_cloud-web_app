# /opt/networkat_sdwan/core/web_app/fastapi_app/schemas/settings.py
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field


class SettingItem(BaseModel):
    key: str
    value: str
    value_type: str = "string"
    label: str = ""
    description: Optional[str] = None
    category: str = "General"
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None

    model_config = {"from_attributes": True}


class SettingsGroupResponse(BaseModel):
    success: bool = True
    category: str
    settings: List[SettingItem]


class SettingsAllResponse(BaseModel):
    success: bool = True
    settings_by_category: Dict[str, List[SettingItem]]


class SettingSingleResponse(BaseModel):
    success: bool = True
    key: str
    value: Any


class SettingsUpdatePayload(BaseModel):
    settings: Dict[str, Any] = Field(..., description="Key-value mapping of settings to update")


class SettingsUpdateResponse(BaseModel):
    success: bool = True
    message: str = "Settings updated successfully"
