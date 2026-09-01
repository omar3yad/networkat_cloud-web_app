from repositories.user_repository import UserRepository
from utils.password import verify_password, hash_password
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

        session['admin_logged_in'] = True
        session['admin_user_id'] = str(user.id)
        session['admin_username'] = user.username
        return True, "Authenticated successfully"
        
    def logout(self):
        session.clear()

    def seed_default_admin(self):
        if self.user_repo.count() == 0:
            pwd_hash = hash_password("admin123")
            # تعديل password_hash إلى password_hashed
            self.user_repo.create(
                username="admin",
                email="admin@networkat.com",
                full_name="System Administrator",
                password_hashed=pwd_hash,  # <-- التعديل هنا
                role="admin"
            )