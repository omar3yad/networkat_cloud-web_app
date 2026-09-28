"""
Client-portal system logs — `/api/v2/client/peers/{peer_id}/logs/system/...`.

Called by the portal's JS through nginx (dashboard host), authenticated by
the client session cookie, not INTERNAL_API_KEY: registered in main.py
without `_auth`. `get_client_peer` limits every route to the client's own
peers; changes also need CSRF + a writable subscription.

Errors: {"detail": "<terse>", "code": "<offline|logs_disabled|unsupported|…>"}
(SystemLogsError, handled in main.py).
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from fastapi_app.dependencies import get_client_peer, require_client_write, get_client_session
from fastapi_app.services.client.session import ClientSession
from fastapi_app.services.client.peer_access import is_paid_client
from fastapi_app.schemas.client.system_logs import (
    LogConfigUpdate,
    SystemLogsResponse,
    LogLevel,
    LogServiceUpdate,
)
from fastapi_app.services.client import system_logs_service
from services.settings_service import settings as app_settings

router = APIRouter(prefix="/api/v2/client/peers/{peer_id}/logs/system", tags=["Client system logs"])

_CATEGORIES = r"^[a-z_]+(,[a-z_]+)*$"


@router.get("", response_model=SystemLogsResponse)
def list_logs(
    peer: dict = Depends(get_client_peer),
    category: Optional[str] = Query(None, pattern=_CATEGORIES, max_length=200),
    level: Optional[LogLevel] = None,
    since: Optional[str] = Query(None, max_length=40),
    until: Optional[str] = Query(None, max_length=40),
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=500),
    before_id: Optional[int] = Query(None, ge=0),
    after_id: Optional[int] = Query(None, ge=0),
    session: ClientSession = Depends(get_client_session),
):
    filters = {"category": category, "level": level.value if level else None, "since": since,
               "until": until, "q": q, "limit": limit, "before_id": before_id, "after_id": after_id}
    res = system_logs_service.list_logs(peer, filters)

    # Feature Gating: configurable log limit for trial / unpaid users
    trial_log_limit = app_settings.get_int("trial.log_limit", default=3)
    if not is_paid_client(session.customer_id):
        entries = res.get("entries") or []
        res["is_gated"] = True
        if len(entries) > trial_log_limit:
            res["gated_count"] = len(entries) - trial_log_limit
            masked_entries = []
            for idx, entry in enumerate(entries):
                if idx < trial_log_limit:
                    masked_entries.append(entry)
                else:
                    gated_entry = dict(entry)
                    gated_entry["message"] = "Available on paid plans"
                    gated_entry["data"] = None
                    gated_entry["code"] = "paid_only"
                    masked_entries.append(gated_entry)
            res["entries"] = masked_entries
        else:
            res["gated_count"] = 0
    else:
        res["is_gated"] = False
        res["gated_count"] = 0

    return res


@router.get("/stream")
async def stream_logs(
    peer: dict = Depends(get_client_peer),
    category: Optional[str] = Query(None, pattern=_CATEGORIES, max_length=200),
    level: Optional[LogLevel] = None,
    q: Optional[str] = Query(None, max_length=200),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID", max_length=20),
    session: ClientSession = Depends(get_client_session),
):
    filters = {"category": category, "level": level.value if level else None, "q": q}
    raw_entries = await system_logs_service.open_stream(peer, filters, last_event_id)
    is_paid = is_paid_client(session.customer_id)
    trial_log_limit = app_settings.get_int("trial.log_limit", default=3)

    async def _gated_stream():
        count = 0
        async for chunk in raw_entries:
            if not is_paid and chunk.startswith(b"data:"):
                count += 1
                if count > trial_log_limit:
                    yield b"event: gated\ndata: {\"code\":\"paid_only\",\"message\":\"Available on paid plans\"}\n\n"
                    break
            yield chunk

    return StreamingResponse(
        _gated_stream() if not is_paid else raw_entries, media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/categories")
def list_categories(peer: dict = Depends(get_client_peer)):
    return {"categories": system_logs_service.list_categories(peer)}


@router.get("/config")
def get_config(peer: dict = Depends(get_client_peer)):
    return system_logs_service.get_config(peer)


@router.put("/config", dependencies=[Depends(require_client_write)])
def update_config(payload: LogConfigUpdate, peer: dict = Depends(get_client_peer)):
    return system_logs_service.update_config(peer, payload.model_dump(mode="json", exclude_none=True))


@router.delete("", dependencies=[Depends(require_client_write)])
def clear_logs(
    peer: dict = Depends(get_client_peer),
    category: Optional[str] = Query(None, pattern=_CATEGORIES, max_length=200),
):
    return system_logs_service.clear_logs(peer, category)


@router.put("/service", dependencies=[Depends(require_client_write)])
def set_service(payload: LogServiceUpdate, peer: dict = Depends(get_client_peer)):
    return system_logs_service.set_logs_service(peer, payload.state.value)
