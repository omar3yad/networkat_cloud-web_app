from datetime import datetime
from config.database import db
from models.base import BaseModel
import uuid
from sqlalchemy.dialects.postgresql import UUID 
class Client(BaseModel):
    __tablename__ = "clients"

    user_id = db.Column(
            UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4
        )

    username = db.Column(
        db.String(32),
        nullable=False,
        unique=True
    )

    password_hashed = db.Column(
        db.Text,
        nullable=False
    )

    client_name = db.Column(
        db.String(100),
        nullable=False
    )

    client_company_name = db.Column(
        db.String(150),
        nullable=True
    )

    netbird_group_id = db.Column(
        db.String(100),
        nullable=True,
        unique=True
    )

    client_email = db.Column(
        db.String(255),
        nullable=False,
        unique=True
    )

    client_phone_number = db.Column(
        db.String(20),
        nullable=True,
        unique=True
    )

    client_country = db.Column(
        db.String(100),
        nullable=True
    )

    subscription = db.Column(
        db.String(50),
        default="free"
    )

    active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    last_login = db.Column(
        db.DateTime(timezone=True),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow
    )

    # --- Relationships ---
    tokens = db.relationship(
        "Token",
        back_populates="client",
        cascade="all, delete-orphan"
    )

    edges = db.relationship(
        "Edge",
        back_populates="client",
        cascade="all, delete-orphan"
    )

    firewall_rules = db.relationship(
        "FirewallRule",
        back_populates="client",
        cascade="all, delete-orphan"
    )

    dns_rules = db.relationship(
        "DNSRule",
        back_populates="client",
        cascade="all, delete-orphan"
    )

    policies = db.relationship(
        "Policy",
        back_populates="client",
        cascade="all, delete-orphan"
    )