from fastapi import APIRouter, HTTPException, status
from typing import List
from fastapi_app.schemas.netbird.setup_keys import (
    NetBirdSetupKeyResponse, 
    NetBirdSetupKeyCreate, 
    NetBirdSetupKeyUpdate
)
from fastapi_app.services.netbird.setup_keys import NetBirdSetupKeyService

router = APIRouter(prefix="/api/v2/netbird/setup-keys", tags=["NetBird Setup Keys"])

def handle_result(result):
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=result["status_code"], detail=f"NetBird Error: {result['detail']}")
    return result

@router.get("", response_model=List[NetBirdSetupKeyResponse])
def list_setup_keys():
    return handle_result(NetBirdSetupKeyService.list_setup_keys())

@router.post("", response_model=NetBirdSetupKeyResponse, status_code=status.HTTP_201_CREATED)
def create_setup_key(payload: NetBirdSetupKeyCreate):
    return handle_result(NetBirdSetupKeyService.create_setup_key(payload))

@router.get("/{key_id}", response_model=NetBirdSetupKeyResponse)
def retrieve_setup_key(key_id: str):
    return handle_result(NetBirdSetupKeyService.get_setup_key(key_id))

@router.put("/{key_id}", response_model=NetBirdSetupKeyResponse)
def update_setup_key(key_id: str, payload: NetBirdSetupKeyUpdate):
    return handle_result(NetBirdSetupKeyService.update_setup_key(key_id, payload))

@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_setup_key(key_id: str):
    result = NetBirdSetupKeyService.delete_setup_key(key_id)
    handle_result(result)
    return