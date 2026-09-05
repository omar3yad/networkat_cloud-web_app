import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import render_template, request, redirect, url_for, session, flash, jsonify, current_app

from client.blueprint import client_bp
from client.decorators import login_required, verify_peer_access
from models import Client
from services.netbird_service import (
    get_cached_customer_peer_ids,
    get_cached_all_netbird_peers,
    check_single_peer_handshake,
    get_api_base_url,
    get_api_headers
)

executor = ThreadPoolExecutor(max_workers=20)


@client_bp.route('/peers/aliases')
@login_required
def aliases_page():
    customer_id = session.get('client_customer_id')
    customer_name = session.get('client_customer_name')
    if not customer_id:
        flash("Customer not found", "error")
        return redirect(url_for('client.login'))
    
    peer_id = request.args.get('peer_id')
    filter_val = request.args.get('filter')
    
    customer = Client.query.get(customer_id)
    peers_list = []
    if customer:
        try:
            allowed_peer_ids = get_cached_customer_peer_ids(customer)
            base_url = get_api_base_url()
            headers = get_api_headers()
            peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
            customer_peers = [p for p in peers_data if p.get("id") in allowed_peer_ids]
            
            processed_peers = []
            if customer_peers:
                futures = {
                    executor.submit(
                        check_single_peer_handshake,
                        peer, base_url, headers
                    ): peer
                    for peer in customer_peers
                }
                for future in as_completed(futures, timeout=5):
                    try:
                        res = future.result()
                        processed_peers.append(res)
                    except Exception as err:
                        current_app.logger.error(f"Peer handshake check error in aliases_page: {err}")
            
            peers_list = [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "connected": p.get("is_online", False),
                    "ip": p.get("ip")
                }
                for p in processed_peers
            ]
            peers_list.sort(key=lambda p: (p.get("name") or "").lower())
        except Exception as e:
            current_app.logger.error(f"Error fetching peers for aliases page: {e}")

    if not peer_id and peers_list:
        first_online = next((p for p in peers_list if p["connected"]), None)
        target_peer = first_online if first_online else peers_list[0]
        url = url_for('client.peer_aliases', peer_id=target_peer["id"])
        if filter_val:
            url += f"?filter={filter_val}"
        return redirect(url)
    elif peer_id:
        url = url_for('client.peer_aliases', peer_id=peer_id)
        if filter_val:
            url += f"?filter={filter_val}"
        return redirect(url)

    return render_template(
        'aliases.html',
        customer_name=customer_name,
        peers=peers_list,
        selected_peer_id=None,
        peer_name='No Peers Available',
        is_online=False
    )


@client_bp.route('/peers/<peer_id>/aliases')
@login_required
def peer_aliases(peer_id):
    customer_id = session.get('client_customer_id')
    customer_name = session.get('client_customer_name')
    if not customer_id:
        flash("Customer not found", "error")
        return redirect(url_for('client.login'))
    
    customer = Client.query.get(customer_id)
    if not customer or not verify_peer_access(customer, peer_id):
        flash("Unauthorized access to this device.", "error")
        return redirect(url_for('client.dashboard'))
        
    peers_list = []
    if customer:
        try:
            allowed_peer_ids = get_cached_customer_peer_ids(customer)
            base_url = get_api_base_url()
            headers = get_api_headers()
            peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
            customer_peers = [p for p in peers_data if p.get("id") in allowed_peer_ids]
            
            processed_peers = []
            if customer_peers:
                futures = {
                    executor.submit(
                        check_single_peer_handshake,
                        peer, base_url, headers
                    ): peer
                    for peer in customer_peers
                }
                for future in as_completed(futures, timeout=5):
                    try:
                        res = future.result()
                        processed_peers.append(res)
                    except Exception as err:
                        current_app.logger.error(f"Peer handshake check error in peer_aliases: {err}")
            
            peers_list = [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "connected": p.get("is_online", False),
                    "ip": p.get("ip")
                }
                for p in processed_peers
            ]
            peers_list.sort(key=lambda p: (p.get("name") or "").lower())
        except Exception as e:
            current_app.logger.error(f"Error fetching peers for peer_aliases: {e}")

    # Check if selected peer exists in list
    selected_peer = next((p for p in peers_list if p["id"] == peer_id), None)
    selected_peer_name = selected_peer["name"] if selected_peer else "Peer Device"
    is_online = selected_peer["connected"] if selected_peer else False

    return render_template(
        'aliases.html',
        customer_name=customer_name,
        peers=peers_list,
        selected_peer_id=peer_id,
        peer_id=peer_id,
        peer_name=selected_peer_name,
        is_online=is_online
    )


@client_bp.route('/api/peers/<peer_id>/aliases', methods=['GET'])
@login_required
def get_peer_address_lists_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"detail": "Peer or Peer IP not found in NetBird"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/aliases"

    try:
        resp = requests.get(agent_url, timeout=10)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "Device agent is offline or unreachable"}), 503


@client_bp.route('/api/peers/<peer_id>/aliases', methods=['POST'])
@login_required
def add_peer_address_list_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"detail": "Peer or Peer IP not found in NetBird"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/aliases"

    try:
        data = request.get_json() or {}
        resp = requests.post(agent_url, json=data, timeout=10)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "Device agent is offline or unreachable"}), 503


@client_bp.route('/api/peers/<peer_id>/aliases/<slug>', methods=['PUT', 'DELETE', 'PATCH'])
@login_required
def modify_peer_address_list_proxy(peer_id, slug):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"detail": "Peer or Peer IP not found in NetBird"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/aliases/{slug}"

    try:
        if request.method == 'PUT':
            data = request.get_json() or {}
            resp = requests.put(agent_url, json=data, timeout=10)
        elif request.method == 'PATCH':
            data = request.get_json() or {}
            resp = requests.patch(agent_url, json=data, timeout=10)
        else:
            resp = requests.delete(agent_url, timeout=10)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "Device agent is offline or unreachable"}), 503


@client_bp.route('/api/peers/<peer_id>/aliases/sync', methods=['POST'])
@login_required
def sync_peer_address_lists_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"detail": "Peer or Peer IP not found in NetBird"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/aliases/sync"

    try:
        resp = requests.post(agent_url, timeout=10)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "Device agent is offline or unreachable"}), 503


@client_bp.route('/api/peers/<peer_id>/resolver-config', methods=['GET'])
@login_required
def get_peer_resolver_config_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    url = f"{get_api_base_url()}/api/v1/peers/{peer_id}/adguard/dns_info"
    headers = get_api_headers()

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "AdGuard service is offline or unreachable"}), 503


@client_bp.route('/api/peers/<peer_id>/resolver-config', methods=['PUT'])
@login_required
def update_peer_resolver_config_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    url = f"{get_api_base_url()}/api/v1/peers/{peer_id}/adguard/dns_config"
    headers = get_api_headers()

    try:
        data = request.get_json() or {}
        
        # 1. Update AdGuard via FastAPI
        resp = requests.post(url, json=data, headers=headers, timeout=10)
        
        # 2. Extract forwarding config and send to Peer Agent's /dns-forwarding endpoint
        upstream_dns = data.get("upstream_dns", [])
        forwarding_config = {}
        for item in upstream_dns:
            match = re.match(r"^\[/([a-zA-Z0-9._-]+)/\](.+)$", item)
            if match:
                domain = match.group(1)
                ip = match.group(2)
                if domain not in forwarding_config:
                    forwarding_config[domain] = []
                forwarding_config[domain].append(ip)

        peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
        peer = next((p for p in peers_data if p.get("id") == peer_id), None)
        if peer and peer.get("ip"):
            peer_ip = peer.get("ip")
            agent_url = f"http://{peer_ip}:8765/dns-forwarding"
            try:
                agent_resp = requests.put(agent_url, json=forwarding_config, timeout=10)
                if not agent_resp.ok:
                    current_app.logger.error(f"Failed to update dns-forwarding on agent: {agent_resp.text}")
            except Exception as e:
                current_app.logger.error(f"Error communicating with agent for dns-forwarding: {e}")

        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "AdGuard service is offline or unreachable"}), 503
