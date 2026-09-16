# /opt/networkat_sdwan/core/web_app/utils/two_factor.py
import io
import json
import base64
import secrets
import hashlib
import pyotp
import qrcode


def generate_totp_secret() -> str:
    """Generate a random Base32 TOTP secret key."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, username: str, issuer: str = "Networkat") -> str:
    """Generate the standard otpauth URI for Authenticator apps."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def generate_qr_base64(uri: str) -> str:
    """Generate a Base64 encoded PNG image data URL for a given URI."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#1e2a41", back_color="white")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_bytes = buffered.getvalue()
    b64_str = base64.b64encode(img_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64_str}"


def verify_totp_code(secret: str, code: str) -> bool:
    """
    Verify a 6-digit TOTP code against a secret key.
    valid_window=1 allows 1 step before/after (±30s) to account for slight clock drifts.
    """
    if not secret or not code:
        return False
    clean_code = str(code).strip().replace(" ", "").replace("-", "")
    if not clean_code.isdigit() or len(clean_code) != 6:
        return False
    try:
        totp = pyotp.TOTP(secret)
        return bool(totp.verify(clean_code, valid_window=1))
    except Exception:
        return False


def _hash_code(code: str) -> str:
    """Hash a single recovery code with SHA-256 for secure storage."""
    normalized = code.strip().upper().replace(" ", "").replace("-", "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_recovery_codes(count: int = 8) -> list[str]:
    """
    Generate a list of formatted alphanumeric recovery codes.
    Format: XXXX-XXXX (e.g., A7B2-9F1C)
    """
    codes = []
    for _ in range(count):
        part1 = secrets.token_hex(2).upper()
        part2 = secrets.token_hex(2).upper()
        codes.append(f"{part1}-{part2}")
    return codes


def hash_recovery_codes(codes_list: list[str]) -> str:
    """Hash a list of recovery codes and return as a JSON-encoded string."""
    hashed_list = [_hash_code(c) for c in codes_list]
    return json.dumps(hashed_list)


def verify_and_consume_recovery_code(entered_code: str, hashed_codes_json: str | None) -> tuple[bool, str | None]:
    """
    Verify an entered recovery code against the stored JSON list of hashes.
    If valid, consumes (removes) the code and returns (True, updated_json).
    Otherwise returns (False, unchanged_json).
    """
    if not entered_code or not hashed_codes_json:
        return False, hashed_codes_json

    try:
        hashes = json.loads(hashed_codes_json)
        if not isinstance(hashes, list):
            return False, hashed_codes_json
    except Exception:
        return False, hashed_codes_json

    entered_hash = _hash_code(entered_code)

    if entered_hash in hashes:
        hashes.remove(entered_hash)
        return True, json.dumps(hashes)

    return False, hashed_codes_json
