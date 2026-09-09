import os
import requests
from datetime import datetime
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app

from extensions import db
from models import Client
from models.subscription_plan import SubscriptionPlan
from services.auth_service import AuthService
from services.customer_service import CustomerService
from services.subscription_service import SubscriptionService
from services.netbird_service import get_cached_customer_peer_ids as _get_customer_group_peer_ids

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


def _get_api_base_url():
    return current_app.config.get('NETBIRD_API_BASE_URL', 'https://api.networkat.cloud')

def _get_api_headers(extra_headers=None):
    token = "57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {token}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ClientApp/1.0'
    }
    if extra_headers:
        headers.update(extra_headers)
    return headers
    
@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        success, message = auth_service.authenticate(username, password)
        if success:
            return redirect(url_for('admin.dashboard'))
        flash(message, 'error')
    return render_template('login.html')


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

    plans = SubscriptionPlan.query.order_by(SubscriptionPlan.peer_limit.asc()).all()
    customer = data.get('customer')
    sub_info = subscription_service.get_subscription_info(customer) if customer else {}

    return render_template('customer_details.html', **data, plans=plans, subscription_info=sub_info)


@admin_bp.route('/customers/create', methods=['POST'])
@login_required
def create_customer():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    client_name = data.get('client_name') or data.get('name')

    if not username or not password or not client_name:
        return jsonify({'success': False, 'error': 'Required fields (username, password, client_name) are missing'}), 400

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
@login_required
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
@login_required
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
def delete_peer(peer_id):
    headers = _get_api_headers()
    base_url = _get_api_base_url()

    try:
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
    if plan_id is not None:
        try:
            plan_id = int(plan_id)
            plan = SubscriptionPlan.query.get(plan_id)
            if plan:
                customer.plan_id = plan.id
                customer.subscription = plan.name
        except (ValueError, TypeError):
            pass

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
    else:
        db.session.commit()

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