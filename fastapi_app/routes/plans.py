# /opt/networkat_sdwan/core/web_app/fastapi_app/routes/plans.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from fastapi_app.dependencies import get_db
from fastapi_app.schemas.plans import (
    PlanCreate,
    PlanUpdate,
    PlanListResponse,
    PlanSingleResponse,
    PlanToggleResponse,
    PlanDeleteResponse,
    TrialDurationUpdate,
    TrialDurationResponse,
)
from fastapi_app.services.plans_service import PlansService

router = APIRouter(
    prefix="/api/v2/plans",
    tags=["Subscription Plans"]
)


@router.get("", response_model=PlanListResponse, summary="List all subscription plans")
def list_plans(db: Session = Depends(get_db)):
    plans = PlansService.get_all_plans(db)
    return {
        "success": True,
        "plans": [p.to_dict() for p in plans]
    }


@router.get("/trial-duration", response_model=TrialDurationResponse, summary="Get global free trial duration in days")
def get_trial_duration(db: Session = Depends(get_db)):
    days = PlansService.get_trial_duration(db)
    return {
        "success": True,
        "trial_days": days
    }


@router.put("/trial-duration", response_model=TrialDurationResponse, summary="Update global free trial duration in days")
def set_trial_duration(payload: TrialDurationUpdate, db: Session = Depends(get_db)):
    days = PlansService.set_trial_duration(db, payload.trial_days)
    return {
        "success": True,
        "trial_days": days
    }


@router.get("/{plan_id}", response_model=PlanSingleResponse, summary="Get single subscription plan by ID")
def get_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = PlansService.get_plan_by_id(db, plan_id)
    return {
        "success": True,
        "plan": plan.to_dict()
    }


@router.post("", response_model=PlanSingleResponse, status_code=status.HTTP_201_CREATED, summary="Create a new subscription plan")
def create_plan(payload: PlanCreate, db: Session = Depends(get_db)):
    plan = PlansService.create_plan(db, payload)
    return {
        "success": True,
        "plan": plan.to_dict()
    }


@router.put("/{plan_id}", response_model=PlanSingleResponse, summary="Update an existing subscription plan")
def update_plan(plan_id: int, payload: PlanUpdate, db: Session = Depends(get_db)):
    plan = PlansService.update_plan(db, plan_id, payload)
    return {
        "success": True,
        "plan": plan.to_dict()
    }


@router.delete("/{plan_id}", response_model=PlanDeleteResponse, summary="Delete a subscription plan")
def delete_plan(plan_id: int, db: Session = Depends(get_db)):
    PlansService.delete_plan(db, plan_id)
    return {
        "success": True,
        "message": "Plan deleted"
    }


@router.post("/{plan_id}/toggle", response_model=PlanToggleResponse, summary="Toggle subscription plan active status")
def toggle_plan(plan_id: int, db: Session = Depends(get_db)):
    is_active = PlansService.toggle_plan_status(db, plan_id)
    return {
        "success": True,
        "is_active": is_active
    }
