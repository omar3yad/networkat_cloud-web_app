# /opt/networkat_sdwan/core/web_app/tests/test_admin_customers.py
"""
Unit and integration tests for Phase 3: Customers & Subscriptions Management (FastAPI).
Covers:
- Listing customers with search and status filtering (list_customers)
- Retrieving customer details, subscription info, and peers (get_customer)
- Updating customer subscription status state machine (update_status)
- Upgrading or changing customer plan and peer quotas (update_plan)
- Resetting customer password with validation (reset_password)
- 404 handling for nonexistent customer records
"""
import pytest
from fastapi import HTTPException
from fastapi_app.database import SessionLocal
from models.client import Client
from models.subscription_plan import SubscriptionPlan
from fastapi_app.schemas.admin.customers import (
    CustomerStatusUpdateSchema,
    CustomerPlanUpdateSchema,
    CustomerResetPasswordSchema,
)
from fastapi_app.routes.admin.customers import (
    list_customers,
    get_customer,
    update_status,
    update_plan,
    reset_password,
)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_customer(db_session):
    client = db_session.query(Client).first()
    assert client is not None, "At least one client should exist in DB"
    return str(client.user_id)


def test_admin_customers_list(db_session):
    res = list_customers(search=None, status=None, page=1, per_page=10, db=db_session)
    assert res["success"] is True
    assert "total" in res
    assert "customers" in res
    assert isinstance(res["customers"], list)
    if res["customers"]:
        c = res["customers"][0]
        assert "id" in c
        assert "username" in c
        assert "status" in c
        assert "peers_count" in c


def test_admin_customers_search_and_filter(db_session, sample_customer):
    client = db_session.query(Client).filter_by(user_id=sample_customer).first()
    res = list_customers(search=client.username, status=None, page=1, per_page=10, db=db_session)
    assert res["success"] is True
    assert res["total"] >= 1
    found_ids = [c["id"] for c in res["customers"]]
    assert sample_customer in found_ids


def test_admin_customers_get_details(db_session, sample_customer):
    res = get_customer(customer_id=sample_customer, db=db_session)
    assert res["success"] is True
    assert res["customer"]["id"] == sample_customer
    assert "subscription" in res
    assert "peers" in res


def test_admin_customers_get_nonexistent_returns_404(db_session):
    fake_id = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(HTTPException) as exc_info:
        get_customer(customer_id=fake_id, db=db_session)
    assert exc_info.value.status_code == 404
    assert "Customer not found" in exc_info.value.detail


def test_admin_customers_update_status(db_session, sample_customer):
    client = db_session.query(Client).filter_by(user_id=sample_customer).first()
    orig_status = client.subscription_status or "active"

    try:
        # Transition to grace_period
        payload = CustomerStatusUpdateSchema(status="grace_period")
        res = update_status(customer_id=sample_customer, payload=payload, db=db_session)
        assert res["success"] is True
        assert res["message"] == "Status updated"

        db_session.refresh(client)
        assert client.subscription_status == "grace_period"

    finally:
        # Restore original status
        restore_payload = CustomerStatusUpdateSchema(status=orig_status)
        update_status(customer_id=sample_customer, payload=restore_payload, db=db_session)


def test_admin_customers_update_plan(db_session, sample_customer):
    plans = db_session.query(SubscriptionPlan).all()
    assert len(plans) >= 1
    target_plan = plans[0]

    client = db_session.query(Client).filter_by(user_id=sample_customer).first()
    orig_plan_id = client.plan_id
    orig_allowed_peers = client.allowed_peers_count

    orig_status = client.subscription_status or "active"

    try:
        payload = CustomerPlanUpdateSchema(
            plan_id=target_plan.id,
            billing_cycle="yearly",
            allowed_peers_count=15,
            is_trial=False,
            status="grace_period"
        )
        res = update_plan(customer_id=sample_customer, payload=payload, db=db_session)
        assert res["success"] is True
        assert res["message"] == "Plan updated"

        db_session.refresh(client)
        assert client.plan_id == target_plan.id
        assert client.billing_cycle == "yearly"
        assert client.allowed_peers_count == 15
        assert client.subscription_status == "grace_period"

    finally:
        # Restore if needed
        if orig_plan_id:
            db_session.query(Client).filter_by(user_id=sample_customer).update({
                "plan_id": orig_plan_id,
                "allowed_peers_count": orig_allowed_peers
            })
            db_session.commit()


def test_admin_customers_reset_password(db_session, sample_customer):
    # 1. Short password rejection
    with pytest.raises(Exception):
        CustomerResetPasswordSchema(password="123")

    # 2. Valid password reset
    payload = CustomerResetPasswordSchema(password="SecureNewPassword123!")
    res = reset_password(customer_id=sample_customer, payload=payload, db=db_session)
    assert res["success"] is True
    assert res["message"] == "Password reset successfully"

    # Verify password hash updated
    client = db_session.query(Client).filter_by(user_id=sample_customer).first()
    from werkzeug.security import check_password_hash
    assert check_password_hash(client.password_hashed, "SecureNewPassword123!")
