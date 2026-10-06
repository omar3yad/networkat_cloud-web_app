# /opt/networkat_sdwan/core/web_app/fastapi_app/services/appearance_service.py
"""IDS page appearance (fonts, icon colors) stored in system_settings, category "Appearance"."""
import logging
import re
from typing import Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

CATEGORY = "Appearance"
PREFIX = "appearance."

_SANS_FALLBACK = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
_AR_FALLBACK = '"Segoe UI", Tahoma, sans-serif'
_MONO_FALLBACK = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

# name -> (css stack, google css2 family param or None)
_FONTS_EN: Dict[str, tuple] = {
    "System": (_SANS_FALLBACK, None),
    "IBM Plex Sans": (f'"IBM Plex Sans", {_SANS_FALLBACK}', "IBM+Plex+Sans:wght@400;500;600;700"),
    "Inter": (f'"Inter", {_SANS_FALLBACK}', "Inter:wght@400;500;600;700"),
    "Plus Jakarta Sans": (f'"Plus Jakarta Sans", {_SANS_FALLBACK}', "Plus+Jakarta+Sans:wght@400;500;600;700"),
    "Roboto": (f'"Roboto", {_SANS_FALLBACK}', "Roboto:wght@400;500;600;700"),
}
_FONTS_AR: Dict[str, tuple] = {
    n: (f'"{n}", {_AR_FALLBACK}', f"{n.replace(' ', '+')}:wght@400;500;600;700")
    for n in ("IBM Plex Sans Arabic", "Cairo", "Tajawal", "Noto Kufi Arabic", "Almarai")
}
_FONTS_MONO: Dict[str, tuple] = {
    "IBM Plex Mono": (f'"IBM Plex Mono", {_MONO_FALLBACK}', "IBM+Plex+Mono:wght@400;500"),
    "JetBrains Mono": (f'"JetBrains Mono", {_MONO_FALLBACK}', "JetBrains+Mono:wght@400;500"),
    "Roboto Mono": (f'"Roboto Mono", {_MONO_FALLBACK}', "Roboto+Mono:wght@400;500"),
    "System mono": (_MONO_FALLBACK, None),
}

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# key -> (css var, default)
_FONT_KEYS = {
    "appearance.font_en": ("--ids-ff", "System", _FONTS_EN),
    "appearance.font_ar": ("--ids-ff-ar", "IBM Plex Sans Arabic", _FONTS_AR),
    "appearance.font_mono": ("--ids-ff-mono", "IBM Plex Mono", _FONTS_MONO),
}
_COLOR_KEYS = {
    "appearance.icon_color": ("--ids-ic", "#64748b", "Icon color", "Idle icons. Hex like #64748b."),
    "appearance.icon_color_active": ("--ids-ic-on", "#0284c7", "Icon color (active)", "Active icons. Hex like #0284c7."),
    "appearance.icon_color_ok": ("--ids-ic-ok", "#059669", "Icon color (ok)", "OK icons. Hex like #059669."),
    "appearance.icon_color_warn": ("--ids-ic-warn", "#d97706", "Icon color (warning)", "Warning icons. Hex like #d97706."),
    "appearance.icon_color_bad": ("--ids-ic-bad", "#dc2626", "Icon color (error)", "Error icons. Hex like #dc2626."),
}
_FONT_LABELS = {
    "appearance.font_en": "English font",
    "appearance.font_ar": "Arabic font",
    "appearance.font_mono": "Mono font",
}


def _match_font(table: Dict[str, tuple], value) -> Optional[str]:
    v = str(value or "").strip().lower()
    for name in table:
        if name.lower() == v:
            return name
    return None


def default_rows() -> List[dict]:
    rows = []
    for key, (_var, default, table) in _FONT_KEYS.items():
        rows.append({
            "key": key, "value": default, "label": _FONT_LABELS[key],
            "description": "IDS page. One of: " + ", ".join(table) + ".",
        })
    for key, (_var, default, label, desc) in _COLOR_KEYS.items():
        rows.append({"key": key, "value": default, "label": label, "description": "IDS page. " + desc})
    return rows


def ensure_defaults(db: Session) -> None:
    """Insert missing Appearance rows. Never overwrites."""
    existing = {k for (k,) in db.query(SystemSetting.key).filter(SystemSetting.key.like(PREFIX + "%")).all()}
    added = False
    for r in default_rows():
        if r["key"] in existing:
            continue
        db.add(SystemSetting(
            key=r["key"], value=r["value"], value_type="string",
            label=r["label"], description=r["description"], category=CATEGORY,
        ))
        added = True
    if added:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise


def validate(key: str, value) -> None:
    """Raise 400 for a bad appearance.* value. Other keys are ignored."""
    if not str(key).startswith(PREFIX):
        return
    v = str(value if value is not None else "").strip()
    if key in _FONT_KEYS:
        if _match_font(_FONT_KEYS[key][2], v) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown font")
    elif key in _COLOR_KEYS:
        if not _COLOR_RE.match(v):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid color")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown setting")


def theme_css(values: dict) -> str:
    """Build the theme CSS. Invalid/missing values fall back to defaults."""
    values = values or {}
    decls = []
    families = []
    for key, (var, default, table) in _FONT_KEYS.items():
        name = _match_font(table, values.get(key)) or default
        stack, family = table[name]
        decls.append(f"{var}: {stack};")
        if family:
            families.append(family)
    for key, (var, default, _l, _d) in _COLOR_KEYS.items():
        raw = str(values.get(key) or "").strip()
        color = raw.lower() if _COLOR_RE.match(raw) else default
        decls.append(f"{var}: {color};")
    out = ""
    if families:
        out += "@import url('https://fonts.googleapis.com/css2?family=" + "&family=".join(families) + "&display=swap');\n"
    out += ":root { " + " ".join(decls) + " }\n"
    return out


def load_values(db: Session) -> Dict[str, str]:
    rows = db.query(SystemSetting).filter(SystemSetting.key.like(PREFIX + "%")).all()
    return {r.key: r.value for r in rows}
