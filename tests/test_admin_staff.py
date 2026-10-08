# /opt/networkat_sdwan/core/web_app/tests/test_admin_staff.py
"""
Unit and integration tests for Phase 5: Staff & Role-Based Access Control (RBAC) in FastAPI.
Covers:
- Listing staff members (list_staff)
- Profile retrieval (get_staff)
- Staff creation with validation and encryption (create_staff)
- Staff profile and role update (update_staff)
- Staff password reset (reset_password)
- Account status toggling and self-deactivation protection (toggle_status)
- Account deletion and self-deletion protection (delete_staff)
- 2FA setup, TOTP verification, and 2FA disabling (setup_2fa, confirm_2fa, disable_2fa)
- Role and schema validation tests
"""
import pytest
from fastapi import HTTPException
from fastapi_app.database import SessionLocal
from fastapi_app.dependencies import AdminAuthContext
from models.system_user import SystemUser
from fastapi_app.schemas.admin.staff import (
    StaffCreateSchema,
    StaffUpdateSchema,
    StaffPasswordResetSchema,
    Staff2FAConfirmSchema,
    Staff2FADisableSchema,
)
from fastapi_app.routes.admin.staff import (
    list_staff,
    get_staff,
    create_staff,
    update_staff,
    reset_password,
    toggle_status,
    delete_staff,
    setup_2fa,
    confirm_2fa,
    disable_2fa,
)
import pyotp


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def admin_auth():
    return AdminAuthContext(
        user_id="1",
        username="admin",
        role="admin",
        is_bearer=True,
        fullname="Administrator"
    )


def test_admin_staff_list(db_session, admin_auth):
    res = list_staff(db=db_session, auth=admin_auth)
    assert res["success"] is True
    assert "total" in res
    assert "staff" in res
    assert isinstance(res["staff"], list)
    assert res["total"] >= 1

    first = res["staff"][0]
    assert "id" in first
    assert "username" in first
    assert "email" in first
    assert "role" in first
    assert "is_active" in first
    assert "is_2fa_enabled" in first


def test_admin_staff_crud_lifecycle(db_session, admin_auth):
    test_username = "phase5_test_user"
    test_email = "phase5_test@networkat.local"

    # Cleanup if leftovers exist
    leftover = db_session.query(SystemUser).filter(
        (SystemUser.username == test_username) | (SystemUser.email == test_email)
    ).first()
    if leftover:
        db_session.delete(leftover)
        db_session.commit()

    # 1. Create staff member
    create_payload = StaffCreateSchema(
        username=test_username,
        email=test_email,
        full_name="Phase5 Test Agent",
        password="TemporaryPassword123!",
        role="support"
    )
    res_create = create_staff(payload=create_payload, db=db_session, auth=admin_auth)
    assert res_create["success"] is True
    assert res_create["message"] == "Staff member created successfully"
    created_id = res_create["staff"]["id"]
    assert res_create["staff"]["username"] == test_username
    assert res_create["staff"]["role"] == "support"
    assert res_create["staff"]["is_active"] is True

    try:
        # 2. Duplicate username rejection
        with pytest.raises(HTTPException) as exc_dup_u:
            create_staff(payload=create_payload, db=db_session, auth=admin_auth)
        assert exc_dup_u.value.status_code == 400
        assert "already taken" in exc_dup_u.value.detail

        # 3. Duplicate email rejection
        dup_email_payload = StaffCreateSchema(
            username="other_username_phase5",
            email=test_email,
            full_name="Another Agent",
            password="TemporaryPassword123!",
            role="sales"
        )
        with pytest.raises(HTTPException) as exc_dup_e:
            create_staff(payload=dup_email_payload, db=db_session, auth=admin_auth)
        assert exc_dup_e.value.status_code == 400
        assert "already registered" in exc_dup_e.value.detail

        # 4. Get staff detail
        res_get = get_staff(user_id=created_id, db=db_session, auth=admin_auth)
        assert res_get["success"] is True
        assert res_get["staff"]["id"] == created_id
        assert res_get["staff"]["username"] == test_username
        assert res_get["staff"]["role"] == "support"

        # 5. Update staff info & role
        update_payload = StaffUpdateSchema(
            full_name="Phase5 Agent Renamed",
            email=test_email,
            role="sales"
        )
        res_update = update_staff(user_id=created_id, payload=update_payload, db=db_session, auth=admin_auth)
        assert res_update["success"] is True
        assert res_update["staff"]["full_name"] == "Phase5 Agent Renamed"
        assert res_update["staff"]["role"] == "sales"

        # 6. Reset password
        pwd_payload = StaffPasswordResetSchema(password="NewSecurePass456!")
        res_pwd = reset_password(user_id=created_id, payload=pwd_payload, db=db_session, auth=admin_auth)
        assert res_pwd["success"] is True
        assert res_pwd["message"] == "Password reset successfully"

        # 7. Toggle status
        res_toggle = toggle_status(user_id=created_id, db=db_session, auth=admin_auth)
        assert res_toggle["success"] is True
        assert res_toggle["is_active"] is False

        res_toggle_back = toggle_status(user_id=created_id, db=db_session, auth=admin_auth)
        assert res_toggle_back["success"] is True
        assert res_toggle_back["is_active"] is True

    finally:
        # 8. Delete staff member
        res_del = delete_staff(user_id=created_id, db=db_session, auth=admin_auth)
        assert res_del["success"] is True
        assert res_del["message"] == "Staff member deleted successfully"

    # 9. Verify 404 after deletion
    with pytest.raises(HTTPException) as exc_404:
        get_staff(user_id=created_id, db=db_session, auth=admin_auth)
    assert exc_404.value.status_code == 404


def test_admin_staff_self_protection(db_session):
    admin_user = db_session.query(SystemUser).first()
    assert admin_user is not None, "At least one system user must exist"

    self_auth = AdminAuthContext(
        user_id=str(admin_user.id),
        username=admin_user.username,
        role=admin_user.role or "admin",
        is_bearer=False,
    )

    # 1. Self deactivation must fail with 400
    with pytest.raises(HTTPException) as exc_toggle:
        toggle_status(user_id=admin_user.id, db=db_session, auth=self_auth)
    assert exc_toggle.value.status_code == 400
    assert "cannot deactivate your own account" in exc_toggle.value.detail

    # 2. Self deletion must fail with 400
    with pytest.raises(HTTPException) as exc_del:
        delete_staff(user_id=admin_user.id, db=db_session, auth=self_auth)
    assert exc_del.value.status_code == 400
    assert "cannot delete your own account" in exc_del.value.detail


def test_admin_staff_schema_validation():
    # Invalid characters in username
    with pytest.raises(Exception):
        StaffCreateSchema(
            username="invalid user spaces!",
            email="valid@networkat.local",
            full_name="Valid Name",
            password="password123",
            role="support"
        )

    # Invalid email
    with pytest.raises(Exception):
        StaffCreateSchema(
            username="validusername",
            email="notanemail",
            full_name="Valid Name",
            password="password123",
            role="support"
        )

    # Invalid role
    with pytest.raises(Exception):
        StaffCreateSchema(
            username="validusername",
            email="valid@networkat.local",
            full_name="Valid Name",
            password="password123",
            role="superman"
        )

    # Short password
    with pytest.raises(Exception):
        StaffCreateSchema(
            username="validusername",
            email="valid@networkat.local",
            full_name="Valid Name",
            password="123",
            role="sales"
        )


def test_admin_staff_2fa_flow(db_session, admin_auth):
    test_username = "phase5_2fa_user"
    test_email = "phase5_2fa@networkat.local"

    # Cleanup
    leftover = db_session.query(SystemUser).filter_by(username=test_username).first()
    if leftover:
        db_session.delete(leftover)
        db_session.commit()

    # Create temporary staff user
    create_payload = StaffCreateSchema(
        username=test_username,
        email=test_email,
        full_name="Phase5 2FA Agent",
        password="TemporaryPassword123!",
        role="support"
    )
    res_create = create_staff(payload=create_payload, db=db_session, auth=admin_auth)
    created_id = res_create["staff"]["id"]

    try:
        # 1. Setup 2FA
        res_setup = setup_2fa(user_id=created_id, db=db_session, auth=admin_auth)
        assert res_setup["success"] is True
        assert "secret" in res_setup
        assert "qr_code" in res_setup
        secret = res_setup["secret"]

        # 2. Confirm 2FA with bad code
        with pytest.raises(HTTPException) as exc_bad_code:
            confirm_2fa(
                user_id=created_id,
                payload=Staff2FAConfirmSchema(secret=secret, code="000000"),
                db=db_session,
                auth=admin_auth
            )
        assert exc_bad_code.value.status_code == 400
        assert "Invalid verification code" in exc_bad_code.value.detail

        # 3. Confirm 2FA with valid code
        valid_code = pyotp.TOTP(secret).now()
        res_confirm = confirm_2fa(
            user_id=created_id,
            payload=Staff2FAConfirmSchema(secret=secret, code=valid_code),
            db=db_session,
            auth=admin_auth
        )
        assert res_confirm["success"] is True
        assert "recovery_codes" in res_confirm
        assert len(res_confirm["recovery_codes"]) == 8

        # Verify DB state
        user = db_session.query(SystemUser).filter_by(id=created_id).first()
        assert user.is_2fa_enabled is True

        # 4. Disable 2FA
        res_disable = disable_2fa(
            user_id=created_id,
            payload=Staff2FADisableSchema(),
            db=db_session,
            auth=admin_auth
        )
        assert res_disable["success"] is True

        db_session.refresh(user)
        assert user.is_2fa_enabled is False

    finally:
        delete_staff(user_id=created_id, db=db_session, auth=admin_auth)
