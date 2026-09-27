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
