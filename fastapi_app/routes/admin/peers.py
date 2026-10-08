# /opt/networkat_sdwan/core/web_app/fastapi_app/routes/admin/peers.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from fastapi_app.dependencies import get_db
from fastapi_app.schemas.admin.peers import (
    AdminPeersResponse,
    AdminPeerDetailResponse,
    AdminPeerActionResponse,
    AdminPeerReconnectResponse,
)
from fastapi_app.services.admin.peers_service import AdminPeersService

router = APIRouter(
    prefix="/api/v2/admin/peers",
    tags=["Admin - Peers Management"]
)


@router.get("", response_model=AdminPeersResponse, summary="List all SD-WAN peers across all customers")
def get_all_peers(
    refresh: bool = Query(default=False, description="Force bypass cache and refresh peer statuses"),
    db: Session = Depends(get_db)
):
    """
    Retrieves a unified inventory of all connected SD-WAN peers and edge devices across customers,
    including live WireGuard handshake verification, customer metadata, and overall network statistics.
    """
    data = AdminPeersService.get_all_peers_data(db=db, force_refresh=refresh)
    return {
        "success": True,
        "peers": data["peers"],
        "stats": data["stats"],
        "customers": data["customers"]
    }


@router.get("/{peer_id}", response_model=AdminPeerDetailResponse, summary="Get details and routes for a specific peer")
def get_peer(peer_id: str, db: Session = Depends(get_db)):
    """
    Retrieves single peer status, customer owner, and associated network routes.
    """
    return AdminPeersService.get_peer_detail(db=db, peer_id=peer_id)


@router.delete("/{peer_id}", response_model=AdminPeerActionResponse, summary="Delete a peer and its routes from network")
def delete_peer(peer_id: str, db: Session = Depends(get_db)):
    """
    Uninstalls client agent, removes associated network routes, and permanently deletes peer.
    """
    return AdminPeersService.delete_peer(db=db, peer_id=peer_id)


@router.post("/{peer_id}/reconnect", response_model=AdminPeerReconnectResponse, summary="Reconnect and check peer handshake")
def reconnect_peer(peer_id: str, db: Session = Depends(get_db)):
    """
    Checks peer live handshake status and triggers network reconnection.
    """
    return AdminPeersService.reconnect_peer(db=db, peer_id=peer_id)

