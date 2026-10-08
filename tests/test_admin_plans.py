# /opt/networkat_sdwan/core/web_app/tests/test_admin_plans.py
"""
Unit and integration tests for Phase 1: Subscription Plans Management in FastAPI.
Direct function call tests for routes and services without httpx dependency.
Tests:
- Schema validation (PlanCreate, PlanUpdate, TrialDurationUpdate)
- Routes and Service execution (list_plans, get_plan, create_plan, update_plan, toggle_plan, delete_plan)
- Data integrity, rollback on error, unique constraint enforcement
- Trial duration get & update
"""
import pytest
from fastapi import HTTPException
from fastapi_app.database import SessionLocal
from fastapi_app.schemas.admin.plans import (
    PlanCreate,
    PlanUpdate,
    TrialDurationUpdate,
)
from fastapi_app.routes.admin.plans import (
    list_plans,
    get_plan,
    create_plan,
    update_plan,
    toggle_plan,
    delete_plan,
    get_trial_duration,
    set_trial_duration,
)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_plans_list(db_session):
    result = list_plans(db=db_session)
    assert result["success"] is True
    assert isinstance(result["plans"], list)
    assert len(result["plans"]) >= 3
    plan_names = [p["name"] for p in result["plans"]]
    assert "starter" in plan_names
    assert "pro" in plan_names
    assert "enterprise" in plan_names


def test_plans_crud_lifecycle(db_session):
    test_slug = "phase1_test_unit"
    # Clean up if leftover
    from models.subscription_plan import SubscriptionPlan
    existing = db_session.query(SubscriptionPlan).filter_by(name=test_slug).first()
    if existing:
        db_session.delete(existing)
        db_session.commit()

    # 1. Create
    payload = PlanCreate(
        name=test_slug,
        display_name="Phase 1 Unit Plan",
        allowed_peers_count=12,
        billing_cycle="monthly,yearly",
        price_monthly=25.0,
        price_annual=250.0,
        is_active=True,
    )
    created = create_plan(payload=payload, db=db_session)
    assert created["success"] is True
    plan = created["plan"]
    plan_id = plan["id"]
    assert plan["name"] == test_slug
    assert plan["display_name"] == "Phase 1 Unit Plan"
    assert plan["allowed_peers_count"] == 12
    assert plan["price_monthly"] == 25.0
    assert plan["price_annual"] == 250.0
    assert plan["is_active"] is True

    try:
        # 2. Duplicate rejection
        with pytest.raises(HTTPException) as exc_dup:
            create_plan(payload=payload, db=db_session)
        assert exc_dup.value.status_code == 400
        assert "already exists" in exc_dup.value.detail

        # 3. Get plan by ID
        fetched = get_plan(plan_id=plan_id, db=db_session)
        assert fetched["success"] is True
        assert fetched["plan"]["id"] == plan_id
        assert fetched["plan"]["name"] == test_slug

        # 4. Update plan
        upd_payload = PlanUpdate(
            display_name="Phase 1 Unit Plan Updated",
            allowed_peers_count=15,
            price_monthly=30.0,
        )
        updated = update_plan(plan_id=plan_id, payload=upd_payload, db=db_session)
        assert updated["success"] is True
        assert updated["plan"]["display_name"] == "Phase 1 Unit Plan Updated"
        assert updated["plan"]["allowed_peers_count"] == 15
        assert updated["plan"]["price_monthly"] == 30.0

        # 5. Toggle active status
        toggled = toggle_plan(plan_id=plan_id, db=db_session)
        assert toggled["success"] is True
        assert toggled["is_active"] is False

        toggled_back = toggle_plan(plan_id=plan_id, db=db_session)
        assert toggled_back["success"] is True
        assert toggled_back["is_active"] is True

    finally:
        # 6. Delete plan
        deleted = delete_plan(plan_id=plan_id, db=db_session)
        assert deleted["success"] is True
        assert deleted["message"] == "Plan deleted"

    # 7. Verify 404 after delete
    with pytest.raises(HTTPException) as exc_404:
        get_plan(plan_id=plan_id, db=db_session)
    assert exc_404.value.status_code == 404


def test_delete_protected_when_clients_assigned(db_session):
    # 'starter' plan has clients assigned or is a primary plan
    from models.subscription_plan import SubscriptionPlan
    starter = db_session.query(SubscriptionPlan).filter_by(name="starter").first()
    assert starter is not None

    with pytest.raises(HTTPException) as exc_info:
        delete_plan(plan_id=starter.id, db=db_session)

    assert exc_info.value.status_code == 400
    assert "Cannot delete" in exc_info.value.detail


def test_trial_duration_get_and_set(db_session):
    orig = get_trial_duration(db=db_session)
    assert orig["success"] is True
    orig_days = orig["trial_days"]
    assert isinstance(orig_days, int)

    try:
        # Update
        updated = set_trial_duration(
            payload=TrialDurationUpdate(trial_days=14),
            db=db_session
        )
        assert updated["success"] is True
        assert updated["trial_days"] == 14

        # Read back
        verify = get_trial_duration(db=db_session)
        assert verify["trial_days"] == 14

    finally:
        # Restore
        set_trial_duration(
            payload=TrialDurationUpdate(trial_days=orig_days),
            db=db_session
        )
