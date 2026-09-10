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

    # --- Subscription Lifecycle Fields ---
    plan_id = db.Column(
        db.Integer,
        db.ForeignKey("subscription_plans.id"),
        nullable=True
    )

    subscription_status = db.Column(
        db.String(20),
        nullable=False,
        default="active"
        # القيم: 'active', 'grace_period', 'limit_control', 'inactive'
    )

    billing_cycle = db.Column(
        db.String(10),
        nullable=True
        # القيم: 'monthly', 'yearly'
    )

    renewal_date = db.Column(
        db.DateTime(timezone=True),
        nullable=True
    )

    grace_expires_at = db.Column(
        db.DateTime(timezone=True),
        nullable=True
    )

    renewal_notified_at = db.Column(
        db.DateTime(timezone=True),
        nullable=True
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
    plan = db.relationship(
        "SubscriptionPlan",
        backref="clients"
    )

    tokens = db.relationship(
        "Token",
        back_populates="client",
        cascade="all, delete-orphan"
    )

    # --- Subscription Helper Properties ---
    @property
    def is_subscription_active(self):
        """Returns True if client has full control (active or grace_period)."""
        return self.subscription_status in ("active", "grace_period")

    @property
    def is_subscription_readonly(self):
        """Returns True if client is in limit_control (read-only mode)."""
        return self.subscription_status == "limit_control"

    @property
    def is_subscription_inactive(self):
        """Returns True if client subscription is inactive."""
        return self.subscription_status == "inactive"

    @property
    def allowed_peers_count(self):
        """Returns allowed peer count from associated plan, defaulting to Starter (5) if no plan."""
        if self.plan:
            return self.plan.allowed_peers_count
        return 5