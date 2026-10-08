# /opt/networkat_sdwan/core/web_app/fastapi_app/routes/admin/customers.py
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from fastapi_app.dependencies import get_db
from fastapi_app.schemas.admin.customers import (
    CustomerListResponse,
    CustomerDetailResponse,
    CustomerStatusUpdateSchema,
    CustomerPlanUpdateSchema,
    CustomerResetPasswordSchema,
    CustomerActionResponse,
)
from fastapi_app.services.admin.customers_service import AdminCustomersService

router = APIRouter(
    prefix="/api/v2/admin/customers",
    tags=["Admin - Customers Management"]
)


@router.get("", response_model=CustomerListResponse, summary="List all customers with search and pagination")
def list_customers(
    search: Optional[str] = Query(default=None, description="Search by name, username, email, or company"),
    status: Optional[str] = Query(default=None, description="Filter by status (active, grace_period, limit_control, inactive)"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=50, ge=1, le=200, description="Items per page"),
    db: Session = Depends(get_db)
):
    """
    Retrieves paginated customers list with device statistics and subscription status.
    """
    return AdminCustomersService.list_customers(
        db=db,
        search=search,
        status_filter=status,
        page=page,
        per_page=per_page
    )


@router.get("/{customer_id}", response_model=CustomerDetailResponse, summary="Get customer profile, subscription, and peers")
def get_customer(customer_id: str, db: Session = Depends(get_db)):
    """
    Retrieves full profile for a specific customer, including current plan, quota, and connected peers.
    """
    return AdminCustomersService.get_customer_detail(db=db, customer_id=customer_id)


@router.post("/{customer_id}/status", response_model=CustomerActionResponse, summary="Change customer subscription status")
def update_status(customer_id: str, payload: CustomerStatusUpdateSchema, db: Session = Depends(get_db)):
    """
    Transitions customer subscription state: active, grace_period, limit_control, or inactive.
    """
    return AdminCustomersService.update_customer_status(db=db, customer_id=customer_id, new_status=payload.status)


@router.post("/{customer_id}/plan", response_model=CustomerActionResponse, summary="Upgrade or modify customer plan and quota")
def update_plan(customer_id: str, payload: CustomerPlanUpdateSchema, db: Session = Depends(get_db)):
    """
    Updates client subscription plan, peer limits, billing cycle, or renewal dates.
    """
    return AdminCustomersService.update_customer_plan(
        db=db,
        customer_id=customer_id,
        plan_id=payload.plan_id,
        billing_cycle=payload.billing_cycle,
        allowed_peers_count=payload.allowed_peers_count,
        renewal_date=payload.renewal_date,
        is_trial=payload.is_trial,
        status=payload.status
    )


@router.post("/{customer_id}/reset-password", response_model=CustomerActionResponse, summary="Reset customer or user password")
def reset_password(customer_id: str, payload: CustomerResetPasswordSchema, db: Session = Depends(get_db)):
    """
    Securely resets customer password.
    """
    return AdminCustomersService.reset_password(
        db=db,
        customer_id=customer_id,
        password=payload.password,
        user_id=payload.user_id
    )
