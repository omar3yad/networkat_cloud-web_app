"""
Client-portal intrusion detection — `/api/v2/client/peers/{peer_id}/ids/...`.

Called by the portal's JS through nginx, authenticated by the client session
cookie (registered in main.py without `_auth`), like client system logs.
`get_client_peer` limits every route to the client's own peers; changes also
need CSRF + a writable subscription.

Browser path -> agent path (services/client/ids_ips_service.py):
  ""                    -> /ids-ips                status
  /enabled              -> /ids-ips/detection      the switch
  /settings[/reset]     -> /ids-ips/settings[/reset]
  /rules/{sid}          -> /ids-ips/rules/{sid}
  /custom-rules, /muted, /excluded, /watchlists [/batch]
                        -> /ids-ips/custom-rules, suppressions, exclusions, watchlists [/batch]
  /threats[/stream], /threats/summary
                        -> /logs/ids-ips/events[/stream], /logs/ids-ips/summary

Errors: {"detail": "<terse>", "code": "<offline|unsupported|busy|…>"}
(IdsError, handled in main.py).
"""
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, Header, Path, Query
from fastapi.responses import StreamingResponse

from fastapi_app.dependencies import get_client_peer, require_client_write
from fastapi_app.schemas.client.ids_ips import (
    CustomRulesOrder,
    Direction,
    EnabledUpdate,
    ListBatch,
    RuleChange,
    SettingsReset,
)
from fastapi_app.services.client import ids_ips_service
from fastapi_app.services.client.ids_ips_service import IdsError
from fastapi_app.services.client.session import ClientSession

router = APIRouter(prefix="/api/v2/client/peers/{peer_id}/ids", tags=["Client IDS"])

_SEVERITIES = r"^(high|medium|low)(,(high|medium|low))*$"
_ITEM_ID = r"^[0-9a-f]{1,64}$"
ListName = Literal["custom-rules", "muted", "excluded", "watchlists"]


# ── Status and switch ─────────────────────────────────────────────────────────

@router.get("")
def get_status(peer: dict = Depends(get_client_peer)):
    return ids_ips_service.get_status(peer)


@router.put("/enabled")
def set_enabled(
    payload: EnabledUpdate,
    peer: dict = Depends(get_client_peer),
    session: ClientSession = Depends(require_client_write),
):
    return ids_ips_service.set_enabled(peer, payload.enabled, session.customer_id)


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(peer: dict = Depends(get_client_peer)):
    return ids_ips_service.get_settings(peer)


@router.put("/settings", dependencies=[Depends(require_client_write)])
def update_settings(payload: dict[str, Any] = Body(..., min_length=1), peer: dict = Depends(get_client_peer)):
    return ids_ips_service.update_settings(peer, payload)


@router.post("/settings/reset", dependencies=[Depends(require_client_write)])
def reset_settings(payload: SettingsReset, peer: dict = Depends(get_client_peer)):
    return ids_ips_service.reset_settings(peer, payload.section)


@router.put("/rules/{sid}", dependencies=[Depends(require_client_write)])
def set_rule(payload: RuleChange, sid: int = Path(ge=1, le=2147483647), peer: dict = Depends(get_client_peer)):
    change = payload.model_dump(mode="json", exclude_unset=True)
    if not change:
        raise IdsError(400, "Invalid request", "usage")
    return ids_ips_service.set_rule(peer, sid, change)


@router.delete("/rules/{sid}", dependencies=[Depends(require_client_write)])
def remove_rule(sid: int = Path(ge=1, le=2147483647), peer: dict = Depends(get_client_peer)):
    return ids_ips_service.remove_rule(peer, sid)


# ── Threats (before the /{list_name} routes) ──────────────────────────────────

@router.get("/threats")
def list_threats(
    peer: dict = Depends(get_client_peer),
    severity: Optional[str] = Query(None, pattern=_SEVERITIES, max_length=30),
    kind: Optional[str] = Query(None, max_length=40),
    device: Optional[str] = Query(None, max_length=15),
    sid: Optional[int] = Query(None, ge=1, le=2147483647),
    direction: Optional[Direction] = None,
    since: Optional[str] = Query(None, max_length=40),
    until: Optional[str] = Query(None, max_length=40),
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=500),
    before_id: Optional[int] = Query(None, ge=0),
    after_id: Optional[int] = Query(None, ge=0),
):
    filters = {"severity": severity, "kind": kind, "device": device, "sid": sid,
               "direction": direction.value if direction else None, "since": since, "until": until,
               "q": q, "limit": limit, "before_id": before_id, "after_id": after_id}
    return ids_ips_service.list_threats(peer, filters)


@router.get("/threats/stream")
async def stream_threats(
    peer: dict = Depends(get_client_peer),
    severity: Optional[str] = Query(None, pattern=_SEVERITIES, max_length=30),
    kind: Optional[str] = Query(None, max_length=40),
    device: Optional[str] = Query(None, max_length=15),
    direction: Optional[Direction] = None,
    q: Optional[str] = Query(None, max_length=200),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID", max_length=40),
):
    filters = {"severity": severity, "kind": kind, "device": device,
               "direction": direction.value if direction else None, "q": q}
    entries = await ids_ips_service.open_stream(peer, filters, last_event_id)
    return StreamingResponse(entries, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/threats/summary")
def threats_summary(peer: dict = Depends(get_client_peer), since: Optional[str] = Query(None, max_length=40)):
    return ids_ips_service.summary(peer, since)


@router.delete("/threats", dependencies=[Depends(require_client_write)])
def clear_threats(peer: dict = Depends(get_client_peer)):
    return ids_ips_service.clear_threats(peer)


# ── The four lists ────────────────────────────────────────────────────────────

@router.put("/custom-rules/order", dependencies=[Depends(require_client_write)])
def reorder_custom_rules(payload: CustomRulesOrder, peer: dict = Depends(get_client_peer)):
    return ids_ips_service.reorder_custom_rules(peer, payload.ids)


@router.get("/{list_name}")
def list_items(list_name: ListName, peer: dict = Depends(get_client_peer)):
    return ids_ips_service.list_items(peer, list_name)


@router.post("/{list_name}", status_code=201, dependencies=[Depends(require_client_write)])
def add_item(
    list_name: ListName,
    payload: dict[str, Any] | list[dict[str, Any]] = Body(...),
    peer: dict = Depends(get_client_peer),
):
    """One object or a list of them (every item or none)."""
    if isinstance(payload, list) and not 1 <= len(payload) <= 100:
        raise IdsError(400, "Invalid request", "usage")
    return ids_ips_service.add_item(peer, list_name, payload)


@router.post("/{list_name}/batch", dependencies=[Depends(require_client_write)])
def batch_items(list_name: ListName, payload: ListBatch, peer: dict = Depends(get_client_peer)):
    if not (payload.add or payload.update or payload.remove):
        raise IdsError(400, "Invalid request", "usage")
    return ids_ips_service.batch_items(peer, list_name, payload.model_dump())


@router.put("/{list_name}/{item_id}", dependencies=[Depends(require_client_write)])
def replace_item(
    list_name: ListName,
    item_id: str = Path(pattern=_ITEM_ID),
    payload: dict[str, Any] = Body(...),
    peer: dict = Depends(get_client_peer),
):
    if list_name == "muted":
        raise IdsError(400, "Invalid request", "usage")  # no update: delete and add
    return ids_ips_service.replace_item(peer, list_name, item_id, payload)


@router.delete("/{list_name}/{item_id}", dependencies=[Depends(require_client_write)])
def remove_item(list_name: ListName, item_id: str = Path(pattern=_ITEM_ID), peer: dict = Depends(get_client_peer)):
    return ids_ips_service.remove_item(peer, list_name, item_id)
