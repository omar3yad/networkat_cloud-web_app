"""
Unit tests for the Unified Admin Security & Session Layer (Phase 0).
Tests header-first bearer authentication, cookie fallback, CSRF validation, and role gating.
"""
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from flask import Flask, session as flask_session
from flask_wtf.csrf import generate_csrf

from fastapi_app import dependencies as deps
from fastapi_app.services.admin import session as admin_session

SECRET = "test-admin-secret"
INTERNAL_KEY = "test-internal-api-key-12345"


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", SECRET)
    monkeypatch.setenv("INTERNAL_API_KEY", INTERNAL_KEY)


def _flask_admin_cookie(secret=SECRET, **values):
    """Session cookie + CSRF header exactly as the admin Flask app issues them."""
    app = Flask(__name__)
    app.secret_key = secret
    app.config["SESSION_COOKIE_NAME"] = admin_session.ADMIN_SESSION_COOKIE_NAME
    out = {}

    @app.route("/")
    def index():
        flask_session.update(values)
        out["csrf"] = generate_csrf()
        return ""

    resp = app.test_client().get("/")
    cookie = resp.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
    return cookie, out["csrf"]


ADMIN_LOGGED_IN = {
    "admin_logged_in": True,
    "admin_user_id": "42",
    "admin_username": "superadmin",
    "admin_role": "admin",
    "admin_fullname": "Super Admin User",
}

STAFF_LOGGED_IN = {
    "admin_logged_in": True,
    "admin_user_id": "43",
    "admin_username": "staffuser",
    "admin_role": "staff",
    "admin_fullname": "Staff Member",
}


class _MockRequest:
    def __init__(self, method="GET"):
        self.method = method


def _status(fn, *args, **kwargs):
    try:
        res = fn(*args, **kwargs)
        return 200, res
    except HTTPException as e:
        return e.status_code, e.detail


# ── 1. Bearer Token Authentication (Primary) ─────────────────────────────────

def test_bearer_token_valid():
    req = _MockRequest("GET")
    auth = deps.get_admin_auth(
        request=req,
        authorization=f"Bearer {INTERNAL_KEY}",
        session_cookie=None,
        csrf_header=None,
    )
    assert auth.is_bearer is True
    assert auth.role == "admin"
    assert auth.username == "internal_api"


def test_bearer_token_case_and_spacing():
    req = _MockRequest("POST")
    auth = deps.get_admin_auth(
        request=req,
        authorization=f"bearer   {INTERNAL_KEY}  ",
        session_cookie=None,
        csrf_header=None,
    )
    assert auth.is_bearer is True


def test_bearer_token_invalid():
    req = _MockRequest("GET")
    code, detail = _status(
        deps.get_admin_auth,
        request=req,
        authorization="Bearer wrong-key",
        session_cookie=None,
        csrf_header=None,
    )
    assert code == 401
    assert "Invalid or missing" in detail


# ── 2. Cookie Authentication (Fallback) ───────────────────────────────────────

def test_cookie_admin_session_valid():
    cookie, _ = _flask_admin_cookie(**ADMIN_LOGGED_IN)
    req = _MockRequest("GET")
    auth = deps.get_admin_auth(
        request=req,
        authorization=None,
        session_cookie=cookie,
        csrf_header=None,
    )
    assert auth.is_bearer is False
    assert auth.user_id == "42"
    assert auth.username == "superadmin"
    assert auth.role == "admin"


def test_cookie_not_logged_in_rejected():
    cookie, _ = _flask_admin_cookie(admin_logged_in=False, admin_user_id="42")
    req = _MockRequest("GET")
    code, detail = _status(
        deps.get_admin_auth,
        request=req,
        authorization=None,
        session_cookie=cookie,
        csrf_header=None,
    )
    assert code == 401


def test_cookie_tampered_rejected():
    cookie, _ = _flask_admin_cookie(**ADMIN_LOGGED_IN)
    req = _MockRequest("GET")
    code, detail = _status(
        deps.get_admin_auth,
        request=req,
        authorization=None,
        session_cookie=cookie[:-3] + "xyz",
        csrf_header=None,
    )
    assert code == 401


# ── 3. CSRF Protection for Cookie Requests ────────────────────────────────────

def test_cookie_unsafe_method_requires_csrf():
    cookie, csrf = _flask_admin_cookie(**ADMIN_LOGGED_IN)
    req = _MockRequest("POST")

    # Missing CSRF
    code, detail = _status(
        deps.get_admin_auth,
        request=req,
        authorization=None,
        session_cookie=cookie,
        csrf_header=None,
    )
    assert code == 403
    assert "CSRF" in detail

    # Invalid CSRF
    code, detail = _status(
        deps.get_admin_auth,
        request=req,
        authorization=None,
        session_cookie=cookie,
        csrf_header="invalid-csrf-token",
    )
    assert code == 403

    # Valid CSRF
    code, auth = _status(
        deps.get_admin_auth,
        request=req,
        authorization=None,
        session_cookie=cookie,
        csrf_header=csrf,
    )
    assert code == 200
    assert auth.user_id == "42"


# ── 4. Precedence & Role Gating ───────────────────────────────────────────────

def test_header_precedes_cookie():
    cookie, _ = _flask_admin_cookie(**ADMIN_LOGGED_IN)
    req = _MockRequest("GET")
    auth = deps.get_admin_auth(
        request=req,
        authorization=f"Bearer {INTERNAL_KEY}",
        session_cookie=cookie,
        csrf_header=None,
    )
    # Bearer header takes precedence
    assert auth.is_bearer is True
    assert auth.username == "internal_api"


def test_no_credentials_rejected():
    req = _MockRequest("GET")
    code, _ = _status(
        deps.get_admin_auth,
        request=req,
        authorization=None,
        session_cookie=None,
        csrf_header=None,
    )
    assert code == 401


def test_require_admin_role():
    # Admin role succeeds
    admin_auth = deps.AdminAuthContext(
        user_id="1", username="admin", role="admin", is_bearer=False
    )
    assert deps.require_admin_role(admin_auth) == admin_auth

    # Staff role rejected
    staff_auth = deps.AdminAuthContext(
        user_id="2", username="staff", role="staff", is_bearer=False
    )
    code, detail = _status(deps.require_admin_role, staff_auth)
    assert code == 403
    assert "Administrator privileges" in detail
