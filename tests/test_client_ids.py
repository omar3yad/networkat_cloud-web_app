"""
Client-portal IDS proxy (fastapi_app/services/client/ids_ips_service.py)
against a fake agent on 127.0.0.1 — real HTTP. Checks what the client must
never see (prevention, failsafe, community_id, action, certificate
watchlists), the client actor on changes, busy retry and the unconfirmed-write
re-read.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from fastapi_app.services.client import ids_ips_service as svc

STATUS = {
    "detection": {"state": "disabled", "locks": ["failsafe", "subscription"], "source": "failsafe",
                  "running": False, "starting": False, "applying": False, "enough_memory": True,
                  "last_error": None, "last_error_at": None, "dropping_packets": False},
    "prevention": {"available": False, "locks": ["subscription", "customer"]},
    "rules": {"updated_at": None, "count": 0, "next_update_at": None},
    "engine": {"inspection_gap_seconds": 30, "memory_limit_mb": 1536},
}
SETTINGS = {
    "settings": {"events": {"retention_days": 30, "community_id": True}, "prevention": {"mode": "off"},
                 "suppression": {"minimum_severity": "low"}},
    "defaults": {"events": {"retention_days": 30, "community_id": True}, "prevention": {"mode": "off"}},
    "customized": ["events.community_id", "prevention.mode", "suppression.minimum_severity"],
    "options": {"events.community_id": {}, "events.retention_days": {"min": 1, "max": 90}, "limits": {}},
    "rule_overrides": [],
}
THREAT = {"id": 9, "time": "2026-10-03T08:14:02.311Z", "severity": "high", "kind": "Malware",
          "signature": "x", "action": "detected", "community_id": "1:abc", "sid": 2030171}
WATCHLISTS = [{"id": "a1", "kind": "names", "name": "Sites"},
              {"id": "b2", "kind": "certificates", "name": "Certs"}]


class FakeAgent(BaseHTTPRequestHandler):
    calls = []
    busy = 0             # answer `busy` this many times
    slow = False         # answer flat 503 (agent timeout) to writes
    settings = None

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
            "body": json.loads(self.rfile.read(length)) if length else None,
        })
        return url.path

    def do_GET(self):
        path = self._record()
        if path == "/ids-ips":
            return self._json(200, STATUS)
        if path == "/ids-ips/settings":
            return self._json(200, FakeAgent.settings)
        if path == "/ids-ips/watchlists":
            return self._json(200, {"items": WATCHLISTS})
        if path == "/logs/ids-ips/events":
            return self._json(200, {"audience": "client", "entries": [THREAT],
                                    "page": {"limit": 50, "count": 1, "has_more": False}, "last_id": 9})
        if path == "/logs/ids-ips/events/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            body = b"retry: 3000\n\nid: 9:1\nevent: threat\ndata: " + json.dumps(THREAT).encode() + b"\n\n"
            self.wfile.write(b"%x\r\n%s\r\n0\r\n\r\n" % (len(body), body))
            return
        self._json(404, {"detail": "Not Found"})

    def _write(self, path):
        if FakeAgent.busy:
            FakeAgent.busy -= 1
            return self._json(409, {"ok": False, "code": "busy", "message": "busy", "ids_ips": []})
        if FakeAgent.slow:
            if path == "/ids-ips/settings":
                FakeAgent.settings["settings"]["events"]["retention_days"] = 14
            return self._json(503, {"detail": "timed out"})
        if path == "/ids-ips/settings":
            return self._json(200, {"changed": ["events.retention_days", "events.community_id"],
                                    "applied": "eventd", "code": "ok", "message": "Saved and applied."})
        if path == "/ids-ips/detection":
            return self._json(200, dict(STATUS, applied="starting", code="ok", message="starting"))
        if path.startswith("/services/"):
            return self._json(200, {"ok": True, "services": []})
        if path.endswith("/batch"):
            body = FakeAgent.calls[-1]["body"]
            return self._json(200, {"removed": body["remove"], "updated": body["update"], "added": body["add"],
                                    "applied": "restart", "code": "ok", "message": "m"})
        if path.startswith("/ids-ips/watchlists"):
            return self._json(201, {"item": {"id": "c3"}, "applied": "dataset", "code": "ok", "message": "m"})
        if path == "/ids-ips/suppressions/ff":
            return self._json(404, {"detail": "No such muted threat."})
        return self._json(200, {"code": "ok", "message": "m", "applied": "reload"})

    def do_PUT(self):
        self._write(self._record())

    def do_POST(self):
        self._write(self._record())

    def do_DELETE(self):
        self._write(self._record())


@pytest.fixture
def peer(monkeypatch):
    FakeAgent.calls = []
    FakeAgent.busy = 0
    FakeAgent.slow = False
    FakeAgent.settings = json.loads(json.dumps(SETTINGS))
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAgent)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(svc, "AGENT_PORT", server.server_address[1])
    monkeypatch.setattr(svc, "BUSY_WAIT", 0)
    yield {"id": "p1", "ip": "127.0.0.1", "connected": True}
    server.shutdown()


def _error(fn, *args):
    with pytest.raises(svc.IdsError) as exc:
        fn(*args)
    return exc.value.status_code, exc.value.code


def _no_hidden(obj):
    text = json.dumps(obj)
    for word in ("prevention", "failsafe", "community_id", '"action"', "certificates", "message"):
        assert word not in text, word


def test_status_hides_prevention_and_failsafe(peer):
    out = svc.get_status(peer)
    _no_hidden(out)
    assert out["detection"]["locks"] == ["subscription"]
    assert out["detection"]["source"] == "subscription"
    assert out["detection"]["state"] == "disabled"


def test_failsafe_alone_reads_unavailable(peer):
    det = {"state": "disabled", "locks": ["failsafe"], "source": "failsafe"}
    out = svc.client_status({"detection": det})
    assert out["detection"] == {"state": "unavailable", "locks": [], "source": None}


def test_settings_hide_prevention_and_community_id(peer):
    out = svc.get_settings(peer)
    _no_hidden(out)
    assert out["customized"] == ["suppression.minimum_severity"]
    assert "events.retention_days" in out["options"]


def test_settings_refuse_hidden_fields(peer):
    assert _error(svc.update_settings, peer, {"prevention": {"mode": "ids"}}) == (400, "usage")
    assert _error(svc.update_settings, peer, {"events": {"community_id": False}}) == (400, "usage")
    assert _error(svc.reset_settings, peer, "prevention") == (400, "usage")
    assert FakeAgent.calls == []


def test_settings_change_carries_client_actor_and_no_message(peer):
    out = svc.update_settings(peer, {"events": {"retention_days": 14}})
    assert out == {"code": "ok", "applied": "eventd", "changed": ["events.retention_days"]}
    assert FakeAgent.calls[-1]["actor"] == "client"
    svc.get_settings(peer)
    assert FakeAgent.calls[-1]["actor"] is None


def test_threats_drop_action_and_community_id(peer):
    out = svc.list_threats(peer, {"severity": "high", "limit": 20, "q": ""})
    _no_hidden(out)
    assert out["entries"][0]["sid"] == 2030171
    assert FakeAgent.calls[-1]["query"] == {"severity": ["high"], "limit": ["20"], "audience": ["client"]}


def test_stream_drops_hidden_fields(peer):
    async def read():
        entries = await svc.open_stream(peer, {"severity": "high", "sid": 5}, "9:1")
        return b"".join([chunk async for chunk in entries])

    body = asyncio.run(read()).decode()
    data = json.loads(body.split("data: ", 1)[1])
    assert data["id"] == 9 and "action" not in data and "community_id" not in data
    assert FakeAgent.calls[-1]["query"] == {"severity": ["high"], "audience": ["client"]}


def test_watchlists_client_kinds_only(peer):
    assert [i["id"] for i in svc.list_items(peer, "watchlists")["items"]] == ["a1"]
    assert _error(svc.add_item, peer, "watchlists", {"kind": "certificates", "fingerprints": []}) == (400, "usage")
    assert _error(svc.remove_item, peer, "watchlists", "b2") == (404, "not_found")
    out = svc.add_item(peer, "watchlists", {"kind": "names", "alias_id": "x", "name": "n"})
    assert out["item"] == {"id": "c3"} and "message" not in out


def test_enable_removes_both_locks(peer):
    out = svc.set_enabled(peer, True, "cust")
    services, detection = FakeAgent.calls
    assert services["path"] == "/services/intrusion_detection"
    assert services["body"] == {"state": "enabled", "source": "subscription"}
    assert detection["path"] == "/ids-ips/detection" and detection["body"] == {"enabled": True}
    assert services["actor"] == detection["actor"] == "client"
    assert out["applied"] == "starting"
    _no_hidden(out)


def test_disable_leaves_subscription_alone(peer):
    svc.set_enabled(peer, False, "cust")
    assert [c["path"] for c in FakeAgent.calls] == ["/ids-ips/detection"]


def test_busy_is_retried(peer):
    FakeAgent.busy = 1
    assert svc.update_settings(peer, {"events": {"retention_days": 14}})["code"] == "ok"
    FakeAgent.busy = 5
    assert _error(svc.update_settings, peer, {"events": {"retention_days": 14}}) == (409, "busy")


def test_timeout_reread_confirms_saved_change(peer):
    FakeAgent.slow = True
    out = svc.update_settings(peer, {"events": {"retention_days": 14}})
    assert out["code"] == "ok"
    assert _error(svc.update_settings, peer, {"events": {"retention_days": 20}}) == (504, "unconfirmed")


def test_errors_are_mapped(peer):
    assert _error(svc.remove_item, peer, "muted", "ff") == (404, "not_found")
    assert _error(svc.list_items, peer, "excluded") == (501, "unsupported")   # no such route
    assert _error(svc.get_status, {"ip": "127.0.0.1", "connected": False}) == (503, "offline")


def test_unreachable_agent_is_offline(peer, monkeypatch):
    monkeypatch.setattr(svc, "AGENT_PORT", 1)
    assert _error(svc.get_status, peer) == (503, "offline")


def test_excluded_address_becomes_host_or_network_and_lists_go_as_one(peer):
    svc.add_item(peer, "excluded", [{"target": "address", "value": "192.168.1.5"},
                                    {"target": "address", "value": "192.168.2.0/24"},
                                    {"target": "alias", "alias_id": "a1"}])
    call = FakeAgent.calls[-1]
    assert call["path"] == "/ids-ips/exclusions" and call["actor"] == "client"
    assert [i["target"] for i in call["body"]] == ["host", "network", "alias"]
    assert len(FakeAgent.calls) == 1


def test_batch_maps_and_answers_the_three_lists(peer):
    out = svc.batch_items(peer, "excluded", {"add": [{"target": "address", "value": "10.0.0.0/8"}],
                                             "update": [{"id": "ab", "target": "address", "value": "10.0.0.9"}],
                                             "remove": ["cd"]})
    call = FakeAgent.calls[-1]
    assert call["method"] == "POST" and call["path"] == "/ids-ips/exclusions/batch" and call["actor"] == "client"
    assert call["body"]["add"][0]["target"] == "network" and call["body"]["update"][0]["target"] == "host"
    assert out["removed"] == ["cd"] and out["applied"] == "restart" and "message" not in out


def test_batch_refuses_what_the_client_may_not_do(peer):
    assert _error(svc.batch_items, peer, "muted", {"update": [{"id": "ab"}]}) == (400, "usage")
    assert _error(svc.batch_items, peer, "watchlists", {"add": [{"kind": "certificates"}]}) == (400, "usage")
    assert _error(svc.batch_items, peer, "watchlists", {"remove": ["b2"]}) == (404, "not_found")
    assert not [c for c in FakeAgent.calls if c["method"] != "GET"]
