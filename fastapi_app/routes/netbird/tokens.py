from fastapi import APIRouter, HTTPException, status
from typing import List
from fastapi_app.schemas.netbird.tokens import NetBirdTokenCreate, NetBirdTokenResponse, NetBirdTokenCreateResponse
from fastapi_app.services.netbird.tokens import NetBirdTokenService

router = APIRouter(prefix="/api/v2/netbird/users", tags=["NetBird Tokens"])

# 1. جلب كل التوكنز لمستخدم معين (List)
@router.get("/{user_id}/tokens", response_model=List[NetBirdTokenResponse], status_code=status.HTTP_200_OK)
def list_user_tokens(user_id: str):
    result = NetBirdTokenService.list_tokens(user_id)
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=result["status_code"], detail=f"NetBird Error: {result['detail']}")
    return result

# 2. إنشاء توكن جديد لمستخدم (Create)
@router.post("/{user_id}/tokens", response_model=NetBirdTokenCreateResponse, status_code=status.HTTP_200_OK)
def create_user_token(user_id: str, payload: NetBirdTokenCreate):
    result = NetBirdTokenService.create_token(user_id, payload)
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=result["status_code"], detail=f"NetBird Error: {result['detail']}")
    return result

# 3. جلب بيانات توكن محدد (Retrieve)
@router.get("/{user_id}/tokens/{token_id}", response_model=NetBirdTokenResponse, status_code=status.HTTP_200_OK)
def get_user_token(user_id: str, token_id: str):
    result = NetBirdTokenService.get_token(user_id, token_id)
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=result["status_code"], detail=f"NetBird Error: {result['detail']}")
    return result

# 4. حذف توكن (Delete)
@router.delete("/{user_id}/tokens/{token_id}", status_code=status.HTTP_200_OK)
def delete_user_token(user_id: str, token_id: str):
    result = NetBirdTokenService.delete_token(user_id, token_id)
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=result["status_code"], detail=f"NetBird Error: {result['detail']}")
    return {"message": "Token deleted successfully"}