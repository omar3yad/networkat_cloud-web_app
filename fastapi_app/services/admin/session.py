"""
Admin portal session, read by FastAPI.

The browser logs in through the admin Flask app, which keeps its session in a
signed cookie (`networkat_admin_session`). Admin-facing FastAPI routes
(`/api/v2/admin/...`) read that same cookie as a fallback when an Authorization
Bearer header is not present. Flask still owns login/logout.

Signing matches Flask exactly: same secret (FLASK_SECRET_KEY or Config.SECRET_KEY),
same salt / serializer / signer as `flask.sessions.SecureCookieSessionInterface`,
and the same CSRF token scheme as Flask-WTF (`X-CSRFToken` header).
"""
import hmac
import os
from dataclasses import dataclass
from typing import Optional

from flask.sessions import SecureCookieSessionInterface
from itsdangerous import BadSignature, URLSafeTimedSerializer

from config.settings import Config

ADMIN_SESSION_COOKIE_NAME = "networkat_admin_session"
CSRF_HEADER = "X-CSRFToken"

_CSRF_SALT = "wtf-csrf-token"  # Flask-WTF default
_CSRF_FIELD = "csrf_token"     # Flask-WTF default session key


def _secret_key() -> str:
    return os.getenv("FLASK_SECRET_KEY") or Config.SECRET_KEY


def _session_serializer() -> URLSafeTimedSerializer:
    iface = SecureCookieSessionInterface()
    return URLSafeTimedSerializer(
        _secret_key(),
        salt=iface.salt,
        serializer=iface.serializer,
        signer_kwargs={"key_derivation": iface.key_derivation, "digest_method": iface.digest_method},
    )


@dataclass(frozen=True)
class AdminSession:
    user_id: str
    username: str
    role: str
    fullname: str
    csrf_token: Optional[str]


def load_admin_session(cookie_value: Optional[str]) -> Optional[AdminSession]:
    """The logged-in admin for this cookie, or None (missing, forged, expired, not logged in)."""
    if not cookie_value:
        return None
    max_age = int(Config.PERMANENT_SESSION_LIFETIME.total_seconds())
    try:
        data = _session_serializer().loads(cookie_value, max_age=max_age)
    except BadSignature:
        return None

    if not isinstance(data, dict) or not data.get("admin_logged_in"):
        return None

    user_id = data.get("admin_user_id") or data.get("user_id")
    if not user_id:
        return None

    username = data.get("admin_username") or data.get("username") or "admin"
    role = data.get("admin_role") or data.get("role") or "admin"
    fullname = data.get("admin_fullname") or data.get("full_name") or username

    return AdminSession(
        user_id=str(user_id),
        username=str(username),
        role=str(role),
        fullname=str(fullname),
        csrf_token=data.get(_CSRF_FIELD),
    )


def csrf_token_valid(session: AdminSession, header_value: Optional[str]) -> bool:
    """Flask-WTF check: the header is the session's raw token, signed. No time limit (WTF_CSRF_TIME_LIMIT=None)."""
    if not header_value or not session.csrf_token:
        return False
    try:
        raw = URLSafeTimedSerializer(_secret_key(), salt=_CSRF_SALT).loads(header_value)
    except BadSignature:
        return False
    return isinstance(raw, str) and hmac.compare_digest(raw, session.csrf_token)
