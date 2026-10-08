import os
import re
import time
import secrets
import requests
from datetime import datetime
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    flash, jsonify, current_app, Response, stream_with_context
)

from extensions import db, limiter
from models import Client
from models.system_user import SystemUser
from models.subscription_plan import SubscriptionPlan
from services.auth_service import AuthService
from services.customer_service import CustomerService
from services.subscription_service import SubscriptionService
from services.netbird_service import (
    get_cached_customer_peer_ids as _get_customer_group_peer_ids,
    get_cached_all_netbird_peers,
    get_cached_all_netbird_routes,
    get_cached_peer_vpn_only,
    check_single_peer_handshake,
    get_api_base_url,
    get_api_headers,
)
from repositories.user_repository import UserRepository
from utils.two_factor import (
    generate_totp_secret,
    get_totp_uri,
    generate_qr_base64,
    verify_totp_code,
    generate_recovery_codes,
    hash_recovery_codes,
    verify_and_consume_recovery_code
)
from utils.email import send_2fa_email_otp
from utils.password import verify_password
from utils.cache_manager import (
    get_name_override,
    get_active_route_overrides,
    firewall_rules_cache,
    firewall_cache_lock,
)

_admin_view_executor = ThreadPoolExecutor(max_workers=20)

admin_bp = Blueprint('admin', __name__, template_folder='../templates')
auth_service = AuthService()
customer_service = CustomerService()
subscription_service = SubscriptionService()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin.login'))
        if session.get('admin_role') != 'admin':
            if request.is_json or request.path.startswith('/api/') or request.method in ['POST', 'DELETE', 'PUT']:
                return jsonify({'success': False, 'error': 'Permission denied. Administrator privileges required.'}), 403
            flash('Permission denied. Administrator privileges required.', 'error')
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def _get_api_base_url():
    return current_app.config.get('NETBIRD_API_BASE_URL', 'https://api.networkat.cloud')

def _get_api_headers(extra_headers=None):
    token = os.getenv("INTERNAL_API_KEY", "")
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {token}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ClientApp/1.0'
    }
    if extra_headers:
        headers.update(extra_headers)
    return headers
    

@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def login():

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        success, message = auth_service.authenticate(username, password)
        if success:
            if message == "2fa_required":
                return redirect(url_for('admin.verify_2fa'))
            return redirect(url_for('admin.dashboard'))
        flash(message, 'error')
    return render_template('login.html')


@admin_bp.route('/verify-2fa', methods=['GET', 'POST'])
def verify_2fa():
    pending = session.get('pending_2fa')
    if not pending or pending.get('type') != 'admin':
        flash("Sign in session expired. Please sign in again.", "error")
        return redirect(url_for('admin.login'))

    # 5-minute expiration
    if time.time() - pending.get('created_at', 0) > 300:
        session.pop('pending_2fa', None)
        session.pop('pending_2fa_email_otp', None)
        flash("Verification session expired. Please sign in again.", "error")
        return redirect(url_for('admin.login'))

    user = UserRepository.get_by_id(pending.get('user_id'))
    if not user:
        session.pop('pending_2fa', None)
        flash("User not found.", "error")
        return redirect(url_for('admin.login'))

    if request.method == 'POST':
        if pending.get('attempts', 0) >= 5:
            session.pop('pending_2fa', None)
            session.pop('pending_2fa_email_otp', None)
            flash("Too many failed attempts. Please sign in again.", "error")
            return redirect(url_for('admin.login'))

        auth_type = request.form.get('auth_type', 'totp')
        code = request.form.get('code', '').strip()

        verified = False

        if auth_type == 'totp':
            verified = verify_totp_code(user.totp_secret, code)
        elif auth_type == 'email':
            email_otp_data = session.get('pending_2fa_email_otp')
            if email_otp_data and time.time() <= email_otp_data.get('expires_at', 0):
                if secrets.compare_digest(code, str(email_otp_data.get('code', ''))):
                    verified = True
        elif auth_type == 'recovery':
            ok, updated_codes = verify_and_consume_recovery_code(code, user.recovery_codes)
            if ok:
                user.recovery_codes = updated_codes
                db.session.commit()
                verified = True

        if verified:
            auth_service.complete_2fa_login(user)
            user.last_login = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('admin.dashboard'))
        else:
            pending['attempts'] = pending.get('attempts', 0) + 1
            session['pending_2fa'] = pending
            flash("Invalid verification code.", "error")

    masked_email = ""
    if user.email and "@" in user.email:
        parts = user.email.split("@")
        name = parts[0]
        domain = parts[1]
        masked_name = name[:2] + "***" if len(name) > 2 else name + "***"
        masked_email = f"{masked_name}@{domain}"

    return render_template(
        'verify_2fa.html',
        username=user.username,
        masked_email=masked_email,
        method=pending.get('method', 'totp')
    )


@admin_bp.route('/send-2fa-email-otp', methods=['POST'])
def send_2fa_email_otp_route():
    pending = session.get('pending_2fa')
    if not pending or pending.get('type') != 'admin':
        return jsonify({'success': False, 'message': 'Session expired'}), 401

    user = UserRepository.get_by_id(pending.get('user_id'))
    if not user or not user.email:
        return jsonify({'success': False, 'message': 'Email address not found'}), 400

    code = str(secrets.randbelow(900000) + 100000)
    session['pending_2fa_email_otp'] = {
        'code': code,
        'expires_at': time.time() + 300
    }

    ok, err = send_2fa_email_otp(user.email, code, user.full_name)
    if not ok:
        current_app.logger.error(f"Failed to send 2FA email OTP: {err}")
        return jsonify({'success': False, 'message': 'Failed to send email'}), 500

    return jsonify({'success': True, 'message': 'Verification code sent'})


@admin_bp.route('/logout')
def logout():
    auth_service.logout()
    return redirect(url_for('admin.login'))


@admin_bp.route('/')
@login_required
def dashboard():
    data = customer_service.get_dashboard_data(online_window=300)
    return render_template('dashboard.html', **data)


# ── Subscription Plans Management (FastAPI Proxy) ──────────────────────────

@admin_bp.route('/plans')
@login_required
@admin_required
def plans():
    from models import Client
    from models.system_setting import SystemSetting
    from sqlalchemy import func
    all_plans = SubscriptionPlan.query.order_by(SubscriptionPlan.allowed_peers_count.asc()).all()
    # Build customer count per plan
    counts_q = db.session.query(Client.plan_id, func.count(Client.user_id)).group_by(Client.plan_id).all()
    customer_counts = {str(plan_id): cnt for plan_id, cnt in counts_q if plan_id is not None}
    total_customers = Client.query.count()

    trial_days = 7
    try:
        st = SystemSetting.query.filter_by(key='trial.duration_days').first()
        if st and st.value:
            trial_days = int(st.value)
    except Exception:
        trial_days = 7

    return render_template(
        'plans.html',
        plans=all_plans,
        customer_counts=customer_counts,
        total_customers=total_customers,
        trial_days=trial_days
    )


@admin_bp.route('/api/plans/trial-duration', methods=['GET'])
@login_required
def api_plans_get_trial_duration():
    try:
        url = f"{_get_api_base_url()}/api/v2/plans/trial-duration"
        response = requests.get(url, headers=_get_api_headers(), timeout=5)
        return (response.text, response.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        current_app.logger.error(f'Error proxying get trial duration: {e}')
        return jsonify({'success': False, 'error': 'Failed to reach API server'}), 502


@admin_bp.route('/api/plans/trial-duration', methods=['PUT'])
@login_required
@admin_required
def api_plans_set_trial_duration():
    try:
        url = f"{_get_api_base_url()}/api/v2/plans/trial-duration"
        response = requests.put(url, json=request.get_json() or {}, headers=_get_api_headers(), timeout=5)
        if response.status_code == 422:
            detail = response.json().get('detail')
            msg = detail[0].get('msg') if isinstance(detail, list) and detail else str(detail)
            return jsonify({'success': False, 'error': msg or 'Validation error'}), 400
        if response.status_code >= 400:
            err = response.json().get('detail', 'Failed to update trial duration')
            return jsonify({'success': False, 'error': err}), response.status_code
        return (response.text, response.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        current_app.logger.error(f'Error proxying set trial duration: {e}')
        return jsonify({'success': False, 'error': 'Failed to update trial duration'}), 502


@admin_bp.route('/api/plans', methods=['GET'])
@login_required
def api_plans_list():
    try:
        url = f"{_get_api_base_url()}/api/v2/plans"
        response = requests.get(url, headers=_get_api_headers(), timeout=5)
        return (response.text, response.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        current_app.logger.error(f'Error proxying plans list: {e}')
        return jsonify({'success': False, 'error': 'Failed to reach API server'}), 502


@admin_bp.route('/api/plans', methods=['POST'])
@login_required
@admin_required
def api_plans_create():
    try:
        url = f"{_get_api_base_url()}/api/v2/plans"
        response = requests.post(url, json=request.get_json() or {}, headers=_get_api_headers(), timeout=5)
        if response.status_code == 422:
            detail = response.json().get('detail')
            msg = detail[0].get('msg') if isinstance(detail, list) and detail else str(detail)
            return jsonify({'success': False, 'error': msg or 'Validation error'}), 400
        if response.status_code >= 400:
            err = response.json().get('detail', 'Failed to create plan')
            return jsonify({'success': False, 'error': err}), response.status_code
        return (response.text, response.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        current_app.logger.error(f'Error proxying plan create: {e}')
        return jsonify({'success': False, 'error': 'Failed to create plan'}), 502


@admin_bp.route('/api/plans/<int:plan_id>', methods=['PUT'])
@login_required
@admin_required
def api_plans_update(plan_id):
    try:
        url = f"{_get_api_base_url()}/api/v2/plans/{plan_id}"
        response = requests.put(url, json=request.get_json() or {}, headers=_get_api_headers(), timeout=5)
        if response.status_code == 422:
            detail = response.json().get('detail')
            msg = detail[0].get('msg') if isinstance(detail, list) and detail else str(detail)
            return jsonify({'success': False, 'error': msg or 'Validation error'}), 400
        if response.status_code >= 400:
            err = response.json().get('detail', 'Failed to update plan')
            return jsonify({'success': False, 'error': err}), response.status_code
        return (response.text, response.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        current_app.logger.error(f'Error proxying plan update: {e}')
        return jsonify({'success': False, 'error': 'Failed to update plan'}), 502


@admin_bp.route('/api/plans/<int:plan_id>', methods=['DELETE'])
@login_required
@admin_required
def api_plans_delete(plan_id):
    try:
        url = f"{_get_api_base_url()}/api/v2/plans/{plan_id}"
        response = requests.delete(url, headers=_get_api_headers(), timeout=5)
        if response.status_code >= 400:
            err = response.json().get('detail', 'Failed to delete plan')
            return jsonify({'success': False, 'error': err}), response.status_code
        return (response.text, response.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        current_app.logger.error(f'Error proxying plan delete: {e}')
        return jsonify({'success': False, 'error': 'Failed to delete plan'}), 502


@admin_bp.route('/api/plans/<int:plan_id>/toggle', methods=['POST'])
@login_required
@admin_required
def api_plans_toggle(plan_id):
    try:
        url = f"{_get_api_base_url()}/api/v2/plans/{plan_id}/toggle"
        response = requests.post(url, headers=_get_api_headers(), timeout=5)
        if response.status_code >= 400:
            err = response.json().get('detail', 'Failed to toggle plan')
            return jsonify({'success': False, 'error': err}), response.status_code
        return (response.text, response.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        current_app.logger.error(f'Error proxying plan toggle: {e}')
        return jsonify({'success': False, 'error': 'Failed to toggle plan'}), 502


@admin_bp.route('/customers')
@login_required
def customers():
    customers_data = customer_service.get_customers_list(online_window=300)
    return render_template('customers.html', customers=customers_data)


@admin_bp.route('/customers/<uuid:customer_id>')
@login_required
def customer_details(customer_id):
    data, err = customer_service.get_customer_details(customer_id)
    if err:
        return jsonify({'success': False, 'error': err}), 404

    plans = SubscriptionPlan.query.order_by(SubscriptionPlan.allowed_peers_count.asc()).all()
    customer = data.get('customer')
    sub_info = subscription_service.get_subscription_info(customer) if customer else {}

    return render_template('customer_details.html', **data, plans=plans, subscription_info=sub_info, customer_id=customer_id)


@admin_bp.route('/customers/create', methods=['POST'])
@login_required
def create_customer():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password')
    client_name = data.get('client_name') or data.get('name')

    if not username or not password or not client_name:
        return jsonify({'success': False, 'error': 'Required fields (username, password, client_name) are missing'}), 400

    if not re.match(r'^[a-zA-Z0-9_-]{3,32}$', username):
        return jsonify({'success': False, 'error': 'Username must be 3-32 characters and contain only letters, numbers, hyphens, and underscores.'}), 400

    try:
        existing_user = customer_service.client_repo.get_by_username(username)
        if existing_user:
            return jsonify({'success': False, 'error': f'Username "{username}" is already taken.'}), 400
    except Exception as e:
        current_app.logger.error(f"Error checking existing username: {e}")

    success, res = customer_service.create_customer(data)
    if success:
        return jsonify({'success': True, **res})

    error_msg = str(res)
    if "duplicate key value violates unique constraint" in error_msg:
        error_msg = 'A record with this unique value (username or email) already exists.'
    return jsonify({'success': False, 'error': error_msg}), 400


@admin_bp.route('/customers/<uuid:customer_id>/token', methods=['POST'])
@login_required
def generate_token(customer_id):
    success, res = customer_service.generate_token(customer_id)
    if success:
        return jsonify({'success': True, 'token': res})
    return jsonify({'success': False, 'error': res}), 400


@admin_bp.route('/customers/<uuid:customer_id>/delete', methods=['POST'])
@admin_required
def delete_customer(customer_id):
    success, err = customer_service.delete_customer(customer_id)
    if success:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': err}), 400


@admin_bp.route('/customers/<uuid:customer_id>/toggle_token/<token>', methods=['POST'])
@login_required
def toggle_token(customer_id, token):
    success, res = customer_service.toggle_token(customer_id, token)
    if success:
        return jsonify({'success': True, 'is_active': res})
    return jsonify({'success': False, 'error': res}), 400


@admin_bp.route('/api/customers/<uuid:customer_id>/users', methods=['GET'])
@login_required
def get_customer_users(customer_id):
    users = customer_service.get_portal_users(customer_id)
    return jsonify(users)


@admin_bp.route('/api/customers/<uuid:customer_id>/users', methods=['POST'])
@login_required
def create_customer_user(customer_id):
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    success, res = customer_service.create_portal_user(customer_id, username, password)
    if success:
        return jsonify({'success': True, 'user': res})
    return jsonify({'success': False, 'error': res}), 400


@admin_bp.route('/api/users/<uuid:user_id>/toggle', methods=['POST'])
@login_required
def toggle_user_status(user_id):
    success, res = customer_service.toggle_portal_user(user_id)
    if success:
        return jsonify({'success': True, 'is_active': res})
    return jsonify({'success': False, 'error': res}), 400


@admin_bp.route('/api/users/<uuid:user_id>/reset-password', methods=['POST'])
@login_required
def reset_user_password(user_id):
    data = request.get_json() or {}
    password = data.get('password')
    success, err = customer_service.reset_portal_user_password(user_id, password)
    if success:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': err}), 400


@admin_bp.route('/api/users/<uuid:user_id>/delete', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    success, err = customer_service.delete_portal_user(user_id)
    if success:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': err}), 400


@admin_bp.route('/api/peers', methods=['GET'])
@login_required
def proxy_peers():
    peer_name = request.args.get('name', '')
    customer_id = request.args.get('customer_id')
    allowed_peer_ids = None

    if customer_id:
        customer = Client.query.get(customer_id)
        if customer:
            allowed_peer_ids = _get_customer_group_peer_ids(customer)

    try:
        url = f"{_get_api_base_url()}/api/v2/netbird/peers"
        params = {'name': peer_name} if peer_name else {}
        headers = _get_api_headers()
        
        response = requests.get(url, params=params, headers=headers, timeout=5)

        if response.status_code != 200:
            return jsonify(response.json()), response.status_code

        peers_data = response.json()
        if isinstance(peers_data, dict):
            peers_data = [peers_data]

        sanitized_peers = [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "connected": p.get("connected", False),
                "last_seen": p.get("last_seen"),
                "ip": p.get("ip"),
                "os": p.get("os"),
                "version": p.get("version")
            }
            for p in peers_data
            if allowed_peer_ids is None or p.get("id") in allowed_peer_ids
        ]
        return jsonify(sanitized_peers), 200
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Failed to reach external NetBird API", "details": str(e)}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/api/peers/<peer_id>/handshake', methods=['GET'])
@login_required
def proxy_handshake(peer_id):
    try:
        url = f"{_get_api_base_url()}/api/v1/peers/{peer_id}/handshake"
        
        # 🔑 إرسال الـ Bearer Token هنا أيضاً
        headers = _get_api_headers()
        
        response = requests.get(url, headers=headers, timeout=5)
        return (response.text, response.status_code, {'Content-Type': 'application/json'})
    except requests.exceptions.RequestException as e:
        return jsonify({"peer_id": peer_id, "is_reachable": False, "error": "External API unreachable", "details": str(e)}), 502
    except Exception as e:
        return jsonify({"peer_id": peer_id, "is_reachable": False, "error": str(e)}), 500

@admin_bp.route('/api/peers/<peer_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_peer(peer_id):
    try:
        from fastapi_app.services.admin.peers_service import AdminPeersService
        res = AdminPeersService.delete_peer(db=db.session, peer_id=peer_id)
        return jsonify(res), 200
    except Exception as e:
        current_app.logger.error(f"Error deleting peer {peer_id}: {e}")
        status_code = getattr(e, 'status_code', 500)
        detail = getattr(e, 'detail', 'Failed to delete peer')
        return jsonify({'success': False, 'error': detail}), status_code



# ----------------------------------------------------------------------
# Subscription Management APIs
# ----------------------------------------------------------------------

@admin_bp.route('/api/customers/<uuid:customer_id>/subscription', methods=['GET'])
@login_required
def get_customer_subscription(customer_id):
    customer = Client.query.get(customer_id)
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'}), 404
    info = subscription_service.get_subscription_info(customer)
    return jsonify({'success': True, 'subscription': info})


@admin_bp.route('/api/customers/<uuid:customer_id>/subscription/update', methods=['POST'])
@admin_bp.route('/api/customers/<uuid:customer_id>/subscription', methods=['POST', 'PUT'])
@login_required
def update_customer_subscription(customer_id):
    from fastapi_app.services.admin.customers_service import AdminCustomersService
    data = request.get_json() or {}
    cid = str(customer_id)
    try:
        plan_id = data.get('plan_id')
        if plan_id:
            AdminCustomersService.update_customer_plan(
                db=db.session,
                customer_id=cid,
                plan_id=int(plan_id),
                billing_cycle=data.get('billing_cycle'),
                allowed_peers_count=data.get('allowed_peers_count'),
                renewal_date=data.get('renewal_date'),
                is_trial=data.get('is_trial'),
            )
        status_val = data.get('status')
        if status_val:
            AdminCustomersService.update_customer_status(
                db=db.session,
                customer_id=cid,
                new_status=status_val
            )
        detail = AdminCustomersService.get_customer_detail(db=db.session, customer_id=cid)
        return jsonify({
            'success': True,
            'message': 'Subscription updated successfully',
            'subscription': detail.get('subscription', {})
        })
    except Exception as e:
        current_app.logger.error(f"Error updating subscription for {cid}: {e}")
        status_code = getattr(e, 'status_code', 500)
        detail = getattr(e, 'detail', 'Failed to update subscription')
        return jsonify({'success': False, 'error': detail}), status_code


@admin_bp.route('/api/customers/<uuid:customer_id>/subscription/activate', methods=['POST'])
@login_required
def activate_customer_subscription(customer_id):
    from fastapi_app.services.admin.customers_service import AdminCustomersService
    try:
        res = AdminCustomersService.update_customer_status(db=db.session, customer_id=str(customer_id), new_status='active')
        return jsonify(res), 200
    except Exception as e:
        status_code = getattr(e, 'status_code', 500)
        detail = getattr(e, 'detail', 'Failed to activate customer')
        return jsonify({'success': False, 'error': detail}), status_code


@admin_bp.route('/api/customers/<uuid:customer_id>/subscription/suspend', methods=['POST'])
@login_required
def suspend_customer_subscription(customer_id):
    from fastapi_app.services.admin.customers_service import AdminCustomersService
    try:
        res = AdminCustomersService.update_customer_status(db=db.session, customer_id=str(customer_id), new_status='inactive')
        return jsonify(res), 200
    except Exception as e:
        status_code = getattr(e, 'status_code', 500)
        detail = getattr(e, 'detail', 'Failed to suspend customer')
        return jsonify({'success': False, 'error': detail}), status_code


@admin_bp.route('/api/customers/<uuid:customer_id>/subscription/send-reminder', methods=['POST'])
@login_required
def send_customer_renewal_reminder(customer_id):
    customer = Client.query.get(customer_id)
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'}), 404

    from utils.email import send_renewal_reminder_email
    to_email = customer.client_email
    if not to_email:
        return jsonify({'success': False, 'error': 'Customer does not have an email address configured'}), 400

    plan_name = customer.plan.name.capitalize() if customer.plan else (customer.subscription or 'Starter').capitalize()
    renewal_str = customer.renewal_date.strftime('%Y-%m-%d') if customer.renewal_date else 'Soon'

    sent = send_renewal_reminder_email(
        to_email=to_email,
        client_name=customer.client_name,
        renewal_date=renewal_str,
        plan_name=plan_name
    )

    if sent:
        customer.renewal_notified_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'message': f'Renewal reminder sent to {to_email}'})
    else:
        return jsonify({'success': False, 'error': 'Failed to send email. Check SMTP configuration.'}), 500


# ----------------------------------------------------------------------
# Staff / Employees Management Routes & APIs
# ----------------------------------------------------------------------
# System Settings (Feature Flags & Limits)
# ----------------------------------------------------------------------
# System Settings & Feature Controls
# ----------------------------------------------------------------------

@admin_bp.route('/settings')
@admin_bp.route('/settings/<string:category>')
@admin_required
def system_settings(category=None):
    from services.settings_service import settings as app_settings
    by_category = app_settings.all_by_category()

    # Filter out hidden or internal settings (like feature.system_logs and unused categories)
    filtered = {}
    for cat, items in by_category.items():
        if cat.lower() == 'subscription':
            continue
        clean_items = [s for s in items if s.get('key') != 'feature.system_logs']
        if clean_items:
            filtered[cat] = clean_items

    # Match initial active category
    active_cat = None
    if category:
        for cat in filtered.keys():
            if cat.lower() == category.lower():
                active_cat = cat
                break
    if not active_cat:
        active_cat = list(filtered.keys())[0] if filtered else 'Features'

    return render_template(
        'settings.html',
        categories=filtered,
        active_category=active_cat
    )


@admin_bp.route('/api/settings', methods=['PATCH', 'POST'])
@admin_required
def update_settings():
    data = request.get_json() or {}
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    # Proxy to FastAPI if available, else fallback
    try:
        url = f"{_get_api_base_url()}/api/v2/settings"
        response = requests.patch(url, json=data, headers=_get_api_headers(), timeout=5)
        if response.status_code == 200:
            return (response.text, response.status_code, {'Content-Type': 'application/json'})
        # A rejected value (e.g. "Invalid color") is final: show it, don't save it through the fallback.
        if response.status_code in (400, 422):
            try:
                detail = response.json().get('detail')
            except ValueError:
                detail = None
            return jsonify({'success': False, 'error': detail if isinstance(detail, str) else 'Invalid value'}), response.status_code
    except Exception as e:
        current_app.logger.warning("FastAPI settings proxy error (using direct fallback): %s", e)

    # Fallback to in-app settings_service
    from services.settings_service import settings as app_settings
    actor = session.get('admin_username', 'admin')
    try:
        app_settings.set_many(data, updated_by=actor)
        return jsonify({'success': True, 'message': 'Settings updated successfully'})
    except Exception as exc:
        current_app.logger.error("Settings update error: %s", exc)
        return jsonify({'success': False, 'error': 'Update failed'}), 500


@admin_bp.route('/api/settings/category/<string:category>', methods=['GET'])
@login_required
def get_category_settings_api(category):
    try:
        url = f"{_get_api_base_url()}/api/v2/settings/category/{category}"
        response = requests.get(url, headers=_get_api_headers(), timeout=5)
        if response.status_code == 200:
            return (response.text, response.status_code, {'Content-Type': 'application/json'})
    except Exception:
        pass

    from services.settings_service import settings as app_settings
    by_category = app_settings.all_by_category()
    for cat, items in by_category.items():
        if cat.lower() == category.lower():
            return jsonify({'success': True, 'category': cat, 'settings': items})
    return jsonify({'success': False, 'error': 'Category not found'}), 404


@admin_bp.route('/api/settings/<string:key>', methods=['GET'])
@login_required
def get_setting(key):
    try:
        url = f"{_get_api_base_url()}/api/v2/settings/key/{key}"
        response = requests.get(url, headers=_get_api_headers(), timeout=5)
        if response.status_code == 200:
            return (response.text, response.status_code, {'Content-Type': 'application/json'})
    except Exception:
        pass

    from services.settings_service import settings as app_settings
    val = app_settings.get(key)
    if val is None:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True, 'key': key, 'value': val})


# ----------------------------------------------------------------------
# Staff Management
# ----------------------------------------------------------------------

@admin_bp.route('/staff')
@admin_required
def staff():
    from fastapi_app.services.admin.staff_service import AdminStaffService
    data = AdminStaffService.list_staff(db=db.session)
    return render_template('staff.html', staff_members=data.get('staff', []))


@admin_bp.route('/api/staff/create', methods=['POST'])
@admin_required
def create_staff():
    from fastapi_app.services.admin.staff_service import AdminStaffService
    data = request.get_json() or {}
    try:
        res = AdminStaffService.create_staff(
            db=db.session,
            username=(data.get('username') or '').strip(),
            email=(data.get('email') or '').strip(),
            full_name=(data.get('full_name') or '').strip(),
            password=data.get('password') or '',
            role=(data.get('role') or 'sales').strip().lower()
        )
        return jsonify(res), 201
    except Exception as e:
        status_code = getattr(e, 'status_code', 500)
        detail = getattr(e, 'detail', str(e))
        return jsonify({'success': False, 'error': detail}), status_code


@admin_bp.route('/api/staff/<int:user_id>/update', methods=['POST'])
@admin_required
def update_staff(user_id):
    from fastapi_app.services.admin.staff_service import AdminStaffService
    data = request.get_json() or {}
    try:
        res = AdminStaffService.update_staff(
            db=db.session,
            user_id=user_id,
            email=(data.get('email') or '').strip(),
            full_name=(data.get('full_name') or '').strip(),
            role=(data.get('role') or 'sales').strip().lower()
        )
        return jsonify(res), 200
    except Exception as e:
        status_code = getattr(e, 'status_code', 500)
        detail = getattr(e, 'detail', str(e))
        return jsonify({'success': False, 'error': detail}), status_code


@admin_bp.route('/api/staff/<int:user_id>/password', methods=['POST'])
@admin_required
def reset_staff_password(user_id):
    from fastapi_app.services.admin.staff_service import AdminStaffService
    data = request.get_json() or {}
    try:
        res = AdminStaffService.reset_password(
            db=db.session,
            user_id=user_id,
            password=data.get('password') or ''
        )
        return jsonify(res), 200
    except Exception as e:
        status_code = getattr(e, 'status_code', 500)
        detail = getattr(e, 'detail', str(e))
        return jsonify({'success': False, 'error': detail}), status_code


@admin_bp.route('/api/staff/<int:user_id>/toggle', methods=['POST'])
@admin_required
def toggle_staff_status(user_id):
    from fastapi_app.services.admin.staff_service import AdminStaffService
    try:
        res = AdminStaffService.toggle_status(
            db=db.session,
            user_id=user_id,
            current_admin_id=session.get('admin_user_id')
        )
        return jsonify(res), 200
    except Exception as e:
        status_code = getattr(e, 'status_code', 500)
        detail = getattr(e, 'detail', str(e))
        return jsonify({'success': False, 'error': detail}), status_code


@admin_bp.route('/api/staff/<int:user_id>/delete', methods=['DELETE', 'POST'])
@admin_required
def delete_staff(user_id):
    from fastapi_app.services.admin.staff_service import AdminStaffService
    try:
        res = AdminStaffService.delete_staff(
            db=db.session,
            user_id=user_id,
            current_admin_id=session.get('admin_user_id')
        )
        return jsonify(res), 200
    except Exception as e:
        status_code = getattr(e, 'status_code', 500)
        detail = getattr(e, 'detail', str(e))
        return jsonify({'success': False, 'error': detail}), status_code


@admin_bp.route('/api/staff/<int:user_id>/2fa/setup', methods=['POST'])
@login_required
def staff_2fa_setup(user_id):
    from fastapi_app.services.admin.staff_service import AdminStaffService
    try:
        res = AdminStaffService.setup_2fa(
            db=db.session,
            user_id=user_id,
            current_user_id=session.get('admin_user_id'),
            current_role=session.get('admin_role', 'admin')
        )
        session['setup_staff_2fa_secret'] = {
            'user_id': user_id,
            'secret': res['secret']
        }
        return jsonify(res), 200
    except Exception as e:
        status_code = getattr(e, 'status_code', 500)
        detail = getattr(e, 'detail', str(e))
        return jsonify({'success': False, 'error': detail}), status_code


@admin_bp.route('/api/staff/<int:user_id>/2fa/confirm', methods=['POST'])
@login_required
def staff_2fa_confirm(user_id):
    from fastapi_app.services.admin.staff_service import AdminStaffService
    setup_data = session.get('setup_staff_2fa_secret')
    secret = setup_data.get('secret') if setup_data and setup_data.get('user_id') == user_id else None
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or request.form.get('code') or '').strip()
    if not secret:
        return jsonify({'success': False, 'error': 'Setup session expired. Please try again.'}), 400
    try:
        res = AdminStaffService.confirm_2fa(
            db=db.session,
            user_id=user_id,
            secret=secret,
            code=code,
            current_user_id=session.get('admin_user_id'),
            current_role=session.get('admin_role', 'admin')
        )
        session.pop('setup_staff_2fa_secret', None)
        return jsonify(res), 200
    except Exception as e:
        status_code = getattr(e, 'status_code', 500)
        detail = getattr(e, 'detail', str(e))
        return jsonify({'success': False, 'error': detail}), status_code


@admin_bp.route('/api/staff/<int:user_id>/2fa/disable', methods=['POST'])
@login_required
def staff_2fa_disable(user_id):
    from fastapi_app.services.admin.staff_service import AdminStaffService
    data = request.get_json(silent=True) or {}
    password = data.get('password') or ''
    try:
        res = AdminStaffService.disable_2fa(
            db=db.session,
            user_id=user_id,
            password=password,
            current_user_id=session.get('admin_user_id'),
            current_role=session.get('admin_role', 'admin')
        )
        return jsonify(res), 200
    except Exception as e:
        status_code = getattr(e, 'status_code', 500)
        detail = getattr(e, 'detail', str(e))
        return jsonify({'success': False, 'error': detail}), status_code

# ======================================================================
# Admin "View As Client" Routes
# ======================================================================
# Prefix: /admin/view/<customer_id>/...
# All routes are READ-ONLY (GET only for API proxies).
# Admin must be logged in; peer must belong to the given customer.
# ======================================================================

def _admin_verify_peer(customer_id, peer_id):
    """Returns (customer, peer_data) if peer belongs to customer, else (None, None)."""
    customer = db.session.get(Client, customer_id)
    if not customer:
        return None, None
    allowed = _get_customer_group_peer_ids(customer)
    if peer_id not in allowed:
        return None, None
    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers(), cache_ttl=10)
    peer_data = next((p for p in peers_data if p.get("id") == peer_id), None)
    return customer, peer_data


def _admin_get_customer_with_peers(customer_id):
    """Returns (customer, peers_list) for aliases and sidebar."""
    customer = db.session.get(Client, customer_id)
    if not customer:
        return None, []
    allowed = _get_customer_group_peer_ids(customer)
    base_url = get_api_base_url()
    headers = get_api_headers()
    peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
    customer_peers = [p for p in peers_data if p.get("id") in allowed]

    processed = []
    if customer_peers:
        futures = {
            _admin_view_executor.submit(check_single_peer_handshake, p, base_url, headers): p
            for p in customer_peers
        }
        for future in as_completed(futures, timeout=5):
            try:
                processed.append(future.result())
            except Exception as err:
                current_app.logger.error(f"Admin view: peer handshake error: {err}")

    peers_list = [
        {
            "id": p.get("id"),
            "name": get_name_override(p.get("id")) or p.get("name"),
            "connected": p.get("is_online", False),
            "ip": p.get("ip"),
            "last_seen": p.get("last_seen"),
            "status_title": "Connected" if p.get("is_online", False) else "Offline"
        }
        for p in processed
    ]
    peers_list.sort(key=lambda p: (p.get("name") or "").lower())
    return customer, peers_list


def _admin_get_sidebar_context(customer_id):
    customer, peers_list = _admin_get_customer_with_peers(customer_id)
    online_count = sum(1 for p in peers_list if p.get("connected"))
    offline_count = len(peers_list) - online_count
    return {
        "sidebar_peers": peers_list,
        "sidebar_online_count": online_count,
        "sidebar_offline_count": offline_count,
    }


def _admin_api_base(customer_id):
    return f"/admin/view/{customer_id}"


# ----------------------------------------------------------------------
# Page Routes
# ----------------------------------------------------------------------

@admin_bp.route('/admin/view/<uuid:customer_id>/peers/<peer_id>')
@login_required
def admin_view_peer_details(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        flash("Peer not found or does not belong to this customer.", "error")
        return redirect(url_for('admin.customer_details', customer_id=customer_id))

    override_name = get_name_override(peer_id)
    peer_name = override_name or (peer_data.get("name") if peer_data else "Peer Device")
    is_online = False
    peer_ip = "Unknown"
    peer_public_ip = "Unknown"
    peer_os = "Unknown"
    peer_version = "Unknown"
    peer_uptime = "Unknown"
    peer_uptime_seconds = None
    peer_last_seen = "Never"

    if peer_data:
        try:
            base_url = get_api_base_url()
            headers = get_api_headers()
            checked = check_single_peer_handshake(peer_data, base_url, headers)
            is_online = checked.get("is_online", False)
            peer_ip = checked.get("ip", peer_ip)
            peer_public_ip = checked.get("connection_ip", peer_public_ip) or "Unknown"
            peer_os = checked.get("os", peer_os)
            peer_version = checked.get("version", peer_version)
            if is_online and peer_ip and peer_ip != "Unknown":
                try:
                    h_resp = requests.get(f"http://{peer_ip}:8765/health", timeout=(1, 2))
                    if h_resp.ok:
                        h_data = h_resp.json()
                        if h_data.get("version"):
                            peer_version = h_data["version"]
                        if h_data.get("uptime") is not None:
                            secs = int(h_data["uptime"])
                            peer_uptime_seconds = secs
                            days, rem = divmod(secs, 86400)
                            hrs, rem2 = divmod(rem, 3600)
                            mins, secs2 = divmod(rem2, 60)
                            prefix = f"{days}d " if days else ""
                            peer_uptime = f"{prefix}{hrs:02d}:{mins:02d}:{secs2:02d}"
                except Exception:
                    pass
            peer_last_seen = checked.get("last_seen", peer_last_seen)
            if peer_last_seen and peer_last_seen != "Never":
                try:
                    clean_str = peer_last_seen.replace('Z', '+00:00')
                    dt = datetime.fromisoformat(clean_str)
                    peer_last_seen = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
        except Exception as e:
            current_app.logger.error(f"Admin view: error checking peer status: {e}")

    peer_route_network = ""
    peer_route_id = ""
    peer_route_network_id = ""
    try:
        all_routes = get_cached_all_netbird_routes(get_api_base_url(), get_api_headers(), cache_ttl=10)
        overrides = get_active_route_overrides()
        if peer_id in overrides:
            peer_route_network = overrides[peer_id]
        else:
            pr = next((r for r in all_routes if r.get("peer") == peer_id), None)
            if pr:
                peer_route_network = pr.get("network", "")
                peer_route_id = pr.get("id", "")
                peer_route_network_id = pr.get("network_id", "")
    except Exception as e:
        current_app.logger.error(f"Admin view: error fetching route: {e}")

    return render_template(
        'peer_details.html',
        peer_id=peer_id,
        peer_name=peer_name,
        customer_name=customer.client_name,
        is_online=is_online,
        peer_ip=peer_ip,
        peer_public_ip=peer_public_ip,
        peer_os=peer_os,
        peer_version=peer_version,
        peer_uptime=peer_uptime,
        peer_uptime_seconds=peer_uptime_seconds,
        peer_last_seen=peer_last_seen,
        peer_network=peer_route_network,
        peer_route_id=peer_route_id,
        peer_route_network_id=peer_route_network_id,
        can_manage_services=False,
        admin_view=True,
        admin_customer_id=customer_id,
        api_base=_admin_api_base(customer_id),
        **_admin_get_sidebar_context(customer_id),
    )


@admin_bp.route('/admin/view/<uuid:customer_id>/peers/<peer_id>/firewall')
@login_required
def admin_view_peer_firewall(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        flash("Peer not found or does not belong to this customer.", "error")
        return redirect(url_for('admin.customer_details', customer_id=customer_id))

    override_name = get_name_override(peer_id)
    peer_name = override_name or (peer_data.get("name") if peer_data else "Edge Device")
    is_online = False
    vpn_only = False

    if peer_data:
        try:
            base_url = get_api_base_url()
            headers = get_api_headers()
            checked = check_single_peer_handshake(peer_data, base_url, headers)
            is_online = checked.get("is_online", False)
            if not override_name and checked.get("name"):
                peer_name = checked.get("name")
            if peer_data.get("ip"):
                vpn_only = get_cached_peer_vpn_only(peer_id, peer_data.get("ip"))
        except Exception as e:
            current_app.logger.error(f"Admin view: error checking peer for firewall: {e}")

    return render_template(
        'firewall.html',
        peer_id=peer_id,
        peer_name=peer_name,
        customer_name=customer.client_name,
        is_online=is_online,
        vpn_only=vpn_only,
        admin_view=True,
        admin_customer_id=customer_id,
        api_base=_admin_api_base(customer_id),
        **_admin_get_sidebar_context(customer_id),
    )


@admin_bp.route('/admin/view/<uuid:customer_id>/peers/<peer_id>/web-filter')
@login_required
def admin_view_peer_web_filter(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        flash("Peer not found or does not belong to this customer.", "error")
        return redirect(url_for('admin.customer_details', customer_id=customer_id))

    override_name = get_name_override(peer_id)
    peer_name = override_name or (peer_data.get("name") if peer_data else "Edge Device")
    is_online = False
    vpn_only = False

    if peer_data:
        try:
            base_url = get_api_base_url()
            headers = get_api_headers()
            checked = check_single_peer_handshake(peer_data, base_url, headers)
            is_online = checked.get("is_online", False)
            if not override_name and checked.get("name"):
                peer_name = checked.get("name")
            if peer_data.get("ip"):
                vpn_only = get_cached_peer_vpn_only(peer_id, peer_data.get("ip"))
        except Exception as e:
            current_app.logger.error(f"Admin view: error checking peer for web-filter: {e}")

    return render_template(
        'web_filter.html',
        peer_id=peer_id,
        peer_name=peer_name,
        customer_name=customer.client_name,
        is_online=is_online,
        vpn_only=vpn_only,
        admin_view=True,
        admin_customer_id=customer_id,
        api_base=_admin_api_base(customer_id),
        **_admin_get_sidebar_context(customer_id),
    )


@admin_bp.route('/admin/view/<uuid:customer_id>/peers/<peer_id>/aliases')
@admin_bp.route('/admin/view/<uuid:customer_id>/peers/aliases')
@login_required
def admin_view_peer_aliases(customer_id, peer_id=None):
    customer_id = str(customer_id)
    customer, peers_list = _admin_get_customer_with_peers(customer_id)
    if not customer:
        flash("Customer not found.", "error")
        return redirect(url_for('admin.customers'))

    if peer_id is None:
        peer_id = request.args.get('peer_id')

    if peer_id:
        allowed = _get_customer_group_peer_ids(customer)
        if peer_id not in allowed:
            flash("Peer not found or does not belong to this customer.", "error")
            return redirect(url_for('admin.customer_details', customer_id=customer_id))

    selected_peer = next((p for p in peers_list if p["id"] == peer_id), None) if peer_id else None
    peer_name = selected_peer["name"] if selected_peer else "No Peers Available"
    is_online = selected_peer["connected"] if selected_peer else False

    if not peer_id and peers_list:
        first_online = next((p for p in peers_list if p["connected"]), None)
        if first_online:
            peer_id = first_online["id"]
            peer_name = first_online["name"]
            is_online = True
            selected_peer = first_online

    online_count = sum(1 for p in peers_list if p.get("connected"))
    offline_count = len(peers_list) - online_count

    return render_template(
        'aliases.html',
        customer_name=customer.client_name,
        peers=peers_list,
        sidebar_peers=peers_list,
        sidebar_online_count=online_count,
        sidebar_offline_count=offline_count,
        selected_peer_id=peer_id,
        peer_id=peer_id,
        peer_name=peer_name,
        is_online=is_online,
        admin_view=True,
        admin_customer_id=customer_id,
        api_base=_admin_api_base(customer_id),
    )


@admin_bp.route('/admin/view/<uuid:customer_id>/peers/<peer_id>/logs/system/', strict_slashes=False)
@login_required
def admin_view_peer_system_logs(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        flash("Peer not found or does not belong to this customer.", "error")
        return redirect(url_for('admin.customer_details', customer_id=customer_id))

    return render_template(
        'system_logs.html',
        peer_id=peer_id,
        customer_name=customer.client_name,
        admin_view=True,
        admin_customer_id=customer_id,
        api_base=_admin_api_base(customer_id),
        is_readonly_subscription=True,
        **_admin_get_sidebar_context(customer_id),
    )


# ----------------------------------------------------------------------
# Read-Only API Proxy Routes
# ----------------------------------------------------------------------

@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers', methods=['GET'])
@login_required
def admin_view_api_peers(customer_id):
    customer_id = str(customer_id)
    customer = db.session.get(Client, customer_id)
    if not customer:
        return jsonify({"error": "Customer not found"}), 404
    allowed = _get_customer_group_peer_ids(customer)
    peer_name_filter = request.args.get('name', '').lower()
    try:
        peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
        result = []
        for p in peers_data:
            pid = p.get("id")
            if pid not in allowed:
                continue
            pname = get_name_override(pid) or p.get("name")
            if peer_name_filter and peer_name_filter not in (pname or "").lower():
                continue
            result.append({"id": pid, "name": pname, "connected": p.get("connected", False),
                           "last_seen": p.get("last_seen"), "ip": p.get("ip")})
        result.sort(key=lambda p: (p.get("name") or "").lower())
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/status', methods=['GET'])
@login_required
def admin_view_api_peers_status(customer_id):
    customer_id = str(customer_id)
    customer = db.session.get(Client, customer_id)
    if not customer:
        return jsonify({"error": "Customer not found"}), 404
    allowed = _get_customer_group_peer_ids(customer)
    if not allowed:
        return jsonify({"peers": [], "summary": {"total": 0, "online": 0, "offline": 0}})
    base_url = get_api_base_url()
    headers = get_api_headers()
    peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
    customer_peers = [p for p in peers_data if p.get("id") in allowed]
    processed = []
    online_count = 0
    if customer_peers:
        futures = {
            _admin_view_executor.submit(check_single_peer_handshake, p, base_url, headers): p
            for p in customer_peers
        }
        for future in as_completed(futures, timeout=15):
            try:
                res = future.result()
                processed.append(res)
                if res.get("is_online"):
                    online_count += 1
            except Exception as err:
                current_app.logger.error(f"Admin view status: {err}")
    processed.sort(key=lambda p: (p.get("name") or "").lower())
    return jsonify({
        "peers": processed,
        "summary": {"total": len(processed), "online": online_count, "offline": len(processed) - online_count}
    }), 200


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/handshake', methods=['GET'])
@login_required
def admin_view_api_peer_handshake(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, _ = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    try:
        url = f"{get_api_base_url()}/api/v1/peers/{peer_id}/handshake"
        resp = requests.get(url, headers=get_api_headers(), timeout=5)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return jsonify({"peer_id": peer_id, "is_reachable": False, "error": str(e)}), 500


@admin_bp.route('/admin/view/<uuid:customer_id>/api/v2/netbird/routes', methods=['GET'])
@login_required
def admin_view_api_routes(customer_id):
    customer_id = str(customer_id)
    customer = db.session.get(Client, customer_id)
    if not customer:
        return jsonify({"error": "Customer not found"}), 404
    allowed = _get_customer_group_peer_ids(customer)
    try:
        all_routes = get_cached_all_netbird_routes(get_api_base_url(), get_api_headers())
        overrides = get_active_route_overrides()
        result = [
            {"id": r.get("id"), "peer": r.get("peer"), "network": r.get("network"),
             "network_id": r.get("network_id"), "enabled": r.get("enabled", True),
             "description": r.get("description", "")}
            for r in all_routes if r.get("peer") in allowed
        ]
        filtered = []
        for r in result:
            pid = r.get("peer")
            if pid in overrides:
                net_val = overrides[pid]
                if net_val:
                    r["network"] = net_val
                    filtered.append(r)
            else:
                filtered.append(r)
        for pid, net_val in overrides.items():
            if net_val and not any(r.get("peer") == pid for r in filtered):
                filtered.append({"id": f"temp-route-{pid}", "peer": pid, "network": net_val,
                                  "network_id": f"temp-net-{pid}", "enabled": True, "description": ""})
        return jsonify(filtered), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/firewall/rules', methods=['GET'])
@login_required
def admin_view_api_firewall_rules(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    if not peer_data or not peer_data.get("ip"):
        return jsonify({"rules": [], "agent_online": False}), 200

    peer_ip = peer_data.get("ip")
    now = time.time()
    cached_rules, agent_online, cache_time = [], False, 0
    cache_found = False
    with firewall_cache_lock:
        if peer_id in firewall_rules_cache:
            cached_rules, agent_online, cache_time = firewall_rules_cache[peer_id]
            cache_found = True

    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    if force_refresh and (now - cache_time < 5):
        force_refresh = False
    if force_refresh or not cache_found or (now - cache_time > 15):
        try:
            resp = requests.get(f"http://{peer_ip}:8765/firewall/rules", timeout=(1, 5))
            if resp.ok:
                agent_online = True
                cached_rules = resp.json().get("rules", [])
            with firewall_cache_lock:
                firewall_rules_cache[peer_id] = (cached_rules, agent_online, time.time())
        except Exception as e:
            current_app.logger.error(f"Admin view firewall rules failed: {e}")

    rules_data = []
    for idx, lr in enumerate(cached_rules):
        src_ips = [(('@' + s[7:]) if s.startswith('@alias_') else s) for s in (lr.get("src") or [])]
        dst_ips = [(('@' + d[7:]) if d.startswith('@alias_') else d) for d in (lr.get("dst") or [])]
        src_ports = lr.get("src_port")
        dst_ports = lr.get("dst_port")
        action = lr.get("action", "DROP")
        action = "ALLOW" if action.lower() in ("accept", "allow") else "DROP"
        comment = lr.get("comment", "")
        is_auto = bool(re.match(r"^rule_\d{6}$", comment))
        rules_data.append({
            "id": idx + 1, "rule_name": "" if is_auto else comment,
            "src_ip": ",".join(src_ips) if src_ips else "Any",
            "dst_ip": ",".join(dst_ips) if dst_ips else "Any",
            "src_port": ",".join(src_ports) if isinstance(src_ports, list) else (src_ports or ""),
            "dst_port": ",".join(dst_ports) if isinstance(dst_ports, list) else (dst_ports or ""),
            "protocol": lr.get("protocol") or "any", "action": action,
            "interface": lr.get("interface") or "lan", "enabled": lr.get("enabled", True),
            "active_on_agent": True, "direction": lr.get("id"),
            "order": lr.get("order", idx + 1), "packets": lr.get("packets"), "bytes": lr.get("bytes"),
        })
    return jsonify({"rules": rules_data, "agent_online": agent_online}), 200


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/web-filter/rules', methods=['GET'])
@login_required
def admin_view_api_web_filter_rules(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    if not peer_data or not peer_data.get("ip"):
        return jsonify({"rules": [], "agent_online": False}), 200
    peer_ip = peer_data.get("ip")
    try:
        resp = requests.get(f"http://{peer_ip}:8765/web-filter/rules", timeout=(1, 10))
        if resp.ok:
            return jsonify(resp.json()), 200
    except Exception as e:
        current_app.logger.error(f"Admin view web-filter rules failed: {e}")
    return jsonify({"rules": [], "agent_online": False}), 200


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/aliases', methods=['GET'])
@login_required
def admin_view_api_aliases(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"detail": "Unauthorized"}), 403
    if not peer_data or not peer_data.get("ip"):
        return jsonify({"detail": "Peer IP not found"}), 404
    peer_ip = peer_data.get("ip")
    try:
        resp = requests.get(f"http://{peer_ip}:8765/aliases", timeout=(1, 10))
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except Exception:
        return jsonify({"detail": "Device agent is offline or unreachable"}), 503


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/adguard/blocked_services', methods=['GET'])
@login_required
def admin_view_api_adguard_blocked_services(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, _ = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    try:
        url = f"{get_api_base_url()}/api/v1/peers/{peer_id}/adguard/blocked_services"
        resp = requests.get(url, headers=get_api_headers(), timeout=10)
        if resp.ok:
            return jsonify(resp.json())
        return jsonify({"error": "Failed"}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route(
    '/admin/view/<uuid:customer_id>/api/peers/<peer_id>/adguard/clients/<client_name>/blocked_services',
    methods=['GET']
)
@login_required
def admin_view_api_adguard_client_blocked_services(customer_id, peer_id, client_name):
    customer_id = str(customer_id)
    customer, _ = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    try:
        url = f"{get_api_base_url()}/api/v1/peers/{peer_id}/adguard/clients/{client_name}/blocked_services"
        resp = requests.get(url, headers=get_api_headers(), timeout=10)
        if resp.ok:
            return jsonify(resp.json())
        return jsonify({"error": "Failed"}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/resolver-config', methods=['GET'])
@login_required
def admin_view_api_resolver_config(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, _ = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"detail": "Unauthorized"}), 403
    try:
        url = f"{get_api_base_url()}/api/v1/peers/{peer_id}/adguard/dns_info"
        resp = requests.get(url, headers=get_api_headers(), timeout=10)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except Exception:
        return jsonify({"detail": "DNS service is unreachable"}), 503


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/vpn-only', methods=['GET'])
@login_required
def admin_view_api_vpn_only(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"detail": "Unauthorized"}), 403
    if not peer_data or not peer_data.get("ip"):
        return jsonify({"detail": "Peer IP not found"}), 404
    peer_ip = peer_data.get("ip")
    try:
        resp = requests.get(f"http://{peer_ip}:8765/vpn-only", timeout=(1, 10))
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except Exception:
        return jsonify({"detail": "Device agent is offline or unreachable"}), 503


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/services', methods=['GET'])
@login_required
def admin_view_api_services(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    if not peer_data or not peer_data.get("ip"):
        return jsonify({"error": "Device unreachable"}), 404
    peer_ip = peer_data.get("ip")
    _SVC_MAP = {"adguard": "dns_filtering", "client_firewall": "firewall", "mesh_network": "mesh_network"}
    try:
        resp = requests.get(f"http://{peer_ip}:8765/services", timeout=(1, 5))
        if not resp.ok:
            return jsonify({"error": "Unable to fetch services"}), 502
        agent_data = resp.json()
        public_services = [
            {"name": _SVC_MAP[s["name"]], "state": s["state"]}
            for s in agent_data.get("services", [])
            if s.get("name") in _SVC_MAP
        ]
        return jsonify({"services": public_services}), 200
    except Exception:
        return jsonify({"error": "Device unreachable"}), 503


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/health', methods=['GET'])
@login_required
def admin_view_api_peer_health(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    if not peer_data or not peer_data.get("ip"):
        return jsonify({"error": "Device unreachable"}), 404
    peer_ip = peer_data.get("ip")
    try:
        resp = requests.get(f"http://{peer_ip}:8765/health", timeout=(1, 2))
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except Exception:
        return jsonify({"error": "Device unreachable"}), 504


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/update', methods=['GET'])
@login_required
def admin_view_api_peer_update(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    if not peer_data or not peer_data.get("ip"):
        return jsonify({"error": "Device unreachable"}), 404
    peer_ip = peer_data.get("ip")
    try:
        resp = requests.get(f"http://{peer_ip}:8765/update", timeout=(2, 15))
        if resp.status_code == 200:
            try:
                import json
                data = json.loads(resp.text)
                update_obj = data.get("update") if isinstance(data, dict) else None
                if isinstance(update_obj, dict):
                    if not update_obj.get("released_at") and not update_obj.get("release_date"):
                        from client.routes.peer_api import get_channel_manifest_data
                        channel = update_obj.get("channel") or "beta"
                        manifest = get_channel_manifest_data(channel)
                        if manifest.get("released_at"):
                            update_obj["released_at"] = manifest["released_at"]
                        elif channel != "stable":
                            stable_manifest = get_channel_manifest_data("stable")
                            if stable_manifest.get("version") == update_obj.get("available_version"):
                                update_obj["released_at"] = stable_manifest.get("released_at")
                return jsonify(data), resp.status_code
            except Exception:
                pass
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except Exception:
        return jsonify({"error": "Device unreachable"}), 503


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/update/config', methods=['GET'])
@login_required
def admin_view_api_peer_update_config(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    if not peer_data or not peer_data.get("ip"):
        return jsonify({"error": "Device unreachable"}), 404
    peer_ip = peer_data.get("ip")
    try:
        resp = requests.get(f"http://{peer_ip}:8765/update/config", timeout=(2, 10))
        if resp.ok:
            try:
                resp_json = resp.json()
                secs = resp_json.get("update_check_interval_seconds")
                if secs is not None:
                    resp_json["update_check_interval_hours"] = round(secs / 3600.0, 1)
                return jsonify(resp_json), resp.status_code
            except Exception:
                pass
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except Exception:
        return jsonify({"error": "Device unreachable"}), 503


def _admin_system_logs_reply(resp):
    """Relay an agent /logs/system reply; a 404 with no `code` means the agent has no such route."""
    if resp.status_code == 404:
        try:
            body = resp.json()
        except ValueError:
            body = None
        if not (isinstance(body, dict) and body.get("code")):
            return jsonify({"detail": "Update device", "code": "unsupported"}), 501
    return (resp.text, resp.status_code, {'Content-Type': 'application/json'})


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/logs/system', methods=['GET'])
@login_required
def admin_view_api_peer_system_logs(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    if not peer_data or not peer_data.get("ip"):
        return jsonify({"detail": "Device unreachable", "code": "offline"}), 503
    peer_ip = peer_data.get("ip")
    try:
        resp = requests.get(f"http://{peer_ip}:8765/logs/system/client", params=request.args, timeout=(5, 20))
        return _admin_system_logs_reply(resp)
    except requests.RequestException:
        return jsonify({"detail": "Device offline", "code": "offline"}), 503


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/logs/system/categories', methods=['GET'])
@login_required
def admin_view_api_peer_system_logs_categories(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    if not peer_data or not peer_data.get("ip"):
        return jsonify({"detail": "Device unreachable", "code": "offline"}), 503
    peer_ip = peer_data.get("ip")
    try:
        resp = requests.get(f"http://{peer_ip}:8765/logs/system/categories", params={"audience": "client"}, timeout=(5, 10))
        return _admin_system_logs_reply(resp)
    except requests.RequestException:
        return jsonify({"detail": "Device offline", "code": "offline"}), 503


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/logs/system/config', methods=['GET'])
@login_required
def admin_view_api_peer_system_logs_config(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    if not peer_data or not peer_data.get("ip"):
        return jsonify({"detail": "Device unreachable", "code": "offline"}), 503
    peer_ip = peer_data.get("ip")
    try:
        resp = requests.get(f"http://{peer_ip}:8765/logs/system/config", timeout=(5, 10))
        return _admin_system_logs_reply(resp)
    except requests.RequestException:
        return jsonify({"detail": "Device offline", "code": "offline"}), 503


@admin_bp.route('/admin/view/<uuid:customer_id>/api/peers/<peer_id>/logs/system/stream', methods=['GET'])
@login_required
def admin_view_api_peer_system_logs_stream(customer_id, peer_id):
    customer_id = str(customer_id)
    customer, peer_data = _admin_verify_peer(customer_id, peer_id)
    if not customer:
        return jsonify({"error": "Unauthorized"}), 403
    if not peer_data or not peer_data.get("ip"):
        return jsonify({"detail": "Device unreachable", "code": "offline"}), 503
    peer_ip = peer_data.get("ip")

    def generate():
        try:
            with requests.get(
                f"http://{peer_ip}:8765/logs/system/client/stream",
                params=request.args,
                stream=True,
                timeout=(5, 60),
                headers={"Accept": "text/event-stream"}
            ) as r:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk:
                        yield chunk
        except Exception:
            return

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ----------------------------------------------------------------------
# Admin All Peers Management
# ----------------------------------------------------------------------

@admin_bp.route('/peers')
@login_required
def peers_page():
    """Admin All Peers Overview Page."""
    from fastapi_app.services.admin.peers_service import AdminPeersService
    data = AdminPeersService.get_all_peers_data(db=db.session, force_refresh=False)
    return render_template(
        'peers.html',
        peers=data['peers'],
        stats=data['stats'],
        customers=data['customers'],
        active_page='peers'
    )


@admin_bp.route('/api/admin/peers', methods=['GET'])
@login_required
def api_admin_peers():
    """JSON API for All Peers data and live stats."""
    from fastapi_app.services.admin.peers_service import AdminPeersService
    force_refresh = request.args.get('refresh', '').lower() in ['1', 'true', 'yes']
    try:
        data = AdminPeersService.get_all_peers_data(db=db.session, force_refresh=force_refresh)
        return jsonify({
            'success': True,
            'peers': data['peers'],
            'stats': data['stats'],
            'customers': data['customers']
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching admin peers: {e}")
        return jsonify({'success': False, 'error': 'Failed to fetch peers'}), 500


