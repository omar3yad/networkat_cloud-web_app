"""
FastAPI reads the client Flask session cookie (fastapi_app/services/client/session.py).
Cookies and CSRF tokens here are minted by real Flask / Flask-WTF, so a change
on either side that breaks compatibility fails these tests.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from flask import Flask, session as flask_session
from flask_wtf.csrf import generate_csrf

from fastapi_app import dependencies as deps
from fastapi_app.services.client import session as client_session

SECRET = "test-secret"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", SECRET)


def _flask_cookie(secret=SECRET, **values):
    """Session cookie + CSRF header exactly as the client Flask app would issue them."""
    app = Flask(__name__)
    app.secret_key = secret
    app.config["SESSION_COOKIE_NAME"] = client_session.SESSION_COOKIE_NAME
    out = {}

    @app.route("/")
    def index():
        flask_session.update(values)
        out["csrf"] = generate_csrf()
        return ""

    resp = app.test_client().get("/")
    cookie = resp.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
    return cookie, out["csrf"]


LOGGED_IN = {"client_logged_in": True, "client_customer_id": "cust-1"}


def test_logged_in_session_is_read():
    cookie, _ = _flask_cookie(**LOGGED_IN)
    s = client_session.load_client_session(cookie)
    assert s is not None and s.customer_id == "cust-1"


@pytest.mark.parametrize("values", [{}, {"client_customer_id": "cust-1"}, {"client_logged_in": True}])
def test_not_logged_in_is_rejected(values):
    cookie, _ = _flask_cookie(**values)
    assert client_session.load_client_session(cookie) is None


def test_other_secret_is_rejected():
    cookie, _ = _flask_cookie(secret="other", **LOGGED_IN)
    assert client_session.load_client_session(cookie) is None


def test_tampered_or_missing_cookie_is_rejected():
    cookie, _ = _flask_cookie(**LOGGED_IN)
    assert client_session.load_client_session(cookie[:-2] + "xx") is None
    assert client_session.load_client_session(None) is None


def test_csrf_token():
    cookie, csrf = _flask_cookie(**LOGGED_IN)
    s = client_session.load_client_session(cookie)
    assert client_session.csrf_token_valid(s, csrf)
    assert not client_session.csrf_token_valid(s, None)
    assert not client_session.csrf_token_valid(s, csrf[:-2] + "xx")
    other_cookie, other_csrf = _flask_cookie(**LOGGED_IN)
    assert not client_session.csrf_token_valid(s, other_csrf)


# ── Dependencies ─────────────────────────────────────────────────────────────

class _Req:
    def __init__(self, method):
        self.method = method


def _owned(customer_id, peer_id):
    return {"id": peer_id, "ip": "100.64.0.9", "connected": True} if peer_id == "mine" else None


def _status(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except HTTPException as e:
        return e.status_code, e.detail
    return 200, None


@patch.object(deps.peer_access, "get_owned_peer", side_effect=_owned)
def test_session_and_ownership(_):
    assert _status(deps.get_client_session, _Req("GET"), None, None)[0] == 401
    cookie, _csrf = _flask_cookie(**LOGGED_IN)
    s = deps.get_client_session(_Req("GET"), cookie, None)
    assert deps.get_client_peer("mine", s)["id"] == "mine"
    assert _status(deps.get_client_peer, "theirs", s) == (404, "Device not found")


def test_writes_need_csrf_and_active_subscription():
    cookie, csrf = _flask_cookie(**LOGGED_IN)
    assert _status(deps.get_client_session, _Req("PUT"), cookie, None) == (403, "Invalid token")
    s = deps.get_client_session(_Req("PUT"), cookie, csrf)
    with patch.object(deps.peer_access, "can_write", return_value=True):
        assert deps.require_client_write(s) is s
    with patch.object(deps.peer_access, "can_write", return_value=False):
        assert _status(deps.require_client_write, s) == (403, "Read-only subscription")
