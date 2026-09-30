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


def feature_required(feature_key: str):
    """
    Decorator to protect routes based on system settings (feature flags).
    If feature is disabled, returns HTTP 403 for API requests or redirects with a flash message for HTML pages.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from services.settings_service import settings as app_settings
            if not app_settings.get_bool(feature_key, default=True):
                from flask import request, flash, redirect, url_for, jsonify
                if request.path.startswith('/api/') or request.is_json:
                    return jsonify({
                        "error": "Feature Disabled",
                        "message": "This feature is currently disabled."
                    }), 403
                flash("This feature is currently disabled.", "warning")
                peer_id = kwargs.get('peer_id')
                if peer_id:
                    return redirect(url_for('client.peer_details', peer_id=peer_id))
                return redirect(url_for('client.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
