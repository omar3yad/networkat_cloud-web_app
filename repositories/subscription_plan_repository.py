# /opt/networkat_sdwan/core/web_app/repositories/subscription_plan_repository.py
from models.subscription_plan import SubscriptionPlan
from config.database import db


class SubscriptionPlanRepository:

    def get_all(self):
        return SubscriptionPlan.query.all()

    def get_all_active(self):
        return SubscriptionPlan.query.filter_by(is_active=True).all()

    def get_by_id(self, plan_id):
        if not plan_id:
            return None
        return SubscriptionPlan.query.get(plan_id)

    def get_by_name(self, name):
        if not name:
            return None
        return SubscriptionPlan.query.filter_by(name=name).first()

    def create(self, name, display_name, allowed_peers_count, billing_cycle="monthly,yearly", price_monthly=None, price_annual=None, is_active=True):
        plan = SubscriptionPlan(
            name=name,
            display_name=display_name,
            allowed_peers_count=allowed_peers_count,
            billing_cycle=billing_cycle,
            price_monthly=price_monthly,
            price_annual=price_annual,
            is_active=is_active
        )
        db.session.add(plan)
        db.session.commit()
        return plan
