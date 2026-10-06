# /opt/networkat_sdwan/core/web_app/fastapi_app/routes/admin/peers.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from fastapi_app.dependencies import get_db
from fastapi_app.schemas.admin.peers import AdminPeersResponse
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
