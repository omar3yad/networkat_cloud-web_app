from extensions import db
from models.system_user import SystemUser
from werkzeug.security import generate_password_hash


class UserRepository:

    # ========== SystemUser Operations (Admins) ==========
    @staticmethod
    def get_by_username(username):
        return SystemUser.query.filter_by(username=username).first()

    @staticmethod
    def get_by_id(user_id):
        return SystemUser.query.get(user_id)

    @staticmethod
    def create(username, email, full_name, raw_password, role="admin", is_active=True):
        hashed_password = generate_password_hash(raw_password)
        user = SystemUser(
            username=username,
            email=email,
            full_name=full_name,
            password_hash=hashed_password,
            role=role,
            is_active=is_active
        )
        db.session.add(user)
        db.session.commit()
        return user

    @staticmethod
    def count():
        return SystemUser.query.count()