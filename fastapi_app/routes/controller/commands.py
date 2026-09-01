"""
/opt/networkat_sdwan/core/web_app/fastapi_app/routes/controller/commands.py
Controller endpoints — internal API, called by the Flask dashboard backend
after it has authenticated the user via session.
This module directly interacts with peers via peer_id without client_id scoping.
Do not expose this router on a public-facing port without adding an
internal-only network restriction or a shared-secret header between the
Flask app and this FastAPI service.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session

from fastapi_app.dependencies import get_db
from fastapi_app.schemas.controller.commands import (
    ExecuteCommandRequest,
    CommandResponse,
    CommandStatus,
    PeerStatusResponse,
    PeerSummary,
    HandshakeResponse,
)
from fastapi_app.services.controller.command_service import (
    execute_command,
    get_peer_status,
    list_peers as list_all_peers,
    handshake as handshake_check,
    CommandError,
)

router = APIRouter(prefix="/api/v1/peers", tags=["Controller"])


@router.post("/{peer_id}/commands", response_model=CommandResponse)
async def send_command(
    peer_id: str,
    payload: ExecuteCommandRequest,
    db: Session = Depends(get_db),
):
    try:
        result = await execute_command(
            db,
            peer_id=peer_id,
            command_type=payload.command_type,
            parameters=payload.parameters,
            requested_by=payload.requested_by,
        )
        return CommandResponse(**result)
    except CommandError as exc:
        return CommandResponse(
            id=exc.log_id,
            peer_id=peer_id,
            command_type=payload.command_type.value,
            status=CommandStatus.REJECTED,
            reject_reason=exc.reason,
            output=None,
            error=str(exc),
            requested_at=exc.requested_at,
            executed_at=None,
        )


@router.get("/{peer_id}/status", response_model=PeerStatusResponse)
async def peer_status(peer_id: str):
    try:
        result = await get_peer_status(peer_id=peer_id)
        return PeerStatusResponse(**result)
    except CommandError as exc:
        if exc.reason == "peer_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("", response_model=list[PeerSummary])
async def list_peers():
    try:
        peers = await list_all_peers()
        return [PeerSummary(**p) for p in peers]
    except CommandError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("/{peer_id}/handshake", response_model=HandshakeResponse)
async def handshake(peer_id: str):
    result = await handshake_check(peer_id)
    return HandshakeResponse(**result)