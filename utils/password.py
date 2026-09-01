import secrets
import hashlib


def hash_password(password):
    salt = secrets.token_hex(16)
    hash_value = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hash_value}"


def verify_password(password, stored_hash):
    try:
        salt, hash_value = stored_hash.split(':')
        return hash_value == hashlib.sha256((salt + password).encode()).hexdigest()
    except Exception:
        return False
