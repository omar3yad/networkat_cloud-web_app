import requests
from flask import render_template, request, redirect, url_for, session, flash, jsonify, current_app

from client.blueprint import client_bp
from client.decorators import login_required, verify_peer_access
from models import Client
from services.netbird_service import (
    get_cached_all_netbird_peers,
    get_cached_peer_vpn_only,
    check_single_peer_handshake,
    get_api_base_url,
    get_api_headers
)
from utils.cache_manager import get_name_override


@client_bp.route('/peers/<peer_id>/web-filter')
@login_required
def peer_web_filter(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    
    if not customer or not verify_peer_access(customer, peer_id):
        flash("Unauthorized access to this device.", "error")
        return redirect(url_for('client.dashboard'))

    is_online = False
    peer_name = 'Edge Device'
    
    override_name = get_name_override(peer_id)
    if override_name:
        peer_name = override_name

    vpn_only = False
    try:
        base_url = get_api_base_url()
        headers = get_api_headers()
        peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
        peer_data = next((p for p in peers_data if p.get("id") == peer_id), None)
        if peer_data:
            checked_peer = check_single_peer_handshake(peer_data, base_url, headers)
            is_online = checked_peer.get("is_online", False)
            if not override_name and checked_peer.get('name'):
                peer_name = checked_peer.get('name')
            if peer_data.get("ip"):
                vpn_only = get_cached_peer_vpn_only(peer_id, peer_data.get("ip"))
    except Exception as e:
        current_app.logger.error(f"Error checking peer status on loading web filter page: {e}")

    if not is_online:
        return redirect(url_for('client.peer_details', peer_id=peer_id))

    return render_template(
        'web_filter.html',
        peer_id=peer_id,
        peer_name=peer_name,
        customer_name=session.get('client_customer_name'),
        is_online=is_online,
        vpn_only=vpn_only
    )


@client_bp.route('/peers/<peer_id>/filtering')
@login_required
def peer_filtering(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    
    if not customer or not verify_peer_access(customer, peer_id):
        flash("Unauthorized access to this device.", "error")
        return redirect(url_for('client.dashboard'))

    is_online = False
    try:
        base_url = get_api_base_url()
        headers = get_api_headers()
        peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
        peer_data = next((p for p in peers_data if p.get("id") == peer_id), None)
        if peer_data:
            checked_peer = check_single_peer_handshake(peer_data, base_url, headers)
            is_online = checked_peer.get("is_online", False)
    except Exception as e:
        current_app.logger.error(f"Error checking peer status on loading filtering page: {e}")

    if not is_online:
        return redirect(url_for('client.peer_details', peer_id=peer_id))

    peer_name = request.args.get('name', 'Edge Device')
    return render_template(
        'filtering.html',
        peer_id=peer_id,
        peer_name=peer_name,
        customer_name=session.get('client_customer_name'),
        is_online=is_online
    )


@client_bp.route('/api/peers/<peer_id>/adguard/blocked_services', methods=['GET'])
@login_required
def get_peer_blocked_services(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None

    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    try:
        url = f"{get_api_base_url()}/api/v1/peers/{peer_id}/adguard/blocked_services"
        resp = requests.get(url, headers=get_api_headers(), timeout=10)
        if resp.ok:
            return jsonify(resp.json())
        return jsonify({"error": "Failed to fetch blocked services"}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/peers/<peer_id>/adguard/blocked_services', methods=['POST', 'PUT'])
@login_required
def update_peer_blocked_services(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None

    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    try:
        payload = request.get_json() or {}
        headers = get_api_headers({'Content-Type': 'application/json'})
        url = f"{get_api_base_url()}/api/v1/peers/{peer_id}/adguard/blocked_services"
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.ok:
            return jsonify(resp.json())
        return jsonify({"error": "Failed to update blocked services", "details": resp.text}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/peers/<peer_id>/adguard/clients/<client_name>/blocked_services', methods=['GET'])
@login_required
def get_client_blocked_services_proxy(peer_id, client_name):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None

    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    try:
        url = f"{get_api_base_url()}/api/v1/peers/{peer_id}/adguard/clients/{client_name}/blocked_services"
        resp = requests.get(url, headers=get_api_headers(), timeout=10)
        if resp.ok:
            return jsonify(resp.json())
        return jsonify({"error": "Failed to fetch client blocked services"}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/peers/<peer_id>/adguard/clients/<client_name>/blocked_services', methods=['POST', 'PUT'])
@login_required
def update_client_blocked_services_proxy(peer_id, client_name):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None

    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    try:
        payload = request.get_json() or {}
        headers = get_api_headers({'Content-Type': 'application/json'})
        url = f"{get_api_base_url()}/api/v1/peers/{peer_id}/adguard/clients/{client_name}/blocked_services"
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.ok:
            return jsonify(resp.json())
        return jsonify({"error": "Failed to update client blocked services", "details": resp.text}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/peers/<peer_id>/web-filter/rules', methods=['GET'])
@login_required
def get_peer_web_filter_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"rules": [], "agent_online": False}), 200

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules"
    try:
        resp = requests.get(agent_url, timeout=10)
        if resp.ok:
            data = resp.json()
            return jsonify({
                "rules": data.get("rules", []),
                "agent_online": True
            }), 200
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"rules": [], "agent_online": False, "error": str(e)}), 200


def _sanitize_web_filter_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return payload
    
    # 1. Sanitize 'src'
    src = payload.get("src")
    if isinstance(src, list):
        sanitized_src = []
        for s in src:
            if isinstance(s, str) and s.startswith("@") and not s.startswith("@alias_"):
                sanitized_src.append("@alias_" + s[1:])
            else:
                sanitized_src.append(s)
        payload["src"] = sanitized_src
    
    # 2. Sanitize 'domains'
    domains = payload.get("domains")
    if isinstance(domains, list):
        sanitized_domains = []
        for d in domains:
            if isinstance(d, str) and d.startswith("@") and not d.startswith("@alias_"):
                sanitized_domains.append("@alias_" + d[1:])
            else:
                sanitized_domains.append(d)
        payload["domains"] = sanitized_domains
        
    return payload


@client_bp.route('/api/peers/<peer_id>/web-filter/rules', methods=['POST'])
@login_required
def add_peer_web_filter_rule(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules"
    payload = _sanitize_web_filter_payload(request.get_json() or {})
    
    try:
        resp = requests.post(agent_url, json=payload, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503


@client_bp.route('/api/peers/<peer_id>/web-filter/rules/<rule_id>', methods=['PUT'])
@login_required
def update_peer_web_filter_rule(peer_id, rule_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules/{rule_id}"
    payload = _sanitize_web_filter_payload(request.get_json() or {})
    
    try:
        resp = requests.put(agent_url, json=payload, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503


@client_bp.route('/api/peers/<peer_id>/web-filter/rules/<rule_id>', methods=['DELETE'])
@login_required
def delete_peer_web_filter_rule(peer_id, rule_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules/remove"
    
    try:
        resp = requests.post(agent_url, json={"ids": [rule_id]}, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503


@client_bp.route('/api/peers/<peer_id>/web-filter/rules/remove', methods=['POST'])
@login_required
def bulk_remove_peer_web_filter_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules/remove"
    payload = request.get_json() or {}
    
    try:
        resp = requests.post(agent_url, json=payload, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503


@client_bp.route('/api/peers/<peer_id>/web-filter/rules/enable', methods=['POST'])
@login_required
def enable_peer_web_filter_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules/enable"
    payload = request.get_json() or {}
    
    try:
        resp = requests.post(agent_url, json=payload, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503


@client_bp.route('/api/peers/<peer_id>/web-filter/rules/disable', methods=['POST'])
@login_required
def disable_peer_web_filter_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules/disable"
    payload = request.get_json() or {}
    
    try:
        resp = requests.post(agent_url, json=payload, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503
