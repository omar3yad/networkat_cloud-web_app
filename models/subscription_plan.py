# /opt/networkat_sdwan/core/web_app/models/subscription_plan.py
from datetime import datetime
from config.database import db
from models.base import BaseModel


class SubscriptionPlan(BaseModel):

    __tablename__ = "subscription_plans"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(
        db.String(50),
        nullable=False,
        unique=True
    )
    # مثال: "starter", "pro", "enterprise"

    display_name = db.Column(
        db.String(100),
        nullable=False
    )
    # مثال: "Starter Plan", "Professional", "Enterprise"

    allowed_peers_count = db.Column(
        db.Integer,
        nullable=False
    )
    # الحد الأقصى للأجهزة المسموح بها في هذه الخطة

    billing_cycle = db.Column(
        db.String(20),
        nullable=False,
        default="monthly,yearly"
    )
    # القيم المسموحة مفصولة بفاصلة: "monthly", "yearly", "monthly,yearly"

    price_monthly = db.Column(
        db.Numeric(10, 2),
        nullable=True
    )

    price_annual = db.Column(
        db.Numeric(10, 2),
        nullable=True
    )

    is_active = db.Column(
        db.Boolean,
        default=True
    )
    # لإخفاء خطط قديمة بدون حذفها

    def __repr__(self):
        return f"<SubscriptionPlan {self.name} (limit={self.allowed_peers_count})>"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "allowed_peers_count": self.allowed_peers_count,
            "billing_cycle": self.billing_cycle.split(",") if self.billing_cycle else [],
            "price_monthly": float(self.price_monthly) if self.price_monthly is not None else None,
            "price_annual": float(self.price_annual) if self.price_annual is not None else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

