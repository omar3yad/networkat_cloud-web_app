# /opt/networkat_sdwan/core/web_app/fastapi_app/routes/admin/staff.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from fastapi_app.dependencies import get_db, get_admin_auth, require_admin_role, AdminAuthContext
from fastapi_app.schemas.admin.staff import (
    StaffListResponse,
    StaffCreateSchema,
    StaffUpdateSchema,
    StaffPasswordResetSchema,
    StaffToggleStatusResponse,
    StaffActionResponse,
    Staff2FASetupResponse,
    Staff2FAConfirmSchema,
    Staff2FAConfirmResponse,
    Staff2FADisableSchema,
)
from fastapi_app.services.admin.staff_service import AdminStaffService

router = APIRouter(
    prefix="/api/v2/admin/staff",
    tags=["Admin - Staff & RBAC Management"]
)


@router.get("", response_model=StaffListResponse, summary="List all staff members")
def list_staff(
    db: Session = Depends(get_db),
    auth: AdminAuthContext = Depends(get_admin_auth)
):
    """
    Retrieves all staff members with their current roles and security status.
    """
    return AdminStaffService.list_staff(db=db)


@router.post("", response_model=StaffActionResponse, status_code=status.HTTP_201_CREATED, summary="Create a new staff member")
def create_staff(
    payload: StaffCreateSchema,
    db: Session = Depends(get_db),
    auth: AdminAuthContext = Depends(require_admin_role)
):
    """
    Creates a new staff member with assigned role (admin, support, sales).
    Requires administrator role.
    """
    return AdminStaffService.create_staff(
        db=db,
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
        role=payload.role
    )


@router.get("/{user_id}", response_model=StaffActionResponse, summary="Get staff member details")
def get_staff(
    user_id: int,
    db: Session = Depends(get_db),
    auth: AdminAuthContext = Depends(get_admin_auth)
):
    """
    Retrieves profile details of a single staff member.
    """
    return AdminStaffService.get_staff_detail(db=db, user_id=user_id)


@router.put("/{user_id}", response_model=StaffActionResponse, summary="Update staff member info and role")
def update_staff(
    user_id: int,
    payload: StaffUpdateSchema,
    db: Session = Depends(get_db),
    auth: AdminAuthContext = Depends(require_admin_role)
):
    """
    Updates staff member details, email, and role.
    Requires administrator role.
    """
    return AdminStaffService.update_staff(
        db=db,
        user_id=user_id,
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role
    )


@router.post("/{user_id}/password", response_model=StaffActionResponse, summary="Reset staff member password")
def reset_password(
    user_id: int,
    payload: StaffPasswordResetSchema,
    db: Session = Depends(get_db),
    auth: AdminAuthContext = Depends(require_admin_role)
):
    """
    Securely resets password for an existing staff member.
    Requires administrator role.
    """
    return AdminStaffService.reset_password(
        db=db,
        user_id=user_id,
        password=payload.password
    )


@router.post("/{user_id}/toggle", response_model=StaffToggleStatusResponse, summary="Toggle staff account status")
def toggle_status(
    user_id: int,
    db: Session = Depends(get_db),
    auth: AdminAuthContext = Depends(require_admin_role)
):
    """
    Activates or deactivates a staff member account. Self-deactivation is prohibited.
    Requires administrator role.
    """
    return AdminStaffService.toggle_status(
        db=db,
        user_id=user_id,
        current_admin_id=auth.user_id
    )


@router.delete("/{user_id}", response_model=StaffActionResponse, summary="Delete a staff member")
def delete_staff(
    user_id: int,
    db: Session = Depends(get_db),
    auth: AdminAuthContext = Depends(require_admin_role)
):
    """
    Permanently deletes a staff member. Self-deletion is prohibited.
    Requires administrator role.
    """
    return AdminStaffService.delete_staff(
        db=db,
        user_id=user_id,
        current_admin_id=auth.user_id
    )


@router.post("/{user_id}/2fa/setup", response_model=Staff2FASetupResponse, summary="Initiate 2FA enrollment")
def setup_2fa(
    user_id: int,
    db: Session = Depends(get_db),
    auth: AdminAuthContext = Depends(get_admin_auth)
):
    """
    Generates TOTP secret and QR code for two-factor authentication.
    """
    return AdminStaffService.setup_2fa(
        db=db,
        user_id=user_id,
        current_user_id=auth.user_id,
        current_role=auth.role
    )


@router.post("/{user_id}/2fa/confirm", response_model=Staff2FAConfirmResponse, summary="Confirm and enable 2FA")
def confirm_2fa(
    user_id: int,
    payload: Staff2FAConfirmSchema,
    db: Session = Depends(get_db),
    auth: AdminAuthContext = Depends(get_admin_auth)
):
    """
    Confirms TOTP setup using code verification and returns recovery codes.
    """
    secret = payload.secret
    if not secret:
        # Fallback to existing user secret if already generating
        user_detail = AdminStaffService.get_staff_detail(db=db, user_id=user_id)
        from models.system_user import SystemUser
        user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
        secret = user.totp_secret if user else ""

    return AdminStaffService.confirm_2fa(
        db=db,
        user_id=user_id,
        secret=secret,
        code=payload.code,
        current_user_id=auth.user_id,
        current_role=auth.role
    )


@router.post("/{user_id}/2fa/disable", response_model=StaffActionResponse, summary="Disable 2FA for staff member")
def disable_2fa(
    user_id: int,
    payload: Staff2FADisableSchema,
    db: Session = Depends(get_db),
    auth: AdminAuthContext = Depends(get_admin_auth)
):
    """
    Disables two-factor authentication. Requires password verification if done by the user themselves.
    """
    return AdminStaffService.disable_2fa(
        db=db,
        user_id=user_id,
        password=payload.password,
        current_user_id=auth.user_id,
        current_role=auth.role
    )
