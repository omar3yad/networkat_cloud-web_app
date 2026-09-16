import bcrypt
import hashlib
import hmac


def hash_password(password: str) -> str:
    """Hash a password using bcrypt with salt rounds=12."""
    if isinstance(password, str):
        pwd_bytes = password.encode('utf-8')
    else:
        pwd_bytes = password
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt(rounds=12)).decode('utf-8')


def is_bcrypt_hash(stored_hash: str) -> bool:
    """Check if the string is a valid bcrypt hash."""
    if not stored_hash or not isinstance(stored_hash, str):
        return False
    return stored_hash.startswith(('$2b$', '$2a$', '$2y$'))


def verify_password(password: str, stored_hash: str) -> bool:
    """
    Verify a password against stored hash.
    Supports both new bcrypt hashes ($2b$...) and legacy SHA-256 (salt:hash).
    """
    if not stored_hash or not password:
        return False

    try:
        if is_bcrypt_hash(stored_hash):
            pwd_bytes = password.encode('utf-8') if isinstance(password, str) else password
            hash_bytes = stored_hash.encode('utf-8') if isinstance(stored_hash, str) else stored_hash
            return bcrypt.checkpw(pwd_bytes, hash_bytes)
        elif ':' in stored_hash:
            salt, hash_value = stored_hash.split(':', 1)
            calculated_hash = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
            return hmac.compare_digest(hash_value, calculated_hash)
        return False
    except Exception:
        return False


def needs_rehash(stored_hash: str) -> bool:
    """Check if stored hash uses legacy format (SHA-256) instead of bcrypt."""
    if not stored_hash:
        return False
    return not is_bcrypt_hash(stored_hash)
