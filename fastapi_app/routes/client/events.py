"""
Client-portal event log — `/api/v2/client/peers/{peer_id}/events/...`.

Called by the portal's JS through nginx (dashboard host), authenticated by
the client session cookie, not INTERNAL_API_KEY: registered in main.py
without `_auth`. `get_client_peer` limits every route to the client's own
peers; changes also need CSRF + a writable subscription.

Errors: {"detail": "<terse>", "code": "<offline|logs_disabled|unsupported|…>"}
(EventsError, handled in main.py).
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from fastapi_app.dependencies import get_client_peer, require_client_write
from fastapi_app.schemas.client.events import (
    LogConfigUpdate,
    LogEventsResponse,
    LogLevel,
    LogServiceUpdate,
)
from fastapi_app.services.client import events_service

router = APIRouter(prefix="/api/v2/client/peers/{peer_id}/events", tags=["Client events"])

_CATEGORIES = r"^[a-z_]+(,[a-z_]+)*$"


@router.get("", response_model=LogEventsResponse)
def list_events(
    peer: dict = Depends(get_client_peer),
    category: Optional[str] = Query(None, pattern=_CATEGORIES, max_length=200),
    level: Optional[LogLevel] = None,
    since: Optional[str] = Query(None, max_length=40),
    until: Optional[str] = Query(None, max_length=40),
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=500),
    before_id: Optional[int] = Query(None, ge=0),
    after_id: Optional[int] = Query(None, ge=0),
):
    filters = {"category": category, "level": level.value if level else None, "since": since,
               "until": until, "q": q, "limit": limit, "before_id": before_id, "after_id": after_id}
    return events_service.list_events(peer, filters)


@router.get("/stream")
async def stream_events(
    peer: dict = Depends(get_client_peer),
    category: Optional[str] = Query(None, pattern=_CATEGORIES, max_length=200),
    level: Optional[LogLevel] = None,
    q: Optional[str] = Query(None, max_length=200),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID", max_length=20),
):
    filters = {"category": category, "level": level.value if level else None, "q": q}
    events = await events_service.open_stream(peer, filters, last_event_id)
    return StreamingResponse(
        events, media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/categories")
def list_categories(peer: dict = Depends(get_client_peer)):
    return {"categories": events_service.list_categories(peer)}


@router.get("/config")
def get_config(peer: dict = Depends(get_client_peer)):
    return events_service.get_config(peer)


@router.put("/config", dependencies=[Depends(require_client_write)])
def update_config(payload: LogConfigUpdate, peer: dict = Depends(get_client_peer)):
    return events_service.update_config(peer, payload.model_dump(mode="json", exclude_none=True))


@router.delete("", dependencies=[Depends(require_client_write)])
def clear_events(
    peer: dict = Depends(get_client_peer),
    category: Optional[str] = Query(None, pattern=_CATEGORIES, max_length=200),
):
    return events_service.clear_events(peer, category)


@router.put("/service", dependencies=[Depends(require_client_write)])
def set_service(payload: LogServiceUpdate, peer: dict = Depends(get_client_peer)):
    return events_service.set_logs_service(peer, payload.state.value)
