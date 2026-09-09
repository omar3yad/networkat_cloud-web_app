"""
Public Authentication API — Peer Installation.

This router is intentionally excluded from the global API key dependency
so that clients can call it without a Bearer token.
It is registered separately in main.py WITHOUT the auth_dependency.
"""
import os
import time
import requests
import logging
from threading import Lock

from typing import Optional

from fastapi import APIRouter, Request, Header, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash

from fastapi_app.database import SessionLocal
from fastapi_app.schemas.auth import InstallPeerRequest, InstallPeerResponse, AccountMeta, SubscriptionMeta, ErrorResponse
from fastapi_app.services.auth.download_token import make_token, verify_token

logger = logging.getLogger("uvicorn.error")

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Client Authentication"],
)

# ---------------------------------------------------------------------------
# In-memory rate limiter  { ip: [hit_timestamp, ...] }
# ---------------------------------------------------------------------------
_RATE_STORE: dict = {}
_RATE_LOCK  = Lock()
_MAX_HITS   = 5    # max attempts
_WINDOW_SEC = 60   # per minute


def _is_rate_limited(ip: str) -> bool:
    """Sliding-window rate limiter. Returns True when the IP is throttled."""
    now = time.time()
    with _RATE_LOCK:
        hits = _RATE_STORE.get(ip, [])
        hits = [t for t in hits if now - t < _WINDOW_SEC]
        if len(hits) >= _MAX_HITS:
            return True
        hits.append(now)
        _RATE_STORE[ip] = hits
    return False


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# POST /api/v1/auth/install-peer
# ---------------------------------------------------------------------------
@router.post(
    "/install-peer",
    response_model=InstallPeerResponse,
    status_code=status.HTTP_200_OK,
    operation_id="install_peer",
    summary="Install a peer",
    description=(
        "Authenticate with your Networkat client username and password to "
        "install a new peer. On success a fresh one-off NetBird setup key "
        "(valid ~20 minutes, single use) is minted and returned, scoped to "
        "your account's groups."
    ),
    responses={
        200: {"model": InstallPeerResponse, "description": "Setup key minted successfully."},
        400: {"model": ErrorResponse,       "description": "Missing or invalid request fields."},
        401: {"model": ErrorResponse,       "description": "Invalid credentials or account disabled."},
        403: {"model": ErrorResponse,       "description": "Subscription restricted or peer limit reached."},
        415: {"model": ErrorResponse,       "description": "Content-Type must be application/json."},
        429: {"model": ErrorResponse,       "description": "Too many requests — rate limit exceeded."},
        500: {"model": ErrorResponse,       "description": "Unexpected server error."},
    },
)
async def install_peer(payload: InstallPeerRequest, request: Request):
    """
    **Public endpoint** — authenticate as a client and install a new peer.

    ### Flow
    1. Validate that `username` and `password` are present.
    2. Apply per-IP sliding-window rate limiting (5 req / 60 s).
    3. Look up the client by username and verify the password hash.
    4. Enforce subscription status and peer quota.
    5. Mint a one-off NetBird setup key scoped to the account's groups.
    6. Log the access and return the key plus non-sensitive account metadata.

    > ⚠ The same error message is returned for both *unknown username* and
    > *wrong password* to prevent user enumeration.
    """
    ip = _client_ip(request)

    # ── 1. Rate limit ──────────────────────────────────────────────────────
    if _is_rate_limited(ip):
        return JSONResponse(
            status_code=429,
            content={
                "error": "Too Many Requests",
                "message": "Too many attempts. Please try again in a minute.",
            },
        )

    username = payload.username.strip()
    password = payload.password

    # ── 2. Database session ────────────────────────────────────────────────
    db: Session = SessionLocal()
    try:
        from sqlalchemy import text

        # ── 3. Look up client & subscription details ────────────────────────
        row = db.execute(
            text("""
                SELECT
                    c.user_id,
                    c.password_hashed,
                    c.active,
                    c.client_name,
                    c.client_company_name,
                    c.client_email,
                    c.client_country,
                    c.subscription,
                    c.created_at,
                    c.netbird_group_id,
                    c.subscription_status,
                    c.plan_id,
                    p.name AS plan_name,
                    p.allowed_peers_count AS plan_peer_limit
                FROM clients c
                LEFT JOIN subscription_plans p ON (c.plan_id = p.id OR (c.plan_id IS NULL AND LOWER(p.name) = LOWER(c.subscription)))
                WHERE c.username = :u
                LIMIT 1
            """),
            {"u": username},
        ).fetchone()

        # Generic error — don't distinguish "not found" vs "wrong password"
        _INVALID = {
            "error": "Unauthorized",
            "message": "Invalid credentials or account is not active.",
        }

        if row is None:
            logger.warning(f"[install-peer-api] Unknown username='{username}' ip={ip}")
            return JSONResponse(status_code=401, content=_INVALID)

        (
            user_id, password_hashed, active,
            client_name, client_company_name, client_email,
            client_country, subscription, created_at,
            netbird_group_id, subscription_status, plan_id,
            plan_name, plan_peer_limit
        ) = row

        if not active:
            logger.warning(f"[install-peer-api] Disabled account username='{username}' ip={ip}")
            return JSONResponse(status_code=401, content=_INVALID)

        if not check_password_hash(password_hashed, password):
            logger.warning(f"[install-peer-api] Bad password for username='{username}' ip={ip}")
            return JSONResponse(status_code=401, content=_INVALID)

        plan_name = plan_name or subscription or "starter"
        allowed_peers_count = plan_peer_limit or (15 if plan_name == "pro" else (50 if plan_name == "enterprise" else 5))
        subscription_status = subscription_status or "active"

        # Account snapshot returned alongside the setup key on 200, and alongside
        # the notice on a quota / subscription 403 so the installer can show the
        # customer their plan next to it. `installed` defaults to the DB edge
        # count; the quota check overwrites it with the live NetBird figure.
        def _account_meta(installed: int) -> dict:
            return AccountMeta(
                full_name    = client_name,
                company_name = client_company_name,
                country      = client_country,
                subscription = SubscriptionMeta(
                    plan                  = plan_name,
                    allowed_peers_count   = allowed_peers_count,
                    remaining_peers_count = max(0, allowed_peers_count - installed),
                    installed_peers_count = installed,
                ),
            ).model_dump()

        # ── 4. Enforce subscription status ─────────────────────────────────
        if subscription_status in ("limit_control", "inactive"):
            logger.warning(f"[install-peer-api] Account in read-only status='{subscription_status}' user='{username}'")
            edge_cnt = db.execute(
                text("SELECT COUNT(*) FROM edges WHERE client_id = :uid"),
                {"uid": str(user_id)}
            ).scalar()
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Forbidden",
                    "message": "Subscription is currently restricted. Renew your plan to enroll new peers.",
                    "account": _account_meta(edge_cnt or 0),
                }
            )

        # ── 5. NetBird group & peer quota check ────────────────────────────
        NETBIRD_BASE_URL = os.getenv("NETBIRD_API_URL", "http://netbird-server/api").rstrip("/")
        NETBIRD_TOKEN = os.getenv("NETBIRD_TOKEN")
        ALL_PEERS_GROUP_ID = os.getenv("NETBIRD_ALL_PEERS_GROUP_ID")
        if not NETBIRD_TOKEN or not ALL_PEERS_GROUP_ID:
            logger.error("[install-peer-api] Missing NETBIRD_TOKEN or NETBIRD_ALL_PEERS_GROUP_ID env vars")
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal Server Error",
                    "message": "Peer provisioning is misconfigured. Please contact support.",
                }
            )
        nb_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {NETBIRD_TOKEN}"
        }

        # Resolve group_id if not present
        if not netbird_group_id:
            try:
                gres = requests.get(f"{NETBIRD_BASE_URL}/groups", headers=nb_headers, timeout=5)
                if gres.status_code == 200:
                    for g in gres.json():
                        if g.get("name") == username:
                            netbird_group_id = g.get("id")
                            try:
                                db.execute(
                                    text("UPDATE clients SET netbird_group_id = :gid WHERE user_id = :uid"),
                                    {"gid": netbird_group_id, "uid": str(user_id)}
                                )
                                db.commit()
                            except Exception:
                                pass
                            break
            except Exception as ge:
                logger.warning(f"[install-peer-api] Error looking up group for {username}: {ge}")

        # Fetch current peer count
        current_peers = 0
        if netbird_group_id:
            try:
                grp_res = requests.get(f"{NETBIRD_BASE_URL}/groups/{netbird_group_id}", headers=nb_headers, timeout=5)
                if grp_res.status_code == 200:
                    gdata = grp_res.json()
                    if gdata.get("peers_count") is not None:
                        current_peers = int(gdata["peers_count"])
                    else:
                        current_peers = len(gdata.get("peers") or [])
            except Exception as exc:
                logger.warning(f"[install-peer-api] Error querying NetBird group {netbird_group_id}: {exc}")
                edge_cnt = db.execute(
                    text("SELECT COUNT(*) FROM edges WHERE client_id = :uid"),
                    {"uid": str(user_id)}
                ).scalar()
                current_peers = edge_cnt or 0
        else:
            edge_cnt = db.execute(
                text("SELECT COUNT(*) FROM edges WHERE client_id = :uid"),
                {"uid": str(user_id)}
            ).scalar()
            current_peers = edge_cnt or 0

        # Quota check
        if current_peers >= allowed_peers_count:
            logger.warning(f"[install-peer-api] Peer limit reached for user='{username}' ({current_peers}/{allowed_peers_count})")
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Forbidden",
                    "message": f"Cannot add more peers\nlimit exceeded ({current_peers}/{allowed_peers_count}). Upgrade plan to connect more.",
                    "account": _account_meta(current_peers),
                }
            )

        # ── 6. Mint dynamic one-off setup key ──────────────────────────────
        auto_groups = [ALL_PEERS_GROUP_ID]
        if netbird_group_id and netbird_group_id not in auto_groups:
            auto_groups.append(netbird_group_id)

        key_payload = {
            "name": f"install-{username}-{int(time.time())}",
            "type": "one-off",
            "usage_limit": 1,
            "expires_in": 1200,
            "auto_groups": auto_groups,
            "ephemeral": False,
            "allow_extra_dns_labels": False
        }

        try:
            sk_res = requests.post(f"{NETBIRD_BASE_URL}/setup-keys", json=key_payload, headers=nb_headers, timeout=10)
            if sk_res.status_code not in (200, 201):
                logger.error(f"[install-peer-api] NetBird key creation failed: HTTP {sk_res.status_code} - {sk_res.text}")
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": "Internal Server Error",
                        "message": "Failed to generate installation setup key. Please try again or contact support."
                    }
                )
            sk_data = sk_res.json()
            plain_key = sk_data.get("key")
            if not plain_key:
                logger.error(f"[install-peer-api] No key in NetBird response: {sk_data}")
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": "Internal Server Error",
                        "message": "Failed to generate installation setup key. Please try again or contact support."
                    }
                )
        except Exception as ske:
            logger.error(f"[install-peer-api] Exception communicating with NetBird API: {ske}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal Server Error",
                    "message": "Failed to generate installation setup key. Please try again or contact support."
                }
            )

        # ── 7. Build response ─────────────────────────────────────────────
        installed = current_peers
        allowed   = allowed_peers_count
        remaining = max(0, allowed - installed)

        logger.info(f"[install-peer-api] One-off key generated — username='{username}' plan='{plan_name}' peers={installed}/{allowed} ip={ip}")

        return InstallPeerResponse(
            username = username,
            account  = AccountMeta(
                full_name    = client_name,
                company_name = client_company_name,
                country      = client_country,
                subscription = SubscriptionMeta(
                    plan                  = plan_name,
                    allowed_peers_count   = allowed,
                    remaining_peers_count = remaining,
                    installed_peers_count = installed,
                ),
            ),
            setup_key     = plain_key,
            install_token = make_token(username),
        )

    except Exception as exc:
        logger.error(f"[install-peer-api] Internal error for username='{username}': {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": "An unexpected error occurred. Please try again later.",
            },
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /api/v1/auth/verify-download
# ---------------------------------------------------------------------------
# Internal gate for the peer-installer tarball. nginx auth_request hits this
# (see core/nginx/conf/peer-installer.locations) forwarding the client's
# Authorization header; 204 tells nginx to serve the file, 401 (which nginx
# maps to a 403 for the client) blocks it. Hidden from /docs — it is not a
# public API surface, just the check behind the download.
@router.get("/verify-download", include_in_schema=False)
async def verify_download(authorization: Optional[str] = Header(default=None)):
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token and verify_token(token):
        return Response(status_code=204)
    return JSONResponse(
        status_code=401,
        content={"error": "Unauthorized", "message": "Invalid or expired download token."},
    )
