from extensions import db
from models.system_user import SystemUser
from utils.password import hash_password


class UserRepository:

    # ========== SystemUser Operations (Staff & Admins) ==========
    @staticmethod
    def get_by_username(username):
        return SystemUser.query.filter_by(username=username).first()

    @staticmethod
    def get_by_email(email):
        return SystemUser.query.filter_by(email=email).first()

    @staticmethod
    def get_by_id(user_id):
        return SystemUser.query.get(user_id)

    @staticmethod
    def get_all_desc():
        return SystemUser.query.order_by(SystemUser.created_at.desc()).all()

    @staticmethod
    def create(username, email, full_name, raw_password, role="sales", is_active=True):
        hashed_password = hash_password(raw_password)
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
    def update(user, email=None, full_name=None, role=None, is_active=None):
        if email is not None:
            user.email = email
        if full_name is not None:
            user.full_name = full_name
        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active
        db.session.commit()
        return user

    @staticmethod
    def update_password(user, raw_password):
        user.password_hash = hash_password(raw_password)
        db.session.commit()
        return user

    @staticmethod
    def toggle_status(user):
        user.is_active = not user.is_active
        db.session.commit()
        return user.is_active

    @staticmethod
    def delete(user):
        db.session.delete(user)
        db.session.commit()
        return True

    @staticmethod
    def count():
        return SystemUser.query.count()