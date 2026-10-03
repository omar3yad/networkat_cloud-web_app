# /opt/networkat_sdwan/core/web_app/fastapi_app/services/plans_service.py
import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException, status

from models.subscription_plan import SubscriptionPlan
from models.client import Client
from models.system_setting import SystemSetting
from fastapi_app.schemas.plans import PlanCreate, PlanUpdate

logger = logging.getLogger(__name__)


class PlansService:

    @staticmethod
    def get_trial_duration(db: Session) -> int:
        """Fetch global trial period duration in days."""
        setting = db.query(SystemSetting).filter(SystemSetting.key == "trial.duration_days").first()
        if setting and setting.value:
            try:
                return int(setting.value)
            except ValueError:
                pass
        return 7

    @staticmethod
    def set_trial_duration(db: Session, days: int) -> int:
        """Update global trial period duration in days."""
        if days < 1 or days > 365:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Trial duration must be between 1 and 365 days"
            )
        setting = db.query(SystemSetting).filter(SystemSetting.key == "trial.duration_days").first()
        if not setting:
            setting = SystemSetting(
                key="trial.duration_days",
                value=str(days),
                value_type="integer",
                label="Free trial duration (days)",
                description="Number of days granted for new client free trials",
                category="Trial"
            )
            db.add(setting)
        else:
            setting.value = str(days)

        try:
            db.commit()
            return days
        except Exception as e:
            db.rollback()
            logger.error("Error setting trial duration in DB: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save trial duration"
            )

    @staticmethod
    def get_all_plans(db: Session) -> List[SubscriptionPlan]:
        """Fetch all subscription plans ordered by allowed peers limit."""
        return db.query(SubscriptionPlan).order_by(SubscriptionPlan.allowed_peers_count.asc()).all()

    @staticmethod
    def get_plan_by_id(db: Session, plan_id: int) -> SubscriptionPlan:
        """Fetch a single plan by its ID or raise 404."""
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan not found"
            )
        return plan

    @staticmethod
    def get_plan_by_name(db: Session, name: str) -> Optional[SubscriptionPlan]:
        """Fetch a plan by internal unique slug name."""
        return db.query(SubscriptionPlan).filter(SubscriptionPlan.name == name).first()

    @staticmethod
    def create_plan(db: Session, data: PlanCreate) -> SubscriptionPlan:
        """Create a new subscription plan with uniqueness check."""
        existing = db.query(SubscriptionPlan).filter(SubscriptionPlan.name == data.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A plan with this name already exists"
            )

        plan = SubscriptionPlan(
            name=data.name,
            display_name=data.display_name.strip(),
            allowed_peers_count=data.allowed_peers_count,
            billing_cycle=data.billing_cycle,
            price_monthly=data.price_monthly,
            price_annual=data.price_annual,
            is_active=data.is_active,
        )

        try:
            db.add(plan)
            db.commit()
            db.refresh(plan)
            return plan
        except Exception as e:
            db.rollback()
            logger.error("Error creating subscription plan in DB: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create subscription plan"
            )

    @staticmethod
    def update_plan(db: Session, plan_id: int, data: PlanUpdate) -> SubscriptionPlan:
        """Update existing plan properties."""
        plan = PlansService.get_plan_by_id(db, plan_id)

        if data.display_name is not None:
            plan.display_name = data.display_name.strip()

        if data.allowed_peers_count is not None:
            plan.allowed_peers_count = data.allowed_peers_count

        if data.billing_cycle is not None:
            plan.billing_cycle = data.billing_cycle

        if data.price_monthly is not None:
            plan.price_monthly = data.price_monthly

        if data.price_annual is not None:
            plan.price_annual = data.price_annual

        if data.is_active is not None:
            plan.is_active = data.is_active

        try:
            db.commit()
            db.refresh(plan)
            return plan
        except Exception as e:
            db.rollback()
            logger.error("Error updating subscription plan %s in DB: %s", plan_id, e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update subscription plan"
            )

    @staticmethod
    def delete_plan(db: Session, plan_id: int) -> None:
        """Delete plan after ensuring no active customers are assigned to it."""
        plan = PlansService.get_plan_by_id(db, plan_id)

        # Check customer usage
        customer_count = db.query(func.count(Client.user_id)).filter(Client.plan_id == plan_id).scalar() or 0
        if customer_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete: {customer_count} customer(s) are currently on this plan"
            )

        try:
            db.delete(plan)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("Error deleting subscription plan %s in DB: %s", plan_id, e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete subscription plan"
            )

    @staticmethod
    def toggle_plan_status(db: Session, plan_id: int) -> bool:
        """Toggle is_active status of a plan."""
        plan = PlansService.get_plan_by_id(db, plan_id)
        plan.is_active = not plan.is_active

        try:
            db.commit()
            db.refresh(plan)
            return plan.is_active
        except Exception as e:
            db.rollback()
            logger.error("Error toggling subscription plan %s in DB: %s", plan_id, e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update plan status"
            )
