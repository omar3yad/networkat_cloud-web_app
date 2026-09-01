"""
Public Authentication API — Client Setup Key Retrieval.

This router is intentionally excluded from the global API key dependency
so that clients can call it without a Bearer token.
It is registered separately in main.py WITHOUT the auth_dependency.
"""
import time
import logging
from threading import Lock

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash

from fastapi_app.database import SessionLocal
from fastapi_app.schemas.auth import SetupKeyRequest, SetupKeyResponse, AccountMeta, ClientSetupKeyInfo, ErrorResponse

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
# GET /api/v1/auth/setup-key
# ---------------------------------------------------------------------------
@router.post(
    "/setup-key",
    response_model=SetupKeyResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve NetBird Setup Key",
    description=(
        "Authenticate with your Networkat client username and password "
        "to obtain the active NetBird Setup Key assigned to your account. "
        "Use this key to enroll new devices into your private SD-WAN network."
    ),
    responses={
        200: {"model": SetupKeyResponse,  "description": "Setup key retrieved successfully."},
        400: {"model": ErrorResponse,     "description": "Missing or invalid request fields."},
        401: {"model": ErrorResponse,     "description": "Invalid credentials or account disabled."},
        404: {"model": ErrorResponse,     "description": "No active setup key found for this account."},
        415: {"model": ErrorResponse,     "description": "Content-Type must be application/json."},
        429: {"model": ErrorResponse,     "description": "Too many requests — rate limit exceeded."},
        500: {"model": ErrorResponse,     "description": "Unexpected server error."},
    },
)
async def get_setup_key(payload: SetupKeyRequest, request: Request):
    """
    **Secure endpoint** — authenticate as a client and retrieve your NetBird Setup Key.

    ### Flow
    1. Validate that `username` and `password` are present.
    2. Apply per-IP sliding-window rate limiting (5 req / 60 s).
    3. Look up the client by username and verify the password hash.
    4. Fetch the first active Setup Key linked to the account.
    5. Attach non-sensitive account metadata to the response.
    6. Log the access and return the result.

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
                "message": (
                    f"Maximum {_MAX_HITS} attempts per {_WINDOW_SEC} seconds exceeded. "
                    "Please wait and try again."
                ),
            },
        )

    username = payload.username.strip()
    password = payload.password

    # ── 2. Database session ────────────────────────────────────────────────
    db: Session = SessionLocal()
    try:
        from sqlalchemy import text

        # ── 3. Look up client (fetch all needed columns in one query) ──────
        row = db.execute(
            text("""
                SELECT
                    user_id,
                    password_hashed,
                    active,
                    client_name,
                    client_company_name,
                    client_email,
                    client_country,
                    subscription,
                    created_at
                FROM clients
                WHERE username = :u
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
            logger.warning(f"[setup-key-api] Unknown username='{username}' ip={ip}")
            return JSONResponse(status_code=401, content=_INVALID)

        (
            user_id, password_hashed, active,
            client_name, client_company_name, client_email,
            client_country, subscription, created_at
        ) = row

        if not active:
            logger.warning(f"[setup-key-api] Disabled account username='{username}' ip={ip}")
            return JSONResponse(status_code=401, content=_INVALID)

        if not check_password_hash(password_hashed, password):
            logger.warning(f"[setup-key-api] Bad password for username='{username}' ip={ip}")
            return JSONResponse(status_code=401, content=_INVALID)

        # ── 4. Fetch all setup keys (active and inactive) ──────────────────
        tokens = db.execute(
            text(
                "SELECT token, is_active FROM tokens "
                "WHERE client_id = :uid "
                "ORDER BY ctid"
            ),
            {"uid": str(user_id)},
        ).fetchall()

        if not tokens:
            logger.error(f"[setup-key-api] No tokens found in database for username='{username}' ip={ip}")
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Not Found",
                    "message": "No setup key found for this account. Please contact your administrator.",
                },
            )

        # Get first active token for top-level setup_key field. Fallback to first token if none active.
        active_tokens = [t[0] for t in tokens if t[1]]
        setup_key = active_tokens[0] if active_tokens else tokens[0][0]

        # ── 5. Fetch all NetBird Setup Keys from NetBird Server ────────────
        netbird_keys = []
        try:
            from fastapi_app.services.netbird.setup_keys import NetBirdSetupKeyService
            nb_res = NetBirdSetupKeyService.list_setup_keys()
            if isinstance(nb_res, list):
                netbird_keys = nb_res
            else:
                logger.error(f"[setup-key-api] NetBird API returned error or non-list: {nb_res}")
        except Exception as exc:
            logger.error(f"[setup-key-api] Failed to list setup keys from NetBird: {exc}")

        # Map and match setup keys
        client_setup_keys_info = []
        for t in tokens:
            token_val = t[0]
            db_prefix = token_val[:5]
            
            # Find matching key from NetBird
            matched_nb_key = None
            for nb_key in netbird_keys:
                nb_key_val = nb_key.get("key", "")
                nb_key_clean = nb_key_val.replace("*", "")
                if nb_key_clean and (db_prefix.startswith(nb_key_clean) or nb_key_clean.startswith(db_prefix)):
                    matched_nb_key = nb_key
                    break
            
            if matched_nb_key:
                valid = matched_nb_key.get("valid", True)
                used_times = matched_nb_key.get("used_times", 0)
                usage_limit = matched_nb_key.get("usage_limit", 0)
                remaining_uses = (usage_limit - used_times) if usage_limit > 0 else None
                client_setup_keys_info.append(
                    ClientSetupKeyInfo(
                        valid=valid,
                        used_times=used_times,
                        usage_limit=usage_limit,
                        remaining_uses=remaining_uses,
                        key=token_val
                    )
                )
            else:
                # Fallback to local DB status if NetBird query failed or doesn't match
                client_setup_keys_info.append(
                    ClientSetupKeyInfo(
                        valid=t[1],
                        used_times=0,
                        usage_limit=0,
                        remaining_uses=None,
                        key=token_val
                    )
                )

        # ── 6. Build account metadata ──────────────────────────────────────
        member_since = (
            created_at.strftime("%Y-%m-%dT%H:%M:%S")
            if created_at else None
        )

        account_meta = AccountMeta(
            full_name    = client_name,
            company_name = client_company_name,
            email        = client_email,
            country      = client_country,
            subscription = subscription,
            member_since = member_since,
            active_keys  = len(active_tokens),
        )

        # ── 7. Audit log ───────────────────────────────────────────────────
        logger.info(f"[setup-key-api] ✅ Key retrieved — username='{username}' ip={ip}")

        # ── 8. Return ──────────────────────────────────────────────────────
        return SetupKeyResponse(
            username  = username,
            account   = account_meta,
            setup_keys = client_setup_keys_info
        )

    except Exception as exc:
        logger.error(f"[setup-key-api] Internal error for username='{username}': {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": "An unexpected error occurred. Please try again later.",
            },
        )
    finally:
        db.close()


