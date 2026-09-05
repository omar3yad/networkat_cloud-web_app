from functools import wraps
from flask import session, redirect, url_for, jsonify
from services.netbird_service import NetBirdService


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('client_logged_in'):
            return redirect(url_for('client.login'))
        return f(*args, **kwargs)
    return decorated_function


def no_cache_json(payload, status_code=200):
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp, status_code


def verify_peer_access(customer, peer_id: str) -> bool:
    return NetBirdService.verify_peer_access(customer, peer_id)
