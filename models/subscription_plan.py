# /opt/networkat_sdwan/core/web_app/models/subscription_plan.py
from datetime import datetime
from config.database import db
from models.base import BaseModel


class SubscriptionPlan(BaseModel):
    """
    جدول الخطط الثابتة — يحدد peer_limit و billing_cycle لكل خطة.
    الأدمن يضيف/يعدل الخطط، والعميل يُربط بخطة عبر Client.plan_id.
    """
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

    peer_limit = db.Column(
        db.Integer,
        nullable=False
    )
    # الحد الأقصى للأجهزة المسموح بها في هذه الخطة

    billing_cycles = db.Column(
        db.String(20),
        nullable=False,
        default="monthly,yearly"
    )
    # القيم المسموحة مفصولة بفاصلة: "monthly", "yearly", "monthly,yearly"

    price_monthly = db.Column(
        db.Numeric(10, 2),
        nullable=True
    )

    price_yearly = db.Column(
        db.Numeric(10, 2),
        nullable=True
    )

    is_active = db.Column(
        db.Boolean,
        default=True
    )
    # لإخفاء خطط قديمة بدون حذفها

    def __repr__(self):
        return f"<SubscriptionPlan {self.name} (limit={self.peer_limit})>"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "peer_limit": self.peer_limit,
            "billing_cycles": self.billing_cycles.split(",") if self.billing_cycles else [],
            "price_monthly": float(self.price_monthly) if self.price_monthly is not None else None,
            "price_yearly": float(self.price_yearly) if self.price_yearly is not None else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
