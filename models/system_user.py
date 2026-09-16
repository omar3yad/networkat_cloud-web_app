from datetime import datetime

from config.database import db


class SystemUser(db.Model):
    __tablename__ = "system_users"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    username = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
        index=True
    )

    email = db.Column(
        db.String(255),
        unique=True,
        nullable=False,
        index=True
    )

    full_name = db.Column(
        db.String(150),
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    role = db.Column(
        db.String(30),
        nullable=False,
        default="admin"
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    totp_secret = db.Column(
        db.String(64),
        nullable=True
    )

    is_2fa_enabled = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    recovery_codes = db.Column(
        db.Text,
        nullable=True
    )

    two_fa_method = db.Column(
        db.String(20),
        nullable=False,
        default="totp"
    )

    last_login = db.Column(
        db.DateTime,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<SystemUser {self.username}>"