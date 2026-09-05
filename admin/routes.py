import os
import requests
from models import Client
from functools import wraps
from services.auth_service import AuthService
from services.customer_service import CustomerService
from services.netbird_service import get_cached_customer_peer_ids as _get_customer_group_peer_ids
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app

admin_bp = Blueprint('admin', __name__, template_folder='../templates')
auth_service = AuthService()
customer_service = CustomerService()


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
    return render_template('customer_details.html', **data)


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