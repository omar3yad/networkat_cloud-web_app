# /opt/networkat_sdwan/core/web_app/fastapi_app/routes/settings.py
from typing import Dict, Any, Union
from fastapi import APIRouter, Depends, Body, status
from sqlalchemy.orm import Session

from fastapi_app.dependencies import get_db
from fastapi_app.schemas.settings import (
    SettingsAllResponse,
    SettingsGroupResponse,
    SettingSingleResponse,
    SettingsUpdatePayload,
    SettingsUpdateResponse,
)
from fastapi_app.services.system_settings_service import SystemSettingsService

router = APIRouter(
    prefix="/api/v2/settings",
    tags=["System Settings"]
)


@router.get("", response_model=SettingsAllResponse, summary="Get all system settings grouped by category")
def get_all_settings(db: Session = Depends(get_db)):
    by_cat = SystemSettingsService.get_all_by_category(db)
    return {
        "success": True,
        "settings_by_category": by_cat
    }


@router.get("/category/{category}", response_model=SettingsGroupResponse, summary="Get settings for a specific category")
def get_category_settings(category: str, db: Session = Depends(get_db)):
    items = SystemSettingsService.get_settings_by_category(db, category)
    return {
        "success": True,
        "category": category,
        "settings": items
    }


@router.get("/key/{key:path}", response_model=SettingSingleResponse, summary="Get a single setting by key")
def get_single_setting(key: str, db: Session = Depends(get_db)):
    item = SystemSettingsService.get_setting_by_key(db, key)
    return {
        "success": True,
        "key": key,
        "value": item.get("value")
    }


@router.patch("", response_model=SettingsUpdateResponse, summary="Update system settings")
@router.post("", response_model=SettingsUpdateResponse, summary="Update system settings (POST alias)")
def update_settings(
    payload: Union[SettingsUpdatePayload, Dict[str, Any]] = Body(...),
    db: Session = Depends(get_db)
):
    if isinstance(payload, SettingsUpdatePayload):
        updates = payload.settings
    elif isinstance(payload, dict) and "settings" in payload and isinstance(payload["settings"], dict):
        updates = payload["settings"]
    elif isinstance(payload, dict):
        updates = payload
    else:
        updates = {}

    SystemSettingsService.update_many(db, updates, updated_by="admin")
    return {
        "success": True,
        "message": "Settings updated successfully"
    }
