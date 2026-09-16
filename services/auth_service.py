import time
from repositories.user_repository import UserRepository
from utils.password import verify_password, hash_password
from utils.two_factor import (
    generate_totp_secret,
    get_totp_uri,
    generate_qr_base64,
    verify_totp_code,
    generate_recovery_codes,
    hash_recovery_codes,
    verify_and_consume_recovery_code,
)
from utils.email import send_2fa_email_otp
from flask import session


class AuthService:

    def __init__(self):
        self.user_repo = UserRepository()

    def authenticate(self, username, password):
        user = self.user_repo.get_by_username(username)
        if not user:
            print(f"[DEBUG AUTH] User '{username}' was NOT found in DB.")
            return False, "Invalid credentials"

        if not user.is_active:
            print(f"[DEBUG AUTH] User '{username}' is deactivated.")
            return False, "User account is deactivated"

        user_password = getattr(user, 'password_hashed', getattr(user, 'password_hash', None))
        print(f"[DEBUG AUTH] Stored hash found: {bool(user_password)}")

        if not user_password or not verify_password(password, user_password):
            print(f"[DEBUG AUTH] Password verification failed for '{username}'.")
            return False, "Invalid credentials"

        # Check if 2FA is enabled for this admin / staff user
        if getattr(user, 'is_2fa_enabled', False):
            session.clear()
            session['pending_2fa'] = {
                'type': 'admin',
                'user_id': user.id,
                'username': user.username,
                'email': user.email,
                'method': getattr(user, 'two_fa_method', 'totp') or 'totp',
                'role': getattr(user, 'role', 'admin') or 'admin',
                'fullname': getattr(user, 'full_name', user.username) or user.username,
                'created_at': time.time(),
                'attempts': 0
            }
            return True, "2fa_required"

        session['admin_logged_in'] = True
        session['admin_user_id'] = str(user.id)
        session['admin_username'] = user.username
        session['admin_role'] = getattr(user, 'role', 'admin') or 'admin'
        session['admin_fullname'] = getattr(user, 'full_name', user.username) or user.username
        return True, "Authenticated successfully"

    def complete_2fa_login(self, user):
        """Finalize login after successful 2FA verification."""
        session.pop('pending_2fa', None)
        session.pop('pending_2fa_email_otp', None)
        session['admin_logged_in'] = True
        session['admin_user_id'] = str(user.id)
        session['admin_username'] = user.username
        session['admin_role'] = getattr(user, 'role', 'admin') or 'admin'
        session['admin_fullname'] = getattr(user, 'full_name', user.username) or user.username
        
    def logout(self):
        session.clear()

    def seed_default_admin(self):
        if self.user_repo.count() == 0:
            pwd_hash = hash_password("admin123")
            self.user_repo.create(
                username="admin",
                email="admin@networkat.com",
                full_name="System Administrator",
                password_hashed=pwd_hash,
                role="admin"
            )