from fastapi import APIRouter, HTTPException, status
from typing import List
from fastapi_app.schemas.netbird.policies import NetBirdPolicyResponse, NetBirdPolicyCreateUpdate
from fastapi_app.services.netbird.policies import NetBirdPolicyService

router = APIRouter(prefix="/api/v2/netbird/policies", tags=["NetBird Policies"])

def handle_result(result):
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=result["status_code"], detail=f"NetBird Error: {result['detail']}")
    return result

@router.get("", response_model=List[NetBirdPolicyResponse])
def list_policies():
    return handle_result(NetBirdPolicyService.list_policies())

@router.post("", response_model=NetBirdPolicyResponse, status_code=status.HTTP_201_CREATED)
def create_policy(payload: NetBirdPolicyCreateUpdate):
    return handle_result(NetBirdPolicyService.create_policy(payload))

@router.get("/{policy_id}", response_model=NetBirdPolicyResponse)
def retrieve_policy(policy_id: str):
    return handle_result(NetBirdPolicyService.get_policy(policy_id))

@router.put("/{policy_id}", response_model=NetBirdPolicyResponse)
def update_policy(policy_id: str, payload: NetBirdPolicyCreateUpdate):
    return handle_result(NetBirdPolicyService.update_policy(policy_id, payload))

@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy(policy_id: str):
    result = NetBirdPolicyService.delete_policy(policy_id)
    handle_result(result)
    return