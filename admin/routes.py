import os
import re
import time
import random
import requests
from datetime import datetime
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app

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
                if code == email_otp_data.get('code'):
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

    code = str(random.randint(100000, 999999))
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
@admin_required
def delete_peer(peer_id):
    headers = _get_api_headers()
    base_url = _get_api_base_url()

    try:
        # الخطوة 0: استدعاء uninstall على جهاز الـ peer نفسه (best-effort، مش هيوقف الحذف لو فشل)
        try:
            peer_resp = requests.get(f"{base_url}/api/v2/netbird/peers/{peer_id}", headers=headers, timeout=5)
            peer_ip = peer_resp.json().get("ip") if peer_resp.ok else None
        except Exception:
            peer_ip = None

        if peer_ip:
            try:
                agent_resp = requests.post(f"http://{peer_ip}:8765/uninstall", timeout=(1, 3))
                current_app.logger.info(f"Agent uninstall call to {peer_ip} returned {agent_resp.status_code}")
            except Exception as agent_err:
                current_app.logger.info(f"Agent uninstall call skipped/failed for {peer_ip}: {agent_err}")

        # الخطوة 1: جلب كل الـ Routes وفحص المرتبط منها بالـ Peer ده
        routes_url = f"{base_url}/api/v2/netbird/routes"
        routes_res = requests.get(routes_url, headers=headers)
        
        if routes_res.ok:
            routes = routes_res.json()
            # NetBird قد يرجع الـ peer المرتبط بالـ route داخل peer_id أو peer
            for route in routes:
                r_peer_id = route.get('peer_id') or route.get('peer')
                if r_peer_id == peer_id:
                    route_id = route.get('id')
                    if route_id:
                        del_route_url = f"{base_url}/api/v2/netbird/routes/{route_id}"
                        del_res = requests.delete(del_route_url, headers=headers)
                        if not del_res.ok:
                            return jsonify({
                                'success': False,
                                'error': f"Failed to delete associated route {route_id}: {del_res.text}"
                            }), 500

        # الخطوة 2: حذف الـ Peer من NetBird (سيتم إزالته من المجموعات تلقائياً)
        del_peer_url = f"{base_url}/api/v2/netbird/peers/{peer_id}"
        peer_del_res = requests.delete(del_peer_url, headers=headers)

        if peer_del_res.ok or peer_del_res.status_code == 204:
            return jsonify({'success': True, 'message': 'Peer and its associated routes deleted successfully'})
        else:
            return jsonify({
                'success': False,
                'error': f"Failed to delete peer: {peer_del_res.text}"
            }), peer_del_res.status_code

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


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
    customer = Client.query.get(customer_id)
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'}), 404

    data = request.get_json() or {}
    plan_id = data.get('plan_id')
    billing_cycle = data.get('billing_cycle')
    renewal_date_str = data.get('renewal_date')
    new_status = data.get('status')

    # Update plan
    old_plan_id = customer.plan_id
    plan = None
    if plan_id is not None:
        try:
            plan_id = int(plan_id)
            plan = SubscriptionPlan.query.get(plan_id)
            if plan:
                customer.plan_id = plan.id
                customer.subscription = plan.name
        except (ValueError, TypeError):
            pass

    # Update allowed_peers_count (custom exception or plan default)
    custom_peers = data.get('allowed_peers_count')
    if custom_peers is not None and str(custom_peers).strip() != "":
        try:
            val = int(custom_peers)
            if val > 0:
                customer.allowed_peers_count = val
        except (ValueError, TypeError):
            pass
    elif plan and plan.id != old_plan_id:
        # If plan changed and no custom override provided, adopt new plan's limit
        customer.allowed_peers_count = plan.allowed_peers_count

    # Update billing cycle
    if billing_cycle in ('monthly', 'yearly'):
        customer.billing_cycle = billing_cycle

    # Update renewal date
    if renewal_date_str:
        try:
            clean_date = renewal_date_str.split('T')[0]
            customer.renewal_date = datetime.strptime(clean_date, '%Y-%m-%d')
            # Reset renewal notification flag
            customer.renewal_notified_at = None
        except Exception as e:
            current_app.logger.warning(f"Error parsing renewal date: {e}")

    # Commit updated attributes (allowed_peers_count, plan_id, billing_cycle, renewal_date)
    db.session.commit()

    # Handle status transition if changed
    old_status = customer.subscription_status
    if new_status and new_status != old_status:
        if new_status == 'active':
            subscription_service.restore_active(customer, new_renewal_date=customer.renewal_date)
        elif new_status == 'grace_period':
            subscription_service.transition_to_grace_period(customer)
        elif new_status == 'limit_control':
            subscription_service.transition_to_limit_control(customer)
        elif new_status == 'inactive':
            subscription_service.transition_to_inactive(customer)

    try:
        db.session.refresh(customer)
    except Exception:
        pass
    sub_info = subscription_service.get_subscription_info(customer)
    return jsonify({
        'success': True,
        'message': 'Subscription updated successfully',
        'subscription': sub_info
    })


@admin_bp.route('/api/customers/<uuid:customer_id>/subscription/activate', methods=['POST'])
@login_required
def activate_customer_subscription(customer_id):
    customer = Client.query.get(customer_id)
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'}), 404

    data = request.get_json() or {}
    new_renewal = None
    if data.get('renewal_date'):
        try:
            clean_date = data['renewal_date'].split('T')[0]
            new_renewal = datetime.strptime(clean_date, '%Y-%m-%d')
        except Exception:
            pass

    plan_id = None
    if data.get('plan_id'):
        try:
            plan_id = int(data['plan_id'])
        except (ValueError, TypeError):
            pass

    billing_cycle = data.get('billing_cycle')

    success = subscription_service.restore_active(
        customer,
        new_renewal_date=new_renewal,
        plan_id=plan_id,
        billing_cycle=billing_cycle
    )
    if success:
        sub_info = subscription_service.get_subscription_info(customer)
        return jsonify({
            'success': True,
            'message': f"Customer '{customer.username}' activated successfully and mesh restored.",
            'subscription': sub_info
        })
    return jsonify({'success': False, 'error': 'Failed to activate customer subscription'}), 500


@admin_bp.route('/api/customers/<uuid:customer_id>/subscription/suspend', methods=['POST'])
@login_required
def suspend_customer_subscription(customer_id):
    customer = Client.query.get(customer_id)
    if not customer:
        return jsonify({'success': False, 'error': 'Customer not found'}), 404

    success = subscription_service.transition_to_inactive(customer)
    if success:
        sub_info = subscription_service.get_subscription_info(customer)
        return jsonify({
            'success': True,
            'message': f"Customer '{customer.username}' suspended successfully and mesh disconnected.",
            'subscription': sub_info
        })
    return jsonify({'success': False, 'error': 'Failed to suspend customer subscription'}), 500


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
    renewal_str = customer.renewal_date.strftime('%d %b %Y') if customer.renewal_date else 'Soon'

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

@admin_bp.route('/staff')
@admin_required
def staff():
    from repositories.user_repository import UserRepository
    users = UserRepository.get_all_desc()
    users_data = []
    for u in users:
        users_data.append({
            'id': u.id,
            'username': u.username,
            'full_name': u.full_name,
            'email': u.email,
            'role': getattr(u, 'role', 'admin') or 'admin',
            'is_active': bool(u.is_active),
            'is_2fa_enabled': bool(getattr(u, 'is_2fa_enabled', False)),
            'last_login': u.last_login.strftime('%Y-%m-%d %H:%M') if getattr(u, 'last_login', None) else None,
            'created_at': u.created_at.strftime('%Y-%m-%d') if getattr(u, 'created_at', None) else None
        })
    return render_template('staff.html', staff_members=users_data)


@admin_bp.route('/api/staff/create', methods=['POST'])
@admin_required
def create_staff():
    from repositories.user_repository import UserRepository
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip()
    full_name = (data.get('full_name') or '').strip()
    password = data.get('password') or ''
    role = (data.get('role') or 'sales').strip().lower()

    if not username or not email or not full_name or not password:
        return jsonify({'success': False, 'error': 'All fields are required.'}), 400

    if not re.match(r'^[a-zA-Z0-9_-]{3,32}$', username):
        return jsonify({'success': False, 'error': 'Username must be 3-32 characters (letters, numbers, _ and - only).'}), 400

    if len(password) < 6:
        return jsonify({'success': False, 'error': 'Password must be at least 6 characters.'}), 400

    if role not in ['admin', 'sales', 'support']:
        role = 'sales'

    if UserRepository.get_by_username(username):
        return jsonify({'success': False, 'error': f'Username "{username}" is already taken.'}), 400

    if UserRepository.get_by_email(email):
        return jsonify({'success': False, 'error': f'Email "{email}" is already registered.'}), 400

    try:
        user = UserRepository.create(
            username=username,
            email=email,
            full_name=full_name,
            raw_password=password,
            role=role,
            is_active=True
        )
        return jsonify({
            'success': True,
            'message': 'Staff member created successfully',
            'staff': {
                'id': user.id,
                'username': user.username,
                'full_name': user.full_name,
                'email': user.email,
                'role': user.role,
                'is_active': user.is_active
            }
        }), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/staff/<int:user_id>/update', methods=['POST'])
@admin_required
def update_staff(user_id):
    from repositories.user_repository import UserRepository
    user = UserRepository.get_by_id(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'Staff member not found.'}), 404

    data = request.get_json() or {}
    email = (data.get('email') or '').strip()
    full_name = (data.get('full_name') or '').strip()
    role = (data.get('role') or user.role).strip().lower()

    if not email or not full_name:
        return jsonify({'success': False, 'error': 'Email and Full Name are required.'}), 400

    if role not in ['admin', 'sales', 'support']:
        role = user.role

    existing = UserRepository.get_by_email(email)
    if existing and existing.id != user.id:
        return jsonify({'success': False, 'error': f'Email "{email}" is already in use by another user.'}), 400

    try:
        UserRepository.update(user, email=email, full_name=full_name, role=role)
        return jsonify({'success': True, 'message': 'Staff info updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/staff/<int:user_id>/password', methods=['POST'])
@admin_required
def reset_staff_password(user_id):
    from repositories.user_repository import UserRepository
    user = UserRepository.get_by_id(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'Staff member not found.'}), 404

    data = request.get_json() or {}
    password = data.get('password') or ''
    if len(password) < 6:
        return jsonify({'success': False, 'error': 'Password must be at least 6 characters.'}), 400

    try:
        UserRepository.update_password(user, password)
        return jsonify({'success': True, 'message': 'Password reset successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/staff/<int:user_id>/toggle', methods=['POST'])
@admin_required
def toggle_staff_status(user_id):
    from repositories.user_repository import UserRepository
    user = UserRepository.get_by_id(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'Staff member not found.'}), 404

    current_admin_id = session.get('admin_user_id')
    if str(user.id) == str(current_admin_id):
        return jsonify({'success': False, 'error': 'You cannot deactivate your own account.'}), 400

    try:
        new_status = UserRepository.toggle_status(user)
        return jsonify({'success': True, 'is_active': new_status, 'message': 'Status updated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/staff/<int:user_id>/delete', methods=['DELETE', 'POST'])
@admin_required
def delete_staff(user_id):
    from repositories.user_repository import UserRepository
    user = UserRepository.get_by_id(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'Staff member not found.'}), 404

    current_admin_id = session.get('admin_user_id')
    if str(user.id) == str(current_admin_id):
        return jsonify({'success': False, 'error': 'You cannot delete your own account.'}), 400

    try:
        UserRepository.delete(user)
        return jsonify({'success': True, 'message': 'Staff member deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/staff/<int:user_id>/2fa/setup', methods=['POST'])
@login_required
def staff_2fa_setup(user_id):
    current_admin_id = session.get('admin_user_id')
    current_role = session.get('admin_role')
    if str(user_id) != str(current_admin_id) and current_role != 'admin':
        return jsonify({'success': False, 'error': 'Permission denied.'}), 403

    user = UserRepository.get_by_id(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found.'}), 404

    secret = generate_totp_secret()
    session['setup_staff_2fa_secret'] = {
        'user_id': user.id,
        'secret': secret
    }

    uri = get_totp_uri(secret, user.username, issuer="Networkat Management")
    qr_b64 = generate_qr_base64(uri)

    return jsonify({
        'success': True,
        'secret': secret,
        'qr_code': qr_b64
    })


@admin_bp.route('/api/staff/<int:user_id>/2fa/confirm', methods=['POST'])
@login_required
def staff_2fa_confirm(user_id):
    current_admin_id = session.get('admin_user_id')
    current_role = session.get('admin_role')
    if str(user_id) != str(current_admin_id) and current_role != 'admin':
        return jsonify({'success': False, 'error': 'Permission denied.'}), 403

    user = UserRepository.get_by_id(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found.'}), 404

    setup_data = session.get('setup_staff_2fa_secret')
    if not setup_data or setup_data.get('user_id') != user.id:
        return jsonify({'success': False, 'error': 'Setup session expired. Please try again.'}), 400

    secret = setup_data.get('secret')
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or request.form.get('code') or '').strip()

    if not verify_totp_code(secret, code):
        return jsonify({'success': False, 'error': 'Invalid verification code.'}), 400

    recovery_codes = generate_recovery_codes(8)
    hashed_codes = hash_recovery_codes(recovery_codes)

    try:
        user.totp_secret = secret
        user.is_2fa_enabled = True
        user.recovery_codes = hashed_codes
        user.two_fa_method = 'totp'
        db.session.commit()
        session.pop('setup_staff_2fa_secret', None)
        return jsonify({
            'success': True,
            'recovery_codes': recovery_codes,
            'message': 'Two-factor authentication enabled successfully'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/staff/<int:user_id>/2fa/disable', methods=['POST'])
@login_required
def staff_2fa_disable(user_id):
    current_admin_id = session.get('admin_user_id')
    current_role = session.get('admin_role')

    is_self = str(user_id) == str(current_admin_id)
    is_admin = current_role == 'admin'

    if not (is_self or is_admin):
        return jsonify({'success': False, 'error': 'Permission denied.'}), 403

    user = UserRepository.get_by_id(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found.'}), 404

    data = request.get_json(silent=True) or {}
    password = data.get('password') or ''
    if is_self and not is_admin:
        if not password:
            return jsonify({'success': False, 'error': 'Password is required to disable 2FA.'}), 400
        user_password = getattr(user, 'password_hashed', getattr(user, 'password_hash', None))
        if not user_password or not verify_password(password, user_password):
            return jsonify({'success': False, 'error': 'Incorrect password.'}), 400

    try:
        user.is_2fa_enabled = False
        user.totp_secret = None
        user.recovery_codes = None
        user.two_fa_method = 'totp'
        db.session.commit()
        return jsonify({
            'success': True,
            'message': 'Two-factor authentication disabled'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

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
                    peer_last_seen = dt.strftime("%d/%m/%Y %H:%M:%S")
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
