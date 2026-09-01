from fastapi import APIRouter, HTTPException, status, Query
from typing import List, Optional
from fastapi_app.schemas.netbird.users import (
    NetBirdUserResponse, NetBirdUserCreate, NetBirdUserUpdate, ChangePasswordRequest,
    InviteResponse, InviteCreateRequest, InviteRegenerateRequest, InviteRegenerateResponse,
    InviteInfoResponse, AcceptInviteRequest
)
from fastapi_app.services.netbird.users import NetBirdUserService

router = APIRouter(prefix="/api/v2/netbird", tags=["NetBird Users"])

def handle_result(result):
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=result["status_code"], detail=f"NetBird Error: {result['detail']}")
    return result

# ==========================================
# 1. CURRENT USER & BASE USERS
# ==========================================
@router.get("/users/current", response_model=NetBirdUserResponse)
def get_current_user():
    return handle_result(NetBirdUserService.get_current_user())

@router.get("/users", response_model=List[NetBirdUserResponse])
def list_all_users(service_user: Optional[bool] = Query(None, description="Filter by service_user")):
    return handle_result(NetBirdUserService.list_users(service_user))

@router.post("/users", response_model=NetBirdUserResponse)
def create_new_user(payload: NetBirdUserCreate):
    return handle_result(NetBirdUserService.create_user(payload))

# ==========================================
# 2. INVITES OPERATIONS (MUST BE BEFORE /{userId})
# ==========================================
@router.get("/users/invites", response_model=List[InviteResponse])
def list_user_invites():
    return handle_result(NetBirdUserService.list_invites())

@router.post("/users/invites", response_model=InviteResponse)
def create_user_invite(payload: InviteCreateRequest):
    return handle_result(NetBirdUserService.create_invite(payload))

@router.delete("/users/invites/{invite_id}")
def delete_user_invite(invite_id: str):
    return handle_result(NetBirdUserService.delete_invite(invite_id))

@router.post("/users/invites/{invite_id}/regenerate", response_model=InviteRegenerateResponse)
def regenerate_user_invite(invite_id: str, payload: InviteRegenerateRequest):
    return handle_result(NetBirdUserService.regenerate_invite(invite_id, payload))

@router.get("/users/invites/info/{token}", response_model=InviteInfoResponse)
def get_invite_info(token: str):
    return handle_result(NetBirdUserService.get_invite_info(token))

@router.post("/users/invites/info/{token}/accept")
def accept_invite(token: str, payload: AcceptInviteRequest):
    return handle_result(NetBirdUserService.accept_invite(token, payload))

# ==========================================
# 3. SPECIFIC USER OPERATIONS (/{userId})
# ==========================================
@router.put("/users/{user_id}", response_model=NetBirdUserResponse)
def update_user(user_id: str, payload: NetBirdUserUpdate):
    return handle_result(NetBirdUserService.update_user(user_id, payload))

@router.delete("/users/{user_id}")
def delete_user(user_id: str):
    return handle_result(NetBirdUserService.delete_user(user_id))

@router.post("/users/{user_id}/invite")
def resend_user_invitation(user_id: str):
    return handle_result(NetBirdUserService.resend_invite(user_id))

@router.post("/users/{user_id}/approve", response_model=NetBirdUserResponse)
def approve_user(user_id: str):
    return handle_result(NetBirdUserService.approve_user(user_id))

@router.delete("/users/{user_id}/reject")
def reject_user(user_id: str):
    return handle_result(NetBirdUserService.reject_user(user_id))

@router.put("/users/{user_id}/password")
def change_user_password(user_id: str, payload: ChangePasswordRequest):
    return handle_result(NetBirdUserService.change_password(user_id, payload))