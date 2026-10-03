# /opt/networkat_sdwan/core/web_app/fastapi_app/services/system_settings_service.py
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from models.system_setting import SystemSetting

logger = logging.getLogger(__name__)


class SystemSettingsService:

    @staticmethod
    def get_all_by_category(db: Session) -> Dict[str, List[dict]]:
        """Return all system settings grouped by category."""
        rows = db.query(SystemSetting).order_by(SystemSetting.category, SystemSetting.key).all()
        result: Dict[str, List[dict]] = {}
        for r in rows:
            result.setdefault(r.category, []).append(r.to_dict())
        return result

    @staticmethod
    def get_settings_by_category(db: Session, category: str) -> List[dict]:
        """Return settings for a specific category (case-insensitive)."""
        rows = db.query(SystemSetting).filter(
            SystemSetting.category.ilike(category.strip())
        ).order_by(SystemSetting.key).all()
        if not rows:
            # Check if category exists
            all_cats = [r[0] for r in db.query(SystemSetting.category).distinct().all()]
            match = next((c for c in all_cats if c.lower() == category.lower()), None)
            if not match:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Category '{category}' not found"
                )
            rows = db.query(SystemSetting).filter(
                SystemSetting.category == match
            ).order_by(SystemSetting.key).all()
        return [r.to_dict() for r in rows]

    @staticmethod
    def get_setting_by_key(db: Session, key: str) -> dict:
        """Fetch a single setting by key or raise 404."""
        setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if not setting:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Setting '{key}' not found"
            )
        return setting.to_dict()

    @staticmethod
    def update_many(db: Session, updates: Dict[str, Any], updated_by: str = "admin") -> None:
        """Update multiple system settings in a single transaction."""
        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No settings provided for update"
            )

        now = datetime.utcnow()
        try:
            for key, val in updates.items():
                row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
                if row is None:
                    logger.warning("SystemSettingsService: unknown key '%s', skipping", key)
                    continue
                # Format booleans cleanly
                if isinstance(val, bool):
                    row.value = "true" if val else "false"
                else:
                    row.value = str(val).strip()
                row.updated_at = now
                row.updated_by = updated_by

            db.commit()

            # Invalidate in-memory cache if settings_service is loaded
            try:
                from services.settings_service import settings as app_settings
                app_settings.invalidate()
            except Exception:
                pass

        except HTTPException:
            raise
        except Exception as e:
            db.rollback()
            logger.error("Error updating system settings in DB: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update settings"
            )
