import os
from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import Security, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi_app.database import SessionLocal

API_SECRET_KEY = os.getenv("INTERNAL_API_KEY")

security_scheme = HTTPBearer()

def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    if not API_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API Key security misconfiguration on server",
        )
        
    if credentials.credentials != API_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Authentication Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

# ── Client-portal routes (/api/v2/client/...) ─────────────────────────────────
# Authenticated by the client Flask session cookie, not INTERNAL_API_KEY.
# See fastapi_app/services/client/session.py.

from fastapi import Cookie, Header, Request
from fastapi_app.services.client.session import (
    CSRF_HEADER,
    SESSION_COOKIE_NAME,
    ClientSession,
    csrf_token_valid,
    load_client_session,
)
from fastapi_app.services.client import peer_access

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_client_session(
    request: Request,
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    csrf_header: str | None = Header(default=None, alias=CSRF_HEADER),
) -> ClientSession:
    session = load_client_session(session_cookie)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    if request.method in _UNSAFE_METHODS and not csrf_token_valid(session, csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token")
    return session


def require_client_write(session: ClientSession = Security(get_client_session)) -> ClientSession:
    if not peer_access.can_write(session.customer_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Read-only subscription")
    return session


def get_client_peer(peer_id: str, session: ClientSession = Security(get_client_session)) -> dict:
    """The client's own peer from the path. Not the client's → 404, so other ids don't leak."""
    peer = peer_access.get_owned_peer(session.customer_id, peer_id)
    if peer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return peer


# ── Admin-portal routes (/api/v2/admin/...) ──────────────────────────────────
# Unified auth: checks Authorization header first (Bearer INTERNAL_API_KEY),
# then falls back to admin session cookie (networkat_admin_session) + CSRF token.

import hmac
from dataclasses import dataclass
from fastapi_app.services.admin.session import (
    ADMIN_SESSION_COOKIE_NAME,
    AdminSession,
    csrf_token_valid as admin_csrf_token_valid,
    load_admin_session,
)


@dataclass(frozen=True)
class AdminAuthContext:
    user_id: str | None
    username: str
    role: str
    is_bearer: bool
    fullname: str | None = None
    csrf_token: str | None = None


def get_admin_auth(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    session_cookie: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE_NAME),
    csrf_header: str | None = Header(default=None, alias=CSRF_HEADER),
) -> AdminAuthContext:
    # 1. Primary: Check Authorization Bearer header
    if authorization:
        token = authorization
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        else:
            token = token.strip()

        secret = os.getenv("INTERNAL_API_KEY") or API_SECRET_KEY
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="API Key security misconfiguration on server",
            )
        if not hmac.compare_digest(token, secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API Authentication Token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return AdminAuthContext(
            user_id=None,
            username="internal_api",
            role="admin",
            is_bearer=True,
            fullname="System Administrator",
        )

    # 2. Fallback: Check Admin Flask session cookie
    if session_cookie:
        session = load_admin_session(session_cookie)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not signed in or session expired",
            )
        if request.method in _UNSAFE_METHODS and not admin_csrf_token_valid(session, csrf_header):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or missing CSRF token",
            )
        return AdminAuthContext(
            user_id=session.user_id,
            username=session.username,
            role=session.role,
            is_bearer=False,
            fullname=session.fullname,
            csrf_token=session.csrf_token,
        )

    # 3. Neither header nor cookie present
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin_role(auth: AdminAuthContext = Security(get_admin_auth)) -> AdminAuthContext:
    if auth.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required",
        )
    return auth

