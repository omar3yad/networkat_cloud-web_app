# fastapi_app/routes/netbird/groups.py
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status
from fastapi_app.schemas.netbird.groups import NetBirdGroupCreate, NetBirdGroupResponse
from fastapi_app.services.netbird.groups import NetBirdService

router = APIRouter(prefix="/api/v2/netbird", tags=["NetBird Groups"])

@router.post("/groups", status_code=status.HTTP_201_CREATED)
def create_netbird_group(payload: NetBirdGroupCreate):
    result = NetBirdService.create_group(payload)
    # إذا كان هناك خطأ في الاتصال بسيرفر NetBird
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(
            status_code=result["status_code"],
            detail=f"NetBird Error: {result['detail']}"
        )
    return result

@router.get("/groups", response_model=List[NetBirdGroupResponse], status_code=status.HTTP_200_OK)
def list_netbird_groups(name: Optional[str] = None):
    result = NetBirdService.get_groups(name)
    
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(
            status_code=result["status_code"],
            detail=f"NetBird Error: {result['detail']}"
        )
        
    return result

# 3. جلب بيانات مجموعة محددة (Retrieve)
@router.get("/groups/{group_id}", response_model=NetBirdGroupResponse, status_code=status.HTTP_200_OK)
def get_netbird_group(group_id: str):
    result = NetBirdService.get_group_by_id(group_id)
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=result["status_code"], detail=f"NetBird Error: {result['detail']}")
    return result

# 4. تحديث مجموعة (Update)
@router.put("/groups/{group_id}", response_model=NetBirdGroupResponse, status_code=status.HTTP_200_OK)
def update_netbird_group(group_id: str, payload: NetBirdGroupCreate):
    result = NetBirdService.update_group(group_id, payload)
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=result["status_code"], detail=f"NetBird Error: {result['detail']}")
    return result

# 5. حذف مجموعة (Delete)
@router.delete("/groups/{group_id}", status_code=status.HTTP_200_OK)
def delete_netbird_group(group_id: str):
    result = NetBirdService.delete_group(group_id)
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=result["status_code"], detail=f"NetBird Error: {result['detail']}")
    return {"message": "Group deleted successfully"}