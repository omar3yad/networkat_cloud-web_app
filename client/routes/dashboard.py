from datetime import datetime
import requests
from flask import render_template, request, redirect, url_for, session, flash, jsonify, current_app
from werkzeug.security import check_password_hash, generate_password_hash

from config.database import db
from client.blueprint import client_bp
from client.decorators import login_required, verify_peer_access
from models import Client, Token
from services.edge_service import EdgeService
from services.netbird_service import (
    get_cached_customer_peer_ids,
    get_cached_all_netbird_peers,
    get_cached_all_netbird_routes,
    check_single_peer_handshake,
    clear_all_netbird_caches,
    get_api_base_url,
    get_api_headers
)
from utils.cache_manager import (
    get_name_override,
    set_name_override,
    get_active_route_overrides
)
from utils.network_validators import validate_dns_name

edge_service = EdgeService()


@client_bp.route('/')
@login_required
def dashboard():
    customer_id = session.get('client_customer_id')
    customer_name = session.get('client_customer_name')
    if not customer_id:
        flash("Customer not found", "error")
        return redirect(url_for('client.login'))
    
    # Get customer peer count from cache
    customer = Client.query.get(customer_id)
    allowed_peer_ids = get_cached_customer_peer_ids(customer) if customer else set()
    total_edges = len(allowed_peer_ids)
    
    return render_template(
        'dashboard.html',
        customer_name=customer_name,
        total_edges=total_edges,
        online_edges=0,
        offline_edges=total_edges,
        netbird_peers=[]
    )


@client_bp.route('/peers', strict_slashes=False)
@login_required
def peers_page():
    customer_id = session.get('client_customer_id')
    customer_name = session.get('client_customer_name')
    if not customer_id:
        flash("Customer not found", "error")
        return redirect(url_for('client.login'))
    
    return render_template(
        'peers.html',
        customer_name=customer_name,
        netbird_peers=[]
    )


@client_bp.route('/peers/<peer_id>')
@login_required
def peer_details(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    
    if not customer or not verify_peer_access(customer, peer_id):
        flash("Unauthorized access to this device.", "error")
        return redirect(url_for('client.dashboard'))
        
    peer_name = request.args.get('name', 'Peer Device')
    
    # Check online status and details of the peer
    is_online = False
    peer_ip = "Unknown"
    peer_public_ip = "Unknown"
    peer_os = "Unknown"
    peer_version = "Unknown"
    peer_last_seen = "Never"
    
    try:
        base_url = get_api_base_url()
        headers = get_api_headers()
        peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
        peer_data = next((p for p in peers_data if p.get("id") == peer_id), None)
        if peer_data:
            checked_peer = check_single_peer_handshake(peer_data, base_url, headers)
            is_online = checked_peer.get("is_online", False)
            peer_ip = checked_peer.get("ip", peer_ip)
            peer_public_ip = checked_peer.get("connection_ip", peer_public_ip) or "Unknown"
            peer_os = checked_peer.get("os", peer_os)
            peer_version = checked_peer.get("version", peer_version)
            if is_online and peer_ip and peer_ip != "Unknown":
                try:
                    h_resp = requests.get(f"http://{peer_ip}:8765/health", timeout=(1, 2))
                    if h_resp.ok:
                        h_data = h_resp.json()
                        if h_data.get("version"):
                            peer_version = h_data["version"]
                except Exception as ex:
                    current_app.logger.warning(f"Could not fetch health version for {peer_ip}: {ex}")
            peer_last_seen = checked_peer.get("last_seen", peer_last_seen)
            if peer_last_seen and peer_last_seen != "Never":
                try:
                    clean_str = peer_last_seen.replace('Z', '+00:00')
                    dt = datetime.fromisoformat(clean_str)
                    peer_last_seen = dt.strftime("%d/%m/%Y %H:%M:%S")
                except Exception as ex:
                    current_app.logger.error(f"Failed to format last seen '{peer_last_seen}': {ex}")
            if not request.args.get('name') and checked_peer.get('name'):
                peer_name = checked_peer.get('name')

        peer_route_network = ""
        peer_route_id = ""
        peer_route_network_id = ""
        try:
            all_routes = get_cached_all_netbird_routes(base_url, headers, cache_ttl=10)
            override_routes = get_active_route_overrides()
            if peer_id in override_routes:
                peer_route_network = override_routes[peer_id]
            else:
                peer_route = next((r for r in all_routes if r.get("peer") == peer_id), None)
                if peer_route:
                    peer_route_network = peer_route.get("network", "")
                    peer_route_id = peer_route.get("id", "")
                    peer_route_network_id = peer_route.get("network_id", "")
        except Exception as ex:
            current_app.logger.error(f"Failed to fetch peer route in peer_details: {ex}")
    except Exception as e:
        current_app.logger.error(f"Error checking peer status in peer details page: {e}")

    if customer and customer.subscription_status == 'inactive':
        is_online = False

    return render_template(
        'peer_details.html',
        peer_id=peer_id,
        peer_name=peer_name,
        customer_name=session.get('client_customer_name'),
        is_online=is_online,
        peer_ip=peer_ip,
        peer_public_ip=peer_public_ip,
        peer_os=peer_os,
        peer_version=peer_version,
        peer_last_seen=peer_last_seen,
        peer_network=peer_route_network,
        peer_route_id=peer_route_id,
        peer_route_network_id=peer_route_network_id,
        can_manage_services=bool(customer and customer.is_subscription_active)
    )


@client_bp.route('/peers/<peer_id>/update', methods=['POST'])
@login_required
def update_peer(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    new_name = data.get('name', '').strip()
    if not new_name:
        return jsonify({'success': False, 'error': 'Name required'}), 400

    is_valid, err_msg = validate_dns_name(new_name, allow_dots=False, max_length=63)
    if not is_valid:
        return jsonify({'success': False, 'error': err_msg}), 400

    # Check for duplicate device name among customer's peers
    allowed_peer_ids = get_cached_customer_peer_ids(customer)
    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    for p in peers_data:
        pid = p.get("id")
        if pid in allowed_peer_ids and pid != peer_id:
            existing_name = get_name_override(pid) or p.get("name") or ""
            if existing_name.strip().lower() == new_name.lower():
                return jsonify({'success': False, 'error': 'Name already in use'}), 400

    success, message = edge_service.update_peer_name(peer_id, new_name)
    if success:
        set_name_override(peer_id, new_name)
        clear_all_netbird_caches(customer_id)
        return jsonify({'success': True, 'message': 'Saved successfully'})
    return jsonify({'success': False, 'error': message or 'Failed to save'}), 400


@client_bp.route('/api/customer/setup-keys', methods=['GET'])
@login_required
def get_customer_setup_keys():
    customer_id = session.get('client_customer_id')
    if not customer_id:
        return jsonify({"error": "Customer association not found"}), 404
    try:
        tokens = Token.query.filter_by(client_id=customer_id).all()
        
        # Fetch NetBird setup keys
        netbird_keys = []
        try:
            base_url = get_api_base_url()
            headers = get_api_headers()
            resp = requests.get(f"{base_url}/api/v2/netbird/setup-keys", headers=headers, timeout=5)
            if resp.status_code == 200:
                netbird_keys = resp.json()
            else:
                current_app.logger.error(f"Failed to fetch setup keys from NetBird: Status {resp.status_code}")
        except Exception as e:
            current_app.logger.error(f"Error fetching setup keys from NetBird: {e}")
            
        tokens_data = []
        for t in tokens:
            db_prefix = t.token[:5]
            
            # Find matching setup key in NetBird list
            matched = None
            for nb_key in netbird_keys:
                nb_key_val = nb_key.get("key", "")
                nb_key_clean = nb_key_val.replace("*", "")
                if nb_key_clean and (db_prefix.startswith(nb_key_clean) or nb_key_clean.startswith(db_prefix)):
                    matched = nb_key
                    break
            
            if matched:
                valid = matched.get("valid", True)
                used_times = matched.get("used_times", 0)
                usage_limit = matched.get("usage_limit", 0)
                remaining_uses = (usage_limit - used_times) if usage_limit > 0 else None
            else:
                valid = t.is_active
                used_times = 0
                usage_limit = 0
                remaining_uses = None
                
            # Mask the setup key before sending it to the client frontend
            masked_token = t.token
            if len(masked_token) > 8:
                parts = masked_token.split('-', 1)
                masked_token = f"{parts[0]}-********************"
                
            tokens_data.append({
                "token": t.token,
                "is_active": valid,  # Real-time validity from NetBird
                "used_times": used_times,
                "usage_limit": usage_limit,
                "remaining_uses": remaining_uses,
                "created_at": t.created_at.strftime("%d/%m/%Y %H:%M:%S") if t.created_at else "Unknown"
            })
            
        return jsonify({"tokens": tokens_data}), 200
    except Exception as e:
        return jsonify({"error": "Database error", "details": str(e)}), 500


@client_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    customer_id = session.get('client_customer_id')
    if not customer_id:
        flash("Customer not found", "error")
        return redirect(url_for('client.login'))

    client_record = Client.query.get(customer_id)
    if not client_record:
        flash("Account not found", "error")
        return redirect(url_for('client.login'))

    if request.method == 'POST':
        client_name = (request.form.get('client_name') or '').strip()
        client_company_name = (request.form.get('client_company_name') or '').strip()
        client_phone_number = (request.form.get('client_phone_number') or '').strip()
        client_country = (request.form.get('client_country') or '').strip()

        if not client_name:
            flash("Full Name is required.", "error")
            return redirect(url_for('client.profile'))

        client_record.client_name = client_name
        client_record.client_company_name = client_company_name or None
        client_record.client_phone_number = client_phone_number or None
        client_record.client_country = client_country or None

        try:
            db.session.commit()
            session['client_customer_name'] = client_record.client_name
            flash("Profile updated successfully!", "success")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating profile for client {customer_id}: {e}")
            flash("Failed to update profile. Please try again.", "error")

        return redirect(url_for('client.profile'))

    allowed_peer_ids = get_cached_customer_peer_ids(client_record) if client_record else set()
    total_edges = len(allowed_peer_ids)

    return render_template(
        'profile.html',
        client=client_record,
        total_edges=total_edges,
        customer_name=client_record.client_name
    )


@client_bp.route('/profile/change-password', methods=['POST'])
@login_required
def change_password():
    customer_id = session.get('client_customer_id')
    if not customer_id:
        flash("Customer not found", "error")
        return redirect(url_for('client.login'))

    client_record = Client.query.get(customer_id)
    if not client_record:
        flash("Account not found", "error")
        return redirect(url_for('client.login'))

    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not current_password or not new_password or not confirm_password:
        flash("All password fields are required.", "error")
        return redirect(url_for('client.profile'))

    if not check_password_hash(client_record.password_hashed, current_password):
        flash("Current password is incorrect.", "error")
        return redirect(url_for('client.profile'))

    if len(new_password) < 8:
        flash("New password must be at least 8 characters long.", "error")
        return redirect(url_for('client.profile'))

    if new_password != confirm_password:
        flash("New passwords do not match.", "error")
        return redirect(url_for('client.profile'))

    try:
        client_record.password_hashed = generate_password_hash(new_password)
        db.session.commit()
        flash("Password updated successfully!", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error changing password for client {customer_id}: {e}")
        flash("Failed to update password. Please try again.", "error")

    return redirect(url_for('client.profile'))

