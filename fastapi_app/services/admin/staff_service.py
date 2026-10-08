# /opt/networkat_sdwan/core/web_app/fastapi_app/services/admin/staff_service.py
import logging
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from models.system_user import SystemUser
from utils.password import hash_password, verify_password
from utils.two_factor import (
    generate_totp_secret,
    get_totp_uri,
    generate_qr_base64,
    verify_totp_code,
    generate_recovery_codes,
    hash_recovery_codes,
)

logger = logging.getLogger(__name__)


class AdminStaffService:
    """Service layer for Admin Staff & Role-Based Access Control."""

    @classmethod
    def list_staff(cls, db: Session) -> Dict[str, Any]:
        """
        Retrieves all staff members ordered by creation date descending.
        """
        users = db.query(SystemUser).order_by(SystemUser.created_at.desc()).all()
        staff_list = []
        for u in users:
            staff_list.append({
                "id": u.id,
                "username": u.username,
                "full_name": u.full_name,
                "email": u.email,
                "role": u.role or "sales",
                "is_active": bool(u.is_active),
                "is_2fa_enabled": bool(u.is_2fa_enabled),
                "last_login": u.last_login.strftime("%Y-%m-%d %H:%M:%S") if u.last_login else None,
                "created_at": u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else None,
            })
        return {
            "success": True,
            "total": len(staff_list),
            "staff": staff_list,
        }

    @classmethod
    def get_staff_detail(cls, db: Session, user_id: int) -> Dict[str, Any]:
        """
        Retrieves profile of a specific staff member.
        """
        user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")

        return {
            "success": True,
            "message": "Staff member retrieved",
            "staff": {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "email": user.email,
                "role": user.role or "sales",
                "is_active": bool(user.is_active),
                "is_2fa_enabled": bool(user.is_2fa_enabled),
                "last_login": user.last_login.strftime("%Y-%m-%d %H:%M:%S") if user.last_login else None,
                "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S") if user.created_at else None,
            }
        }

    @classmethod
    def create_staff(
        cls,
        db: Session,
        username: str,
        email: str,
        full_name: str,
        password: str,
        role: str = "sales",
    ) -> Dict[str, Any]:
        """
        Creates a new staff member with encrypted password and validated role.
        """
        if db.query(SystemUser).filter(SystemUser.username == username).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'Username "{username}" is already taken',
            )

        if db.query(SystemUser).filter(SystemUser.email == email).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'Email "{email}" is already registered',
            )

        hashed = hash_password(password)
        user = SystemUser(
            username=username,
            email=email,
            full_name=full_name,
            password_hash=hashed,
            role=role,
            is_active=True,
        )
        try:
            db.add(user)
            db.commit()
            db.refresh(user)
        except Exception as e:
            db.rollback()
            logger.error("Failed to create staff member: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create staff member",
            )

        return {
            "success": True,
            "message": "Staff member created successfully",
            "staff": {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active,
                "is_2fa_enabled": False,
                "last_login": None,
                "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S") if user.created_at else None,
            }
        }

    @classmethod
    def update_staff(
        cls,
        db: Session,
        user_id: int,
        email: str,
        full_name: str,
        role: str,
    ) -> Dict[str, Any]:
        """
        Updates profile info and assigned role for an existing staff member.
        """
        user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")

        existing_email = db.query(SystemUser).filter(SystemUser.email == email).first()
        if existing_email and existing_email.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'Email "{email}" is already in use by another user',
            )

        user.email = email
        user.full_name = full_name
        user.role = role

        try:
            db.commit()
            db.refresh(user)
        except Exception as e:
            db.rollback()
            logger.error("Failed to update staff member: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update staff member",
            )

        return {
            "success": True,
            "message": "Staff info updated successfully",
            "staff": {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active,
                "is_2fa_enabled": bool(user.is_2fa_enabled),
                "last_login": user.last_login.strftime("%Y-%m-%d %H:%M:%S") if user.last_login else None,
                "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S") if user.created_at else None,
            }
        }

    @classmethod
    def reset_password(cls, db: Session, user_id: int, password: str) -> Dict[str, Any]:
        """
        Resets password for an existing staff member.
        """
        user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")

        user.password_hash = hash_password(password)
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("Failed to reset staff password: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to reset password",
            )

        return {
            "success": True,
            "message": "Password reset successfully",
        }

    @classmethod
    def toggle_status(
        cls,
        db: Session,
        user_id: int,
        current_admin_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Toggles active status of staff member, preventing self-deactivation.
        """
        user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")

        if current_admin_id and str(user.id) == str(current_admin_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot deactivate your own account",
            )

        user.is_active = not user.is_active
        try:
            db.commit()
            db.refresh(user)
        except Exception as e:
            db.rollback()
            logger.error("Failed to toggle staff status: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update staff status",
            )

        return {
            "success": True,
            "is_active": user.is_active,
            "message": "Status updated",
        }

    @classmethod
    def delete_staff(
        cls,
        db: Session,
        user_id: int,
        current_admin_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Deletes a staff member, preventing self-deletion.
        """
        user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")

        if current_admin_id and str(user.id) == str(current_admin_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot delete your own account",
            )

        try:
            db.delete(user)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("Failed to delete staff member: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete staff member",
            )

        return {
            "success": True,
            "message": "Staff member deleted successfully",
        }

    @classmethod
    def setup_2fa(
        cls,
        db: Session,
        user_id: int,
        current_user_id: Optional[str] = None,
        current_role: str = "admin",
    ) -> Dict[str, Any]:
        """
        Generates TOTP secret and QR code for 2FA enrollment.
        """
        is_self = current_user_id and str(user_id) == str(current_user_id)
        if not (is_self or current_role == "admin"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

        user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        secret = generate_totp_secret()
        uri = get_totp_uri(secret, user.username, issuer="Networkat Management")
        qr_b64 = generate_qr_base64(uri)

        return {
            "success": True,
            "secret": secret,
            "qr_code": qr_b64,
        }

    @classmethod
    def confirm_2fa(
        cls,
        db: Session,
        user_id: int,
        secret: str,
        code: str,
        current_user_id: Optional[str] = None,
        current_role: str = "admin",
    ) -> Dict[str, Any]:
        """
        Confirms TOTP enrollment with code verification and stores recovery codes.
        """
        is_self = current_user_id and str(user_id) == str(current_user_id)
        if not (is_self or current_role == "admin"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

        user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if not verify_totp_code(secret, code):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code")

        recovery_codes = generate_recovery_codes(8)
        hashed_codes = hash_recovery_codes(recovery_codes)

        user.totp_secret = secret
        user.is_2fa_enabled = True
        user.recovery_codes = hashed_codes
        user.two_fa_method = "totp"

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("Failed to enable 2FA for staff: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to enable two-factor authentication",
            )

        return {
            "success": True,
            "recovery_codes": recovery_codes,
            "message": "Two-factor authentication enabled successfully",
        }

    @classmethod
    def disable_2fa(
        cls,
        db: Session,
        user_id: int,
        password: Optional[str] = None,
        current_user_id: Optional[str] = None,
        current_role: str = "admin",
    ) -> Dict[str, Any]:
        """
        Disables 2FA for a staff member.
        """
        is_self = current_user_id and str(user_id) == str(current_user_id)
        is_admin = current_role == "admin"

        if not (is_self or is_admin):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

        user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if is_self and not is_admin:
            if not password or not verify_password(password, user.password_hash):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid password confirmation")

        user.is_2fa_enabled = False
        user.totp_secret = None
        user.recovery_codes = None

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("Failed to disable 2FA: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to disable two-factor authentication",
            )

        return {
            "success": True,
            "message": "Two-factor authentication disabled",
        }
