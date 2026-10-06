"""
Client-portal intrusion detection (IDS) — proxy to the peer agent's `/ids-ips/*`
and `/logs/ids-ips/*` (agent docs/agent-api/ids-ips.md).

What the client never sees, cut here both ways (dropped from replies, refused in
requests):
  - prevention: the `prevention` status block and settings section; no route;
  - failsafe: removed from `locks`/`source` (failsafe alone reads `unavailable`);
  - `community_id` (threats and the `events.community_id` setting) and a threat's `action`;
  - watchlists of kind `certificates` / `client_fingerprints`;
  - the agent's `message`: replies carry `code`/`applied`/`changed`/…, the page
    writes its own text.

Changes carry `X-Networkat-Actor: client`. Turning IDS on also removes the
`subscription` lock when `ids_allowed()` says the customer has it.

Agent waits 25 s for a write and answers 503 past that; a write that timed out
is re-read and reported as saved when the change is there.
"""
import asyncio
import json
import time
from typing import AsyncIterator, Optional
from urllib.parse import urlencode

import h11
import requests

from fastapi_app.services.client.system_logs_service import _AgentStream

AGENT_PORT = 8765
AGENT_TIMEOUT = (5, 35)          # connect, read — the agent itself gives up at 25 s
STREAM_CONNECT_TIMEOUT = 5
STREAM_FIRST_BYTE_TIMEOUT = 20
STREAM_IDLE_TIMEOUT = 45         # agent sends `: keepalive` every 15 s
BUSY_RETRIES = 1                 # the agent already waits 20 s before busy; nginx cuts at 60 s
BUSY_WAIT = 3

ACTOR_HEADERS = {"X-Networkat-Actor": "client"}
SERVICE = "intrusion_detection"
SOURCE_RANK = ("subscription", "customer", "manual")   # failsafe left out on purpose

HIDDEN_SETTINGS = {"prevention": None, "events": ("community_id",)}
HIDDEN_ENTRY_FIELDS = ("community_id", "action")
CLIENT_WATCHLIST_KINDS = ("names", "addresses")

LIST_FILTERS = ("severity", "kind", "device", "sid", "direction", "since", "until", "q",
                "limit", "before_id", "after_id")
STREAM_FILTERS = ("severity", "kind", "device", "direction", "q")

REPLY_FIELDS = ("code", "applied", "inspection_gap_seconds", "changed", "notes")


class IdsError(Exception):
    """Terse, client-safe failure. `code` lets the page pick its state."""

    def __init__(self, status_code: int, detail: str, code: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


def ids_allowed(customer_id: str) -> bool:
    """The one place that decides whether a customer has IDS. Everyone, for now."""
    return True


def _offline() -> IdsError:
    return IdsError(503, "Device offline", "offline")


_CODE_ERRORS = {
    "usage": (400, "Invalid request"),
    "invalid_settings": (400, "Invalid value"),
    "limit_reached": (400, "Limit reached"),
    "alias_not_found": (409, "Alias not found"),
    "alias_wrong_type": (409, "Wrong alias type"),
    "locked": (409, "Unavailable now"),
    "insufficient_memory": (409, "Not enough memory"),
    "not_available": (400, "Invalid request"),
    "busy": (409, "Busy, try again"),
}


def _agent_error(status_code: int, body) -> IdsError:
    code = body.get("code") if isinstance(body, dict) else None
    if code == "locked":
        return IdsError(409, "Unavailable now", "unavailable")
    if code in _CODE_ERRORS:
        status, detail = _CODE_ERRORS[code]
        return IdsError(status, detail, code)
    if status_code == 404:
        # The plugin's own not_found carries a sentence; FastAPI's route miss is "Not Found".
        if isinstance(body, dict) and body.get("detail") not in (None, "Not Found"):
            return IdsError(404, "Not found", "not_found")
        return IdsError(501, "Update device", "unsupported")
    if status_code in (400, 422):
        return IdsError(400, "Invalid request", "usage")
    if status_code == 503:
        return IdsError(502, "Device error", "engine_error")
    return IdsError(502, "Device error", "agent_error")


class _Timeout(Exception):
    """A write the agent did not confirm in time (503 / read timeout)."""


def _host(peer: dict) -> str:
    if not peer.get("connected") or not peer.get("ip"):
        raise _offline()
    return peer["ip"]


def _request(peer: dict, method: str, path: str, *, params=None, json_body=None, actor=False):
    url = f"http://{_host(peer)}:{AGENT_PORT}{path}"
    try:
        resp = requests.request(method, url, params=params, json=json_body,
                                headers=ACTOR_HEADERS if actor else None, timeout=AGENT_TIMEOUT)
    except requests.ReadTimeout:
        if actor:
            raise _Timeout()
        raise _offline()
    except requests.RequestException:
        raise _offline()
    try:
        body = resp.json()
    except ValueError:
        body = None
    return resp.status_code, body


def _call(peer: dict, method: str, path: str, *, params=None, json_body=None) -> dict:
    status, body = _request(peer, method, path, params=params, json_body=json_body)
    if status >= 400 or not isinstance(body, dict):
        raise _agent_error(status, body)
    return body


def _write(peer: dict, method: str, path: str, json_body=None, *, params=None) -> dict:
    """A change: client actor, `busy` retried, an unconfirmed reply raised as _Timeout."""
    for attempt in range(BUSY_RETRIES + 1):
        status, body = _request(peer, method, path, params=params, json_body=json_body, actor=True)
        code = body.get("code") if isinstance(body, dict) else None
        if status == 409 and code == "busy" and attempt < BUSY_RETRIES:
            time.sleep(BUSY_WAIT)
            continue
        if status == 503 and code is None:
            raise _Timeout()
        if status >= 400 or not isinstance(body, dict):
            raise _agent_error(status, body)
        return body
    raise _agent_error(409, {"code": "busy"})


def _unconfirmed() -> IdsError:
    return IdsError(504, "Not confirmed, refresh", "unconfirmed")


def _reply(body: dict, **extra) -> dict:
    out = {k: body[k] for k in REPLY_FIELDS if k in body}
    out.update(extra)
    return out


# ── Hiding ────────────────────────────────────────────────────────────────────

def client_status(body: dict) -> dict:
    det = dict(body.get("detection") or {})
    locks = [l for l in det.get("locks") or [] if l != "failsafe"]
    failsafe = "failsafe" in (det.get("locks") or [])
    det["locks"] = locks
    if det.get("source") == "failsafe":
        det["source"] = next((s for s in SOURCE_RANK if s in locks), None)
    if failsafe and not locks:
        det["state"] = "unavailable"
    out = {"detection": det}
    for key in ("rules", "engine"):
        if key in body:
            out[key] = body[key]
    return out


def _strip_settings_doc(doc: dict) -> dict:
    doc = dict(doc or {})
    for section, fields in HIDDEN_SETTINGS.items():
        if fields is None:
            doc.pop(section, None)
        elif isinstance(doc.get(section), dict):
            doc[section] = {k: v for k, v in doc[section].items() if k not in fields}
    return doc


def _hidden_name(dotted: str) -> bool:
    section, _, field = dotted.partition(".")
    if section not in HIDDEN_SETTINGS:
        return False
    fields = HIDDEN_SETTINGS[section]
    return fields is None or field.split(".")[0] in fields


def client_settings(body: dict) -> dict:
    out = {
        "settings": _strip_settings_doc(body.get("settings")),
        "defaults": _strip_settings_doc(body.get("defaults")),
        "customized": [n for n in body.get("customized") or [] if not _hidden_name(n)],
        "options": {k: v for k, v in (body.get("options") or {}).items() if not _hidden_name(k)},
        "rule_overrides": body.get("rule_overrides") or [],
    }
    return out


def check_settings_update(update: dict) -> None:
    for section, fields in HIDDEN_SETTINGS.items():
        if section not in update:
            continue
        if fields is None or (isinstance(update[section], dict) and set(fields) & set(update[section])):
            raise IdsError(400, "Invalid request", "usage")


def client_entry(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k not in HIDDEN_ENTRY_FIELDS}


def _client_watchlist(item: dict) -> bool:
    return isinstance(item, dict) and item.get("kind") in CLIENT_WATCHLIST_KINDS


def _changed(body: dict) -> dict:
    if isinstance(body.get("changed"), list):
        body = dict(body, changed=[n for n in body["changed"] if not _hidden_name(n)])
    return body


# ── Status and switch ─────────────────────────────────────────────────────────

def get_status(peer: dict) -> dict:
    return client_status(_call(peer, "GET", "/ids-ips"))


def set_enabled(peer: dict, enabled: bool, customer_id: str) -> dict:
    if enabled and ids_allowed(customer_id):
        try:
            _write(peer, "PUT", f"/services/{SERVICE}", {"state": "enabled", "source": "subscription"})
        except _Timeout:
            pass  # the detection call below reports the lock if it is still there
    try:
        body = _write(peer, "PUT", "/ids-ips/detection", {"enabled": enabled})
    except _Timeout:
        status = get_status(peer)
        if ("customer" in status["detection"]["locks"]) != enabled:
            return dict(status, applied="starting" if enabled else "stopping", code="ok")
        raise _unconfirmed()
    except IdsError as exc:
        if exc.code == "unavailable" and not ids_allowed(customer_id):
            raise IdsError(403, "Not in your plan", "upgrade")
        raise
    return dict(client_status(body), **_reply(body))


# ── Settings ──────────────────────────────────────────────────────────────────

def get_settings(peer: dict) -> dict:
    return client_settings(_call(peer, "GET", "/ids-ips/settings"))


def _contains(have, want) -> bool:
    if isinstance(want, dict):
        return isinstance(have, dict) and all(_contains(have.get(k), v) for k, v in want.items())
    if isinstance(want, list):
        # Lists are replaced whole; compare the fields sent, ignoring server-added ids.
        return isinstance(have, list) and len(have) == len(want) and all(
            _contains(h, w) for h, w in zip(have, want))
    return have == want


def update_settings(peer: dict, update: dict) -> dict:
    check_settings_update(update)
    try:
        return _reply(_changed(_write(peer, "PUT", "/ids-ips/settings", update)))
    except _Timeout:
        current = _call(peer, "GET", "/ids-ips/settings").get("settings") or {}
        if _contains(current, update):
            return {"code": "ok", "applied": "pending"}
        raise _unconfirmed()


def reset_settings(peer: dict, section: Optional[str]) -> dict:
    if section in HIDDEN_SETTINGS:
        raise IdsError(400, "Invalid request", "usage")
    try:
        return _reply(_changed(_write(peer, "POST", "/ids-ips/settings/reset", {"section": section})))
    except _Timeout:
        raise _unconfirmed()


def set_rule(peer: dict, sid: int, change: dict) -> dict:
    try:
        body = _write(peer, "PUT", f"/ids-ips/rules/{sid}", change)
    except _Timeout:
        overrides = _call(peer, "GET", "/ids-ips/settings").get("rule_overrides") or []
        row = next((o for o in overrides if o.get("sid") == sid), None)
        if row is not None and all(row.get(k) == v for k, v in change.items()):
            return {"sid": sid, **{k: row.get(k) for k in ("disabled", "severity")},
                    "code": "ok", "applied": "pending"}
        raise _unconfirmed()
    return {"sid": sid, "disabled": body.get("disabled"), "severity": body.get("severity"), **_reply(body)}


def remove_rule(peer: dict, sid: int) -> dict:
    try:
        return {"sid": sid, **_reply(_write(peer, "DELETE", f"/ids-ips/rules/{sid}"))}
    except _Timeout:
        raise _unconfirmed()


# ── The four lists ────────────────────────────────────────────────────────────
# Browser name -> agent path.
LISTS = {
    "custom-rules": "/ids-ips/custom-rules",
    "muted": "/ids-ips/suppressions",
    "excluded": "/ids-ips/exclusions",
    "watchlists": "/ids-ips/watchlists",
}


def list_items(peer: dict, name: str) -> dict:
    items = _call(peer, "GET", LISTS[name]).get("items") or []
    if name == "watchlists":
        items = [i for i in items if _client_watchlist(i)]
    return {"items": items}


def _client_item(name: str, item) -> dict:
    """One item from the browser: refuse what the client may not send and
    turn an excluded `address` into the peer's host / network."""
    if not isinstance(item, dict):
        raise IdsError(400, "Invalid request", "usage")
    if name == "watchlists" and not _client_watchlist(item):
        raise IdsError(400, "Invalid request", "usage")
    if name == "excluded" and item.get("target") == "address":
        value = item.get("value")
        target = "network" if isinstance(value, str) and "/" in value else "host"
        item = dict(item, target=target)
    return item


def _list_write(peer: dict, name: str, method: str, suffix: str = "", body=None) -> dict:
    if body is not None and suffix != "/order":
        body = [_client_item(name, i) for i in body] if isinstance(body, list) else _client_item(name, body)
    if name == "watchlists" and method in ("PUT", "DELETE"):
        current = _call(peer, "GET", LISTS[name]).get("items") or []
        target = next((i for i in current if i.get("id") == suffix.strip("/")), None)
        if target is not None and not _client_watchlist(target):
            raise IdsError(404, "Not found", "not_found")
    try:
        reply = _write(peer, method, LISTS[name] + suffix, body)
    except _Timeout:
        raise _unconfirmed()
    out = _reply(reply)
    for key in ("item", "items"):
        if key in reply:
            out[key] = reply[key]
    return out


def add_item(peer: dict, name: str, item) -> dict:
    """One object -> {"item"}; a list -> {"items"}, every item or none."""
    return _list_write(peer, name, "POST", body=item)


def batch_items(peer: dict, name: str, change: dict) -> dict:
    """remove / update / add in one request: one transaction and one apply on the peer."""
    if name == "muted" and change.get("update"):
        raise IdsError(400, "Invalid request", "usage")  # no update: delete and add
    add = [_client_item(name, i) for i in change.get("add") or []]
    update = [_client_item(name, i) for i in change.get("update") or []]
    remove = list(change.get("remove") or [])
    if name == "watchlists" and (update or remove):
        current = {i.get("id"): i for i in _call(peer, "GET", LISTS[name]).get("items") or []}
        for item_id in remove + [u.get("id") for u in update]:
            if item_id in current and not _client_watchlist(current[item_id]):
                raise IdsError(404, "Not found", "not_found")
    try:
        reply = _write(peer, "POST", LISTS[name] + "/batch", {"add": add, "update": update, "remove": remove})
    except _Timeout:
        raise _unconfirmed()
    out = _reply(reply)
    for key in ("added", "updated", "removed"):
        out[key] = reply.get(key) or []
    return out


def replace_item(peer: dict, name: str, item_id: str, item: dict) -> dict:
    return _list_write(peer, name, "PUT", f"/{item_id}", item)


def remove_item(peer: dict, name: str, item_id: str) -> dict:
    return _list_write(peer, name, "DELETE", f"/{item_id}")


def reorder_custom_rules(peer: dict, ids: list) -> dict:
    return _list_write(peer, "custom-rules", "PUT", "/order", {"ids": ids})


# ── Threats ───────────────────────────────────────────────────────────────────

def _pick(filters: dict, allowed: tuple) -> dict:
    return {k: filters[k] for k in allowed if filters.get(k) not in (None, "")}


def list_threats(peer: dict, filters: dict) -> dict:
    params = dict(_pick(filters, LIST_FILTERS), audience="client")
    body = _call(peer, "GET", "/logs/ids-ips/events", params=params)
    return {
        "entries": [client_entry(e) for e in body.get("entries") or [] if isinstance(e, dict)],
        "page": body.get("page") or {"limit": 0, "count": 0, "has_more": False},
        "last_id": body.get("last_id"),
    }


def summary(peer: dict, since: Optional[str]) -> dict:
    params = {"since": since} if since else None
    return _call(peer, "GET", "/logs/ids-ips/summary", params=params)


def clear_threats(peer: dict) -> dict:
    try:
        body = _write(peer, "DELETE", "/logs/ids-ips/events")
    except _Timeout:
        raise _unconfirmed()
    return {"removed": body.get("removed", 0), "code": "ok"}


def _filter_sse_block(block: bytes) -> bytes:
    lines = []
    for line in block.split(b"\n"):
        if line.startswith(b"data:"):
            try:
                entry = json.loads(line[5:].strip())
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            line = b"data: " + json.dumps(client_entry(entry)).encode()
        lines.append(line)
    return b"\n".join(lines) + b"\n\n"


async def open_stream(peer: dict, filters: dict, last_event_id: Optional[str]) -> AsyncIterator[bytes]:
    """Connect and check the agent's answer (errors raise IdsError before any
    stream bytes). Returns the SSE byte iterator."""
    host = _host(peer)
    query = urlencode(dict(_pick(filters, STREAM_FILTERS), audience="client"))
    target = "/logs/ids-ips/events/stream?" + query
    headers = [("Host", f"{host}:{AGENT_PORT}"), ("Accept", "text/event-stream"), ("Connection", "close")]
    if last_event_id and all(p.isdigit() for p in last_event_id.split(":", 1)):
        headers.append(("Last-Event-ID", last_event_id))

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, AGENT_PORT), STREAM_CONNECT_TIMEOUT)
    except (OSError, asyncio.TimeoutError):
        raise _offline()
    stream = _AgentStream(reader, writer)
    try:
        await stream.send(target, headers)
        response = await stream.next_event(STREAM_FIRST_BYTE_TIMEOUT)
        if not isinstance(response, h11.Response):
            raise _offline()
        if response.status_code != 200:
            try:
                body = json.loads(await stream.read_body(STREAM_FIRST_BYTE_TIMEOUT) or b"null")
            except ValueError:
                body = None
            raise _agent_error(response.status_code, body)
    except IdsError:
        stream.close()
        raise
    except (OSError, asyncio.TimeoutError, h11.ProtocolError):
        stream.close()
        raise _offline()

    async def entries() -> AsyncIterator[bytes]:
        buffer = b""
        try:
            while True:
                event = await stream.next_event(STREAM_IDLE_TIMEOUT)
                if not isinstance(event, h11.Data):
                    return  # agent ended the stream (30 min) — the browser reconnects
                buffer += event.data
                *blocks, buffer = buffer.split(b"\n\n")
                for block in blocks:
                    yield _filter_sse_block(block)
        except (OSError, asyncio.TimeoutError, h11.ProtocolError):
            return
        finally:
            stream.close()

    return entries()
