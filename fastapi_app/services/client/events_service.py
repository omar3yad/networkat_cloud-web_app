"""
Client-portal event log — proxy to the peer agent's `/logs/*` (agent docs/logs.md).

Client audience only: this module never calls `/logs/system/admin` or
`audience=admin`, and every entry is cut down to CLIENT_ENTRY_FIELDS before
it leaves (the agent already omits admin fields on client routes; this is
the second lock).

Changes carry `X-Networkat-Actor: client`, so the peer records them as
"… by client.". The agent listens on the mesh IP only; no auth token.

The live stream is proxied without holding a worker thread: an asyncio socket
plus h11 (already installed with uvicorn), since `requests` is blocking and
the stream stays open up to 30 minutes.
"""
import asyncio
import json
from typing import AsyncIterator, Optional
from urllib.parse import urlencode

import h11
import requests

from fastapi_app.schemas.client.events import CLIENT_ENTRY_FIELDS

AGENT_PORT = 8765
AGENT_TIMEOUT = (5, 20)          # connect, read — the agent runs logs_engine.py per call
STREAM_CONNECT_TIMEOUT = 5
STREAM_FIRST_BYTE_TIMEOUT = 20
STREAM_IDLE_TIMEOUT = 45         # agent sends `: keepalive` every 15 s

ACTOR_HEADERS = {"X-Networkat-Actor": "client"}
SERVICE_SOURCE = "customer"      # agent ServiceSource for a customer's own toggle

# Filters a client may pass through (agent LOG_QUERY_PARAMS minus code/subject/actor).
LIST_FILTERS = ("category", "level", "since", "until", "q", "limit", "before_id", "after_id")
STREAM_FILTERS = ("category", "level", "q")


class EventsError(Exception):
    """Terse, client-safe failure. `code` lets the page pick its state (offline, off, …)."""

    def __init__(self, status_code: int, detail: str, code: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


def _offline() -> EventsError:
    return EventsError(503, "Device offline", "offline")


def _agent_error(status_code: int, body) -> EventsError:
    code = body.get("code") if isinstance(body, dict) else None
    if code == "logs_disabled":
        return EventsError(403, "Event log off", "logs_disabled")
    if code == "bad_category":
        return EventsError(404, "Unknown category", "bad_category")
    if status_code == 400:
        return EventsError(400, "Invalid request", "usage")
    if status_code == 404:
        # No /logs routes at all: an agent from before the event log.
        return EventsError(501, "Update device", "unsupported")
    if status_code == 503:
        return EventsError(502, "Event log unavailable", code or "state_failed")
    return EventsError(502, "Device error", "agent_error")


def _host(peer: dict) -> str:
    if not peer.get("connected") or not peer.get("ip"):
        raise _offline()
    return peer["ip"]


def _call(peer: dict, method: str, path: str, *, params=None, json_body=None, actor=False) -> dict:
    url = f"http://{_host(peer)}:{AGENT_PORT}{path}"
    try:
        resp = requests.request(
            method, url, params=params, json=json_body,
            headers=ACTOR_HEADERS if actor else None, timeout=AGENT_TIMEOUT,
        )
    except requests.RequestException:
        raise _offline()
    try:
        body = resp.json()
    except ValueError:
        body = None
    if resp.status_code >= 400 or not isinstance(body, dict):
        raise _agent_error(resp.status_code, body)
    return body


def _pick(filters: dict, allowed: tuple) -> dict:
    return {k: filters[k] for k in allowed if filters.get(k) not in (None, "")}


def client_entry(entry: dict) -> dict:
    return {k: entry[k] for k in CLIENT_ENTRY_FIELDS if k in entry}


# ── Reads ─────────────────────────────────────────────────────────────────────

def list_events(peer: dict, filters: dict) -> dict:
    body = _call(peer, "GET", "/logs/system/client", params=_pick(filters, LIST_FILTERS))
    return {
        "entries": [client_entry(e) for e in body.get("entries") or [] if isinstance(e, dict)],
        "page": body.get("page") or {"limit": 0, "count": 0, "has_more": False},
        "last_id": body.get("last_id"),
    }


def list_categories(peer: dict) -> list:
    return _call(peer, "GET", "/logs/system/categories", params={"audience": "client"}).get("categories") or []


def get_config(peer: dict) -> dict:
    body = _call(peer, "GET", "/logs/system/config")
    body.pop("ok", None)
    return body


# ── Changes (actor: client) ───────────────────────────────────────────────────

def update_config(peer: dict, update: dict) -> dict:
    body = _call(peer, "PUT", "/logs/system/config", json_body=update, actor=True)
    body.pop("ok", None)
    return body


def clear_events(peer: dict, categories: Optional[str]) -> dict:
    params = {"category": categories} if categories else None
    body = _call(peer, "DELETE", "/logs/system/client", params=params, actor=True)
    return {"cleared": body.get("cleared") or [], "up_to_id": body.get("up_to_id")}


def set_logs_service(peer: dict, state: str) -> dict:
    _call(peer, "PUT", "/services/logs", json_body={"state": state, "source": SERVICE_SOURCE}, actor=True)
    return {"state": state}


# ── Live stream (SSE) ─────────────────────────────────────────────────────────

class _AgentStream:
    """One HTTP/1.1 GET to the agent over an asyncio socket, parsed by h11."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self._conn = h11.Connection(h11.CLIENT)

    async def send(self, target: str, headers: list) -> None:
        self._writer.write(self._conn.send(h11.Request(method="GET", target=target, headers=headers)))
        self._writer.write(self._conn.send(h11.EndOfMessage()))
        await self._writer.drain()

    async def next_event(self, timeout: float):
        while True:
            event = self._conn.next_event()
            if event is not h11.NEED_DATA:
                return event
            data = await asyncio.wait_for(self._reader.read(65536), timeout)
            self._conn.receive_data(data)  # b"" = connection closed

    async def read_body(self, timeout: float) -> bytes:
        body = b""
        while True:
            event = await self.next_event(timeout)
            if isinstance(event, h11.Data):
                body += event.data
            else:
                return body

    def close(self) -> None:
        self._writer.close()


def _filter_sse_block(block: bytes) -> bytes:
    """Re-encode `data:` of one SSE event through client_entry; other lines as-is."""
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
    """Connect and check the agent's answer (errors raise EventsError before any
    stream bytes, like the agent itself). Returns the SSE byte iterator."""
    host = _host(peer)
    query = urlencode(_pick(filters, STREAM_FILTERS))
    target = "/logs/system/client/stream" + (f"?{query}" if query else "")
    headers = [("Host", f"{host}:{AGENT_PORT}"), ("Accept", "text/event-stream"), ("Connection", "close")]
    if last_event_id and last_event_id.isdigit():
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
    except EventsError:
        stream.close()
        raise
    except (OSError, asyncio.TimeoutError, h11.ProtocolError):
        stream.close()
        raise _offline()

    async def events() -> AsyncIterator[bytes]:
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
            return  # peer gone quiet or dropped; the reconnect rechecks it
        finally:
            stream.close()

    return events()
