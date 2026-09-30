# /opt/networkat_sdwan/core/web_app/services/settings_service.py
"""
SettingsService — cached wrapper over the SystemSetting table.

Usage (anywhere in the app):
    from services.settings_service import settings

    limit = settings.get_int("trial.log_limit", default=3)
    enabled = settings.get_bool("feature.firewall", default=True)
    days = settings.get_int("subscription.grace_period_days", default=7)

The cache lives at module level with a short TTL so multi-process workers
(FastAPI, Flask workers, schedulers) stay synced with database changes.
"""
import threading
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# The cache lives at module level with a TTL so multi-process workers sync updates.
_cache: Dict[str, str] = {}
_cache_lock = threading.Lock()
_last_loaded: float = 0.0
_CACHE_TTL: float = 5.0  # seconds


def _load_all() -> None:
    """Load every row from system_settings into the cache."""
    global _cache, _last_loaded
    loaded = False
    new_cache = {}

    # 1. Try Flask-SQLAlchemy first if inside an active Flask context
    try:
        from models.system_setting import SystemSetting
        rows = SystemSetting.query.all()
        new_cache = {r.key: r.value for r in rows}
        loaded = True
    except Exception:
        pass

    # 2. If outside Flask context (e.g. FastAPI / uvicorn), use SessionLocal
    if not loaded:
        try:
            from fastapi_app.database import SessionLocal
            from sqlalchemy import text
            with SessionLocal() as session:
                rows = session.execute(text("SELECT key, value FROM system_settings")).fetchall()
                new_cache = {r[0]: str(r[1]) for r in rows}
                loaded = True
        except Exception as exc:
            logger.warning("SettingsService: could not load settings via SessionLocal: %s", exc)

    if loaded:
        with _cache_lock:
            _cache = new_cache
            _last_loaded = time.time()


class _SettingsService:
    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _ensure_loaded(self) -> None:
        global _last_loaded
        if (time.time() - _last_loaded) > _CACHE_TTL:
            _load_all()

    def _raw(self, key: str, default: Optional[str] = None) -> Optional[str]:
        self._ensure_loaded()
        with _cache_lock:
            return _cache.get(key, default)

    # ------------------------------------------------------------------ #
    # Public typed accessors                                               #
    # ------------------------------------------------------------------ #

    def get(self, key: str, default: Any = None) -> Any:
        """Return the raw string value, or *default* if the key is missing."""
        return self._raw(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        val = self._raw(key)
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        val = self._raw(key)
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_bool(self, key: str, default: bool = True) -> bool:
        val = self._raw(key)
        if val is None:
            return default
        return val.lower() in ("true", "1", "yes")

    def get_str(self, key: str, default: str = "") -> str:
        return self._raw(key) or default

    def get_string(self, key: str, default: str = "") -> str:
        return self.get_str(key, default)

    # ------------------------------------------------------------------ #
    # Write path (used by admin routes)                                    #
    # ------------------------------------------------------------------ #

    def set(self, key: str, value: str, updated_by: str = "admin") -> None:
        """Persist a new value and update the cache."""
        from models.system_setting import SystemSetting
        from config.database import db
        from datetime import datetime

        row = SystemSetting.query.get(key)
        if row is None:
            raise KeyError(f"Setting '{key}' not found in database.")
        row.value = str(value)
        row.updated_at = datetime.utcnow()
        row.updated_by = updated_by
        db.session.commit()
        with _cache_lock:
            _cache[key] = str(value)

    def set_many(self, updates: Dict[str, str], updated_by: str = "admin") -> None:
        """Persist multiple values in a single transaction."""
        from models.system_setting import SystemSetting
        from config.database import db
        from datetime import datetime

        now = datetime.utcnow()
        for key, value in updates.items():
            row = SystemSetting.query.get(key)
            if row is None:
                logger.warning("SettingsService.set_many: unknown key '%s', skipping", key)
                continue
            row.value = str(value)
            row.updated_at = now
            row.updated_by = updated_by
        db.session.commit()
        with _cache_lock:
            for key, value in updates.items():
                _cache[key] = str(value)

    def invalidate(self) -> None:
        """Force a full reload on the next access."""
        global _last_loaded
        with _cache_lock:
            _last_loaded = 0.0

    def all_by_category(self) -> Dict[str, list]:
        """Return all settings grouped by category (for the admin UI)."""
        from models.system_setting import SystemSetting
        rows = SystemSetting.query.order_by(
            SystemSetting.category, SystemSetting.key
        ).all()
        result: Dict[str, list] = {}
        for row in rows:
            result.setdefault(row.category, []).append(row.to_dict())
        return result


# Module-level singleton
settings = _SettingsService()
