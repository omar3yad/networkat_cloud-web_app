"""
Client-portal event log proxy (fastapi_app/services/client/events_service.py)
against a fake agent on 127.0.0.1 — real HTTP, and a chunked SSE stream like
uvicorn sends.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from fastapi_app.services.client import events_service as svc

ADMIN_ENTRY = {
    "id": 7, "time": "2026-09-25T10:17:40.123Z", "level": "notice", "category": "wan",
    "code": "wan.up", "subject": "wan1", "actor": "system", "message": "WAN1 is back up.",
    "data": {"down_seconds": 157}, "repeat_count": 1,
    "source": "check-health", "admin_message": "secret detail", "admin_data": {"x": 1},
}


class FakeAgent(BaseHTTPRequestHandler):
    calls = []
    disabled = False

    def log_message(self, *args):
        pass

    def _json(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        url = urlparse(self.path)
        FakeAgent.calls.append({
            "method": self.command, "path": url.path, "query": parse_qs(url.query),
            "actor": self.headers.get("X-Networkat-Actor"),
            "last_event_id": self.headers.get("Last-Event-ID"),
            "body": json.loads(self.rfile.read(length)) if length else None,
        })
        return url.path

    def do_GET(self):
        path = self._record()
        if path.startswith("/logs/system/client") and FakeAgent.disabled:
            return self._json(403, {"ok": False, "code": "logs_disabled", "message": "off", "logs": []})
        if path == "/logs/system/client":
            return self._json(200, {"ok": True, "audience": "client", "entries": [ADMIN_ENTRY],
                                    "page": {"limit": 50, "count": 1, "has_more": False,
                                             "next_before_id": None}, "last_id": 7})
        if path == "/logs/system/client/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            body = (b"retry: 3000\n\n: keepalive\n\n"
                    b"id: 7\nevent: log\ndata: " + json.dumps(ADMIN_ENTRY).encode() + b"\n\n")
            for piece in (body[:10], body[10:40], body[40:]):  # split mid-event on purpose
                self.wfile.write(b"%x\r\n%s\r\n" % (len(piece), piece))
            self.wfile.write(b"0\r\n\r\n")
            return
        if path == "/logs/system/config":
            return self._json(200, {"ok": True, "enabled": True, "categories": {}, "bounds": {},
                                    "always_on": ["audit"]})
        self._json(404, {"detail": "Not Found"})

    def do_PUT(self):
        path = self._record()
        if path == "/logs/system/config":
            if "audit" in FakeAgent.calls[-1]["body"]["categories"]:
                return self._json(400, {"ok": False, "code": "usage", "message": "audit: cannot", "logs": []})
            return self._json(200, {"ok": True, "enabled": True, "categories": {}, "bounds": {},
                                    "always_on": ["audit"]})
        if path == "/services/logs":
            return self._json(200, {"ok": True, "services": []})
        self._json(404, {"detail": "Not Found"})

    def do_DELETE(self):
        self._record()
        self._json(200, {"ok": True, "cleared": ["wan"], "up_to_id": 7})


@pytest.fixture
def peer(monkeypatch):
    FakeAgent.calls = []
    FakeAgent.disabled = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAgent)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(svc, "AGENT_PORT", server.server_address[1])
    yield {"id": "p1", "ip": "127.0.0.1", "connected": True}
    server.shutdown()


def _error(fn, *args):
    with pytest.raises(svc.EventsError) as exc:
        fn(*args)
    return exc.value.status_code, exc.value.code


def test_list_is_client_only(peer):
    out = svc.list_events(peer, {"category": "wan", "limit": 20, "code": "x", "actor": "y", "q": ""})
    entry = out["entries"][0]
    assert entry["message"] == "WAN1 is back up."
    assert not {"source", "admin_message", "admin_data"} & set(entry)
    call = FakeAgent.calls[-1]
    assert call["path"] == "/logs/system/client"
    assert call["query"] == {"category": ["wan"], "limit": ["20"]}  # code/actor/empty q dropped


def test_changes_carry_client_actor(peer):
    svc.update_config(peer, {"categories": {"wan": {"retention_days": 10}}})
    svc.clear_events(peer, "wan")
    svc.set_logs_service(peer, "enabled")
    config, clear, service = FakeAgent.calls
    assert all(c["actor"] == "client" for c in (config, clear, service))
    assert clear["query"] == {"category": ["wan"]}
    assert service["body"] == {"state": "enabled", "source": "customer"}
    svc.get_config(peer)
    assert FakeAgent.calls[-1]["actor"] is None


def test_errors_are_mapped(peer):
    FakeAgent.disabled = True
    assert _error(svc.list_events, peer, {}) == (403, "logs_disabled")
    assert _error(svc.update_config, peer, {"categories": {"audit": {"enabled": False}}}) == (400, "usage")
    assert _error(svc.list_categories, peer) == (501, "unsupported")  # fake agent has no route
    assert _error(svc.list_events, {"ip": "127.0.0.1", "connected": False}, {}) == (503, "offline")


def test_unreachable_agent_is_offline(peer, monkeypatch):
    monkeypatch.setattr(svc, "AGENT_PORT", 1)
    assert _error(svc.get_config, peer) == (503, "offline")
    with pytest.raises(svc.EventsError) as exc:
        asyncio.run(svc.open_stream(peer, {}, None))
    assert exc.value.code == "offline"


def test_stream_passes_events_without_admin_fields(peer):
    async def read():
        events = await svc.open_stream(peer, {"category": "wan", "since": "x"}, "5")
        return b"".join([chunk async for chunk in events])

    body = asyncio.run(read()).decode()
    assert body.startswith("retry: 3000\n\n: keepalive\n\nid: 7\nevent: log\ndata: ")
    data = json.loads(body.split("data: ", 1)[1])
    assert data["id"] == 7 and "admin_message" not in data and "source" not in data
    call = FakeAgent.calls[-1]
    assert call["query"] == {"category": ["wan"]} and call["last_event_id"] == "5"


def test_stream_error_before_any_bytes(peer):
    FakeAgent.disabled = True
    with pytest.raises(svc.EventsError) as exc:
        asyncio.run(svc.open_stream(peer, {}, None))
    assert (exc.value.status_code, exc.value.code) == (403, "logs_disabled")
