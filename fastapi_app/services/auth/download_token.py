"""
Short-lived, stateless download token for the peer-installer tarball.

The bootstrap script (install.sh) signs the customer in to the portal BEFORE it
downloads https://api.networkat.cloud/peer-installer.tar.gz. That 200 login
response now carries a `download_token` minted here; install.sh presents it as a
Bearer header on the tarball request, and nginx `auth_request` calls
/api/v1/auth/verify-download (which uses verify_token below) to gate the file.

The token is a signed HMAC blob — no DB, no nonce store, nothing to persist —
mirroring dependencies.py's `verify_api_key` philosophy. A 10-minute TTL is
enough: install.sh's download window is seconds, and a resumed install
(re-running the same curl|bash line, supported for 15 min) simply signs in again
and mints a fresh one, so single-use state buys nothing and only complicates
resume.

Layout:  base64url(payload) + "." + base64url(hmac_sha256(_SECRET, payload))
         payload = "<username>|<expiry_epoch>"
"""
import hmac
import hashlib
import time
import base64

# Module-level constant, same pattern as API_SECRET_KEY in dependencies.py
# (supervisord passes no environment to the uvicorn `api` program, so an env var
# would never be read). Random 64-hex, deliberately independent of
# API_SECRET_KEY — that value is leaked in /docs (see fastapi_app/main.py
# license_info) and must never be reused as a signing secret.
_SECRET = b"862382397ab3debbcaa43d4ebab2d567153b492414cfefe1af3681527273abe4"

# 10 minutes. install.sh's download happens within seconds of the login; a
# longer window only widens the replay surface for no benefit.
_TTL_SECONDS = 600


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(username: str) -> str:
    """Mint a signed download token valid for _TTL_SECONDS."""
    payload = f"{username}|{int(time.time()) + _TTL_SECONDS}".encode()
    sig = hmac.new(_SECRET, payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(sig)}"


def verify_token(token: str) -> bool:
    """True iff the token's signature is valid AND it has not expired."""
    try:
        p_b64, s_b64 = token.split(".", 1)
        payload = _unb64(p_b64)
        expected = hmac.new(_SECRET, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(s_b64)):
            return False
        _user, expiry = payload.decode().rsplit("|", 1)
        return int(expiry) > int(time.time())
    except Exception:
        return False
