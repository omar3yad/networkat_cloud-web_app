# /opt/networkat_sdwan/core/web_app/fastapi_app/routes/netbird/peers.py
from fastapi import APIRouter, HTTPException, status, Query
from typing import List, Optional
from fastapi_app.schemas.netbird.peers import (
    NetBirdPeerResponse, 
    NetBirdPeerUpdate, 
    AccessiblePeerResponse, 
    TemporaryAccessRequest, 
    TemporaryAccessResponse
)
from fastapi_app.services.netbird.peers import NetBirdPeerService

router = APIRouter(prefix="/api/v2/netbird/peers", tags=["NetBird Peers"])

def handle_result(result):
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=result["status_code"], detail=f"NetBird Error: {result['detail']}")
    return result

@router.get("", response_model=List[NetBirdPeerResponse])
def list_all_peers(
    name: Optional[str] = Query(None, description="Filter peers by name"),
    ip: Optional[str] = Query(None, description="Filter peers by IP address")
):
    return handle_result(NetBirdPeerService.list_peers(name, ip))

@router.get("/{peer_id}", response_model=NetBirdPeerResponse)
def retrieve_peer(peer_id: str):
    return handle_result(NetBirdPeerService.get_peer(peer_id))

@router.put("/{peer_id}", response_model=NetBirdPeerResponse)
def update_peer(peer_id: str, payload: NetBirdPeerUpdate):
    return handle_result(NetBirdPeerService.update_peer(peer_id, payload))

@router.delete("/{peer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_peer(peer_id: str):
    result = NetBirdPeerService.delete_peer(peer_id)
    handle_result(result)
    return

@router.get("/{peer_id}/accessible-peers", response_model=List[AccessiblePeerResponse])
def list_accessible_peers(peer_id: str):
    return handle_result(NetBirdPeerService.list_accessible_peers(peer_id))

@router.post("/{peer_id}/temporary-access", response_model=TemporaryAccessResponse)
def create_temporary_access_peer(peer_id: str, payload: TemporaryAccessRequest):
    return handle_result(NetBirdPeerService.create_temporary_access(peer_id, payload))