"""
Client-portal session, read by FastAPI.

The browser logs in through the client Flask app, which keeps its session in a
signed cookie (`networkat_client_session`). Client-facing FastAPI routes
(`/api/v2/client/...`, proxied by nginx on the dashboard host) read that same
cookie instead of the INTERNAL_API_KEY, so the page's JS can call FastAPI
directly. Nothing here writes the session — Flask still owns login/logout.

Signing must match Flask exactly: same secret (supervisord gives Flask
SECRET_KEY = $FLASK_SECRET_KEY; this process only has FLASK_SECRET_KEY), same
salt / serializer / signer as `flask.sessions.SecureCookieSessionInterface`,
and the same CSRF token scheme as Flask-WTF (the base template's fetch wrapper
sends it as `X-CSRFToken`).
"""
import hmac
import os
from dataclasses import dataclass
from typing import Optional

from flask.sessions import SecureCookieSessionInterface
from itsdangerous import BadSignature, URLSafeTimedSerializer

from config.settings import Config

SESSION_COOKIE_NAME = "networkat_client_session"
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
class ClientSession:
    customer_id: str
    csrf_token: Optional[str]


def load_client_session(cookie_value: Optional[str]) -> Optional[ClientSession]:
    """The logged-in client for this cookie, or None (missing, forged, expired, not logged in)."""
    if not cookie_value:
        return None
    max_age = int(Config.PERMANENT_SESSION_LIFETIME.total_seconds())
    try:
        data = _session_serializer().loads(cookie_value, max_age=max_age)
    except BadSignature:
        return None
    if not isinstance(data, dict) or not data.get("client_logged_in"):
        return None
    customer_id = data.get("client_customer_id")
    if not customer_id:
        return None
    return ClientSession(customer_id=str(customer_id), csrf_token=data.get(_CSRF_FIELD))


def csrf_token_valid(session: ClientSession, header_value: Optional[str]) -> bool:
    """Flask-WTF check: the header is the session's raw token, signed. No time limit (WTF_CSRF_TIME_LIMIT=None)."""
    if not header_value or not session.csrf_token:
        return False
    try:
        raw = URLSafeTimedSerializer(_secret_key(), salt=_CSRF_SALT).loads(header_value)
    except BadSignature:
        return False
    return isinstance(raw, str) and hmac.compare_digest(raw, session.csrf_token)
