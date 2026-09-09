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


def subscription_write_required(f):
    """
    Decorator to protect write operations (POST, PUT, DELETE, PATCH).
    Allows full control if client subscription_status is 'active' or 'grace_period'.
    Blocks modifications if subscription_status is 'limit_control' or 'inactive',
    returning HTTP 403 Forbidden with details.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask import request
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            cid = session.get('client_customer_id') or session.get('client_user_id')
            if cid:
                from models.client import Client
                client = Client.query.get(cid)
                if client and not client.is_subscription_active:
                    status = client.subscription_status
                    msg = (
                        "Your subscription is currently in read-only mode (limit_control). "
                        "Modifying configurations, rules, or peers is prohibited until renewed."
                        if status == "limit_control"
                        else f"Your subscription is inactive ({status}). All network modifications are disabled."
                    )
                    return jsonify({
                        "error": "Subscription Restricted",
                        "message": msg,
                        "subscription_status": status,
                        "read_only": True
                    }), 403
        return f(*args, **kwargs)
    return decorated_function
