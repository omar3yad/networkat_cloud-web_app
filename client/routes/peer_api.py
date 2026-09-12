import os
import time
import requests
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import request, session, jsonify, current_app
from sqlalchemy import or_

from client.blueprint import client_bp
from client.decorators import login_required, no_cache_json, verify_peer_access, subscription_write_required
from models import Client
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
    cache_lock,
    customer_groups_cache,
    firewall_rules_cache,
    vpn_only_cache,
    read_file_cache,
    write_file_cache,
    get_name_override,
    get_active_route_overrides,
    set_route_override,
    get_vpn_only_override,
    set_vpn_only_override,
    update_customer_status_vpn_only,
    is_revalidating,
    start_revalidating,
    stop_revalidating
)
from utils.network_validators import validate_route_network

logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=30)


@client_bp.route('/api/peers', methods=['GET'])
@login_required
def proxy_peers():
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer:
        return jsonify({"error": "Unauthorized"}), 401

    allowed_peer_ids = get_cached_customer_peer_ids(customer)
    peer_name = request.args.get('name', '').lower()
    
    try:
        peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())

        sanitized_peers = []
        for p in peers_data:
            pid = p.get("id")
            if pid not in allowed_peer_ids:
                continue
            
            pname = p.get("name")
            ov_name = get_name_override(pid)
            if ov_name:
                pname = ov_name

            if peer_name and peer_name not in pname.lower():
                continue

            sanitized_peers.append({
                "id": pid,
                "name": pname,
                "connected": p.get("connected", False),
                "last_seen": p.get("last_seen"),
                "ip": p.get("ip")
            })
        sanitized_peers.sort(key=lambda p: (p.get("name") or "").lower())
        return jsonify(sanitized_peers), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/peers/<peer_id>/handshake')
@login_required
def peer_handshake(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    try:
        url = f"{get_api_base_url()}/api/v1/peers/{peer_id}/handshake"
        resp = requests.get(url, headers=get_api_headers(), timeout=5)
        if resp.ok:
            return jsonify(resp.json())
        return jsonify({"peer_id": peer_id, "is_reachable": False}), resp.status_code
    except Exception as e:
        return jsonify({"peer_id": peer_id, "is_reachable": False, "error": str(e)}), 500


@client_bp.route('/api/v2/netbird/routes', methods=['GET'])
@login_required
def proxy_get_routes():
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer:
        return jsonify({"error": "Unauthorized"}), 401

    allowed_peer_ids = get_cached_customer_peer_ids(customer)
    try:
        all_routes = get_cached_all_netbird_routes(get_api_base_url(), get_api_headers())
        sanitized_routes = [
            {
                "id": r.get("id"),
                "peer": r.get("peer"),
                "network": r.get("network"),
                "network_id": r.get("network_id"),
                "enabled": r.get("enabled", True),
                "description": r.get("description", "")
            }
            for r in all_routes if r.get("peer") in allowed_peer_ids
        ]

        # Apply route overrides (to circumvent Netbird API propagation delay)
        active_route_overrides = get_active_route_overrides()

        # 1. Update/remove existing route items
        filtered_routes = []
        for r in sanitized_routes:
            pid = r.get("peer")
            if pid in active_route_overrides:
                net_val = active_route_overrides[pid]
                if net_val:  # If not empty (meaning not deleted)
                    r["network"] = net_val
                    filtered_routes.append(r)
                # If net_val is empty string, it's deleted, so we skip/remove it!
            else:
                filtered_routes.append(r)
        sanitized_routes = filtered_routes

        # 2. Inject new route items if not present
        for pid, net_val in active_route_overrides.items():
            if net_val:
                if not any(r.get("peer") == pid for r in sanitized_routes):
                    sanitized_routes.append({
                        "id": f"temp-route-{pid}",
                        "peer": pid,
                        "network": net_val,
                        "network_id": f"temp-net-{pid}",
                        "enabled": True,
                        "description": "Temporary inline route override"
                    })
        return jsonify(sanitized_routes), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/v2/netbird/routes', methods=['POST'])
@login_required
@subscription_write_required
def proxy_post_route():
    headers = get_api_headers({"Content-Type": "application/json"})
    try:
        req_data = request.get_json() or {}
        customer_id = session.get('client_customer_id')
        username = session.get('client_username', 'user')

        if not customer_id:
            return jsonify({"error": "Unauthorized"}), 401

        customer = Client.query.get(customer_id)
        if not customer or not getattr(customer, 'netbird_group_id', None):
            return jsonify({"error": "NetBird Group ID not found for this customer"}), 400

        target_peer = req_data.get("peer")
        if not verify_peer_access(customer, target_peer):
            return jsonify({"error": "This peer does not belong to your account"}), 403

        # Validate network format and duplicate subnet
        network_val = req_data.get("network", "")
        valid, err_msg, normalized_net = validate_route_network(customer, target_peer, network_val)
        if not valid:
            return jsonify({"error": err_msg}), 400
        if normalized_net:
            req_data["network"] = normalized_net

        netbird_group_id = customer.netbird_group_id
        req_data["groups"] = [netbird_group_id]
        req_data["access_control_groups"] = [netbird_group_id]

        if not req_data.get("network_id") or req_data.get("network_id").startswith("route-"):
            peer_id = req_data.get("peer", "")[:5]
            req_data["network_id"] = f"{username.lower()}-{peer_id}"

        req_data.pop("peer_groups", None)

        url = f"{get_api_base_url()}/api/v2/netbird/routes"
        response = requests.post(url, json=req_data, headers=headers, timeout=10)
        if response.status_code in [200, 201]:
            peer_id = req_data.get("peer")
            network = req_data.get("network")
            if peer_id and network:
                set_route_override(peer_id, network)
            clear_all_netbird_caches(customer_id)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/v2/netbird/routes/<route_id>', methods=['PUT'])
@login_required
@subscription_write_required
def proxy_put_route(route_id):
    headers = get_api_headers({"Content-Type": "application/json"})
    try:
        req_data = request.get_json() or {}
        customer_id = session.get('client_customer_id')

        if not customer_id:
            return jsonify({"error": "Unauthorized"}), 401

        customer = Client.query.get(customer_id)
        if not customer or not getattr(customer, 'netbird_group_id', None):
            return jsonify({"error": "NetBird Group ID not found for this customer"}), 400

        target_peer = req_data.get("peer")
        if not verify_peer_access(customer, target_peer):
            return jsonify({"error": "This peer does not belong to your account"}), 403

        # Validate network format and duplicate subnet
        network_val = req_data.get("network", "")
        valid, err_msg, normalized_net = validate_route_network(customer, target_peer, network_val)
        if not valid:
            return jsonify({"error": err_msg}), 400
        if normalized_net:
            req_data["network"] = normalized_net

        netbird_group_id = customer.netbird_group_id
        req_data["groups"] = [netbird_group_id]
        req_data["access_control_groups"] = [netbird_group_id]
        req_data.pop("peer_groups", None)

        url = f"{get_api_base_url()}/api/v2/netbird/routes/{route_id}"
        response = requests.put(url, json=req_data, headers=headers, timeout=10)
        if response.status_code in [200, 201, 204]:
            peer_id = req_data.get("peer")
            network = req_data.get("network")
            if peer_id and network:
                set_route_override(peer_id, network)
            clear_all_netbird_caches(customer_id)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/v2/netbird/routes/<route_id>', methods=['DELETE'])
@login_required
@subscription_write_required
def proxy_delete_route(route_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer:
        return jsonify({"error": "Unauthorized"}), 401

    base_url = get_api_base_url()
    peer_id = None
    try:
        allowed_peer_ids = get_cached_customer_peer_ids(customer)
        check_resp = requests.get(f"{base_url}/api/v2/netbird/routes/{route_id}", headers=get_api_headers(), timeout=5)
        
        if check_resp.status_code == 200:
            route_data = check_resp.json()
            peer_id = route_data.get("peer")
            if route_data.get("peer") not in allowed_peer_ids:
                return jsonify({"error": "This route does not belong to your account"}), 403
        else:
            return jsonify({"error": "Failed to verify route ownership"}), check_resp.status_code
    except Exception as e:
        return jsonify({"error": "Error verifying ownership before deletion", "details": str(e)}), 500

    try:
        response = requests.delete(f"{base_url}/api/v2/netbird/routes/{route_id}", headers=get_api_headers(), timeout=10)
        if response.status_code in [200, 204]:
            if peer_id:
                set_route_override(peer_id, "")
            clear_all_netbird_caches(customer_id)
            return '', response.status_code
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/peers/<peer_id>/delete', methods=['DELETE', 'POST'])
@client_bp.route('/api/peers/<peer_id>', methods=['DELETE'])
@login_required
@subscription_write_required
def delete_peer(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    base_url = get_api_base_url()
    headers = get_api_headers()

    # Retrieve peer details to obtain IP and Name
    peer_ip = None
    peer_name = None
    try:
        peer_resp = requests.get(f"{base_url}/api/v2/netbird/peers/{peer_id}", headers=headers, timeout=5)
        if peer_resp.ok:
            p_data = peer_resp.json()
            peer_ip = p_data.get("ip")
            peer_name = p_data.get("name")
    except Exception as e:
        logger.warning(f"Could not fetch peer details from NetBird for {peer_id}: {e}")

    if not peer_ip or not peer_name:
        peers_data = get_cached_all_netbird_peers(base_url, headers)
        for p in peers_data:
            if p.get("id") == peer_id:
                peer_ip = peer_ip or p.get("ip")
                peer_name = peer_name or p.get("name")
                break

    # 1. Send uninstall command to peer agent (optional/graceful, ignore failure)
    if peer_ip:
        agent_url = f"http://{peer_ip}:8765/uninstall-peer"
        try:
            agent_resp = requests.post(agent_url, json={"peer_id": peer_id}, timeout=(1, 3))
            logger.info(f"Agent uninstall-peer call to {agent_url} returned {agent_resp.status_code}")
        except Exception as agent_err:
            logger.info(f"Agent uninstall-peer call skipped/failed for {peer_ip}: {agent_err}")

    # 2. Delete all NetBird routes associated with this peer
    try:
        routes_url = f"{base_url}/api/v2/netbird/routes"
        routes_res = requests.get(routes_url, headers=headers, timeout=5)
        if routes_res.ok:
            routes = routes_res.json()
            for route in routes:
                r_peer_id = route.get('peer_id') or route.get('peer')
                if r_peer_id == peer_id:
                    route_id = route.get('id')
                    if route_id:
                        del_route_url = f"{base_url}/api/v2/netbird/routes/{route_id}"
                        requests.delete(del_route_url, headers=headers, timeout=5)
                        logger.info(f"Deleted associated route {route_id} for peer {peer_id}")
    except Exception as r_err:
        logger.warning(f"Error deleting associated routes for peer {peer_id}: {r_err}")

    # 3. Delete peer from NetBird
    del_peer_url = f"{base_url}/api/v2/netbird/peers/{peer_id}"
    peer_del_res = requests.delete(del_peer_url, headers=headers, timeout=10)

    if not (peer_del_res.ok or peer_del_res.status_code in [204, 404]):
        return jsonify({
            'success': False,
            'error': f"Failed to delete peer from NetBird: {peer_del_res.text}"
        }), peer_del_res.status_code

    # 4. Clear caches and overrides
    for path in [
        f"/tmp/peer_name_{peer_id}.json",
        f"/tmp/peer_route_{peer_id}.json",
        f"/tmp/peer_vpn_only_{peer_id}.json"
    ]:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    with cache_lock:
        vpn_only_cache.pop(peer_id, None)
        firewall_rules_cache.pop(peer_id, None)
        customer_groups_cache.pop(customer_id, None)

    clear_all_netbird_caches(customer_id=str(customer_id))

    return jsonify({
        "success": True,
        "message": f"Peer '{peer_name or peer_id}' and all associated configurations were deleted successfully"
    }), 200


def _apply_subscription_status_overrides(payload, customer):
    if customer and customer.subscription_status == 'inactive':
        for p in payload.get("peers", []):
            p["is_online"] = False
            p["connected"] = False
        if "summary" in payload:
            total = payload["summary"].get("total", len(payload.get("peers", [])))
            payload["summary"]["online"] = 0
            payload["summary"]["offline"] = total
    return payload


def _revalidate_customer_peers_status(customer_id, customer, base_url, headers, allowed_peer_ids):
    """Background helper to refresh customer status cache."""
    try:
        peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
        customer_peers = [p for p in peers_data if p.get("id") in allowed_peer_ids]

        processed_peers = []
        online_count = 0

        if customer_peers:
            futures = {
                executor.submit(
                    check_single_peer_handshake,
                    peer, base_url, headers
                ): peer
                for peer in customer_peers
            }
            for future in as_completed(futures, timeout=15):
                try:
                    res = future.result()
                    processed_peers.append(res)
                    if res["is_online"]:
                        online_count += 1
                except Exception as err:
                    logger.error(f"Peer check error in background revalidation: {err}")

        processed_peers.sort(key=lambda p: (p.get("name") or "").lower())

        if customer and customer.subscription_status == 'inactive':
            for p in processed_peers:
                p["is_online"] = False
                p["connected"] = False
            online_count = 0

        payload = {
            "peers": processed_peers,
            "summary": {
                "total": len(processed_peers),
                "online": online_count,
                "offline": len(processed_peers) - online_count
            }
        }
        write_file_cache(f"customer_status_{customer_id}", payload)
    except Exception as e:
        logger.error(f"Background revalidation failed for customer {customer_id}: {e}")
    finally:
        stop_revalidating(customer_id)


@client_bp.route('/api/peers/status')
@login_required
def get_peers_status_api():
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer:
        return jsonify({"error": "Unauthorized"}), 401

    force_refresh = request.args.get('refresh') == 'true'
    now = time.time()
    cached_payload, cached_time = read_file_cache(f"customer_status_{customer_id}")

    base_url = get_api_base_url()
    headers = get_api_headers()
    allowed_peer_ids = get_cached_customer_peer_ids(customer, force_refresh=force_refresh)

    if not allowed_peer_ids:
        return jsonify({
            "peers": [],
            "summary": {"total": 0, "online": 0, "offline": 0}
        })

    # 1. Fresh cache (< 10s) when not forcing refresh
    if not force_refresh and cached_payload and (now - cached_time < 10):
        return no_cache_json(_apply_subscription_status_overrides(cached_payload, customer))

    # 2. Stale cache: return immediately, revalidate in background (only when not forcing refresh)
    if not force_refresh and cached_payload:
        if not is_revalidating(customer_id):
            start_revalidating(customer_id)
            executor.submit(
                _revalidate_customer_peers_status,
                customer_id, customer, base_url, headers, allowed_peer_ids
            )
        return no_cache_json(_apply_subscription_status_overrides(cached_payload, customer))

    # 3. Synchronous fresh load
    try:
        peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=0 if force_refresh else 10)
        customer_peers = [p for p in peers_data if p.get("id") in allowed_peer_ids]

        processed_peers = []
        online_count = 0

        if customer_peers:
            futures = {
                executor.submit(
                    check_single_peer_handshake,
                    peer, base_url, headers
                ): peer
                for peer in customer_peers
            }
            for future in as_completed(futures, timeout=15):
                try:
                    res = future.result()
                    processed_peers.append(res)
                    if res["is_online"]:
                        online_count += 1
                except Exception as err:
                    logger.error(f"Peer check error: {err}")

        processed_peers.sort(key=lambda p: (p.get("name") or "").lower())

        if customer and customer.subscription_status == 'inactive':
            for p in processed_peers:
                p["is_online"] = False
                p["connected"] = False
            online_count = 0

        payload = {
            "peers": processed_peers,
            "summary": {
                "total": len(processed_peers),
                "online": online_count,
                "offline": len(processed_peers) - online_count
            }
        }
        write_file_cache(f"customer_status_{customer_id}", payload)
        return no_cache_json(payload)
    except Exception as e:
        logger.error(f"Failed to fetch peers status: {e}")
        return jsonify({"error": "fetch_failed"}), 500


@client_bp.route('/api/peers/<peer_id>/vpn-only', methods=['GET', 'POST'])
@login_required
@subscription_write_required
def peer_vpn_only_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"detail": "Peer or Peer IP not found in NetBird"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/vpn-only"

    try:
        if request.method == 'POST':
            data = request.get_json() or {}
            if "action" in data and "operation" not in data:
                data["operation"] = data.pop("action")
            resp = requests.post(agent_url, json=data, timeout=(1, 10))
        else:
            resp = requests.get(agent_url, timeout=(1, 10))

        if resp.ok:
            try:
                resp_data = resp.json()
                enabled = resp_data.get("enabled")
                if enabled is not None:
                    enabled = bool(enabled)
                elif request.method == 'POST':
                    op = data.get("operation", "").lower()
                    enabled = op in ("enable", "on")

                if enabled is not None:
                    set_vpn_only_override(peer_id, enabled)
                    if customer_id:
                        update_customer_status_vpn_only(customer_id, peer_id, enabled)
            except Exception as cache_err:
                current_app.logger.error(f"Error updating vpn-only cache: {cache_err}")

        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "Device agent is offline or unreachable"}), 503


# Public-facing service names — never leak the agent's internal service
# identifiers (adguard/client_firewall/mesh_network) or its raw JSON/errors.
_SERVICE_PUBLIC_TO_INTERNAL = {
    "dns_filtering": "adguard",
    "firewall": "client_firewall",
    "mesh_network": "mesh_network",
}
_SERVICE_INTERNAL_TO_PUBLIC = {v: k for k, v in _SERVICE_PUBLIC_TO_INTERNAL.items()}


@client_bp.route('/api/peers/<peer_id>/services', methods=['GET', 'PUT'])
@login_required
@subscription_write_required
def peer_services_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Device unreachable"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/services"

    try:
        if request.method == 'PUT':
            data = request.get_json() or {}
            services = data.get("services") or {}

            internal_services = {}
            for public_name, state in services.items():
                internal_name = _SERVICE_PUBLIC_TO_INTERNAL.get(public_name)
                if not internal_name or state not in ("enabled", "disabled"):
                    return jsonify({"error": "Invalid request"}), 400
                internal_services[internal_name] = state

            if not internal_services:
                return jsonify({"error": "Invalid request"}), 400

            resp = requests.put(
                agent_url,
                json={"services": internal_services, "source": "customer"},
                timeout=(1, 10),
            )
        else:
            resp = requests.get(agent_url, timeout=(1, 5))

        if not resp.ok:
            return jsonify({"error": "Unable to update service"}), 502

        agent_data = resp.json()
        public_services = [
            {"name": _SERVICE_INTERNAL_TO_PUBLIC[s["name"]], "state": s["state"]}
            for s in agent_data.get("services", [])
            if s.get("name") in _SERVICE_INTERNAL_TO_PUBLIC
        ]
        return jsonify({"services": public_services}), 200
    except requests.RequestException:
        return jsonify({"error": "Device unreachable"}), 503
    except (ValueError, KeyError):
        return jsonify({"error": "Unable to update service"}), 502


@client_bp.route('/api/peers/<peer_id>/health', methods=['GET'])
@login_required
def peer_health_api(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Device unreachable"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/health"

    try:
        resp = requests.get(agent_url, timeout=(1, 2))
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException:
        return jsonify({"error": "Device unreachable"}), 504


@client_bp.route('/api/peers/<peer_id>/update', methods=['GET', 'POST'])
@login_required
def peer_update_api(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    if request.method == 'POST':
        if not customer.is_subscription_active or customer.subscription_status in ('inactive', 'limit_control'):
            return jsonify({"error": "Updates locked in Read-Only mode"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Device unreachable"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/update"

    try:
        if request.method == 'POST':
            payload = request.get_json(silent=True) or {}
            # Software apply can take up to 3 minutes for tarball download and engine apply
            resp = requests.post(agent_url, json=payload, timeout=(2, 180))
        else:
            resp = requests.get(agent_url, timeout=(2, 15))

        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.Timeout:
        return jsonify({"error": "Update operation timed out"}), 504
    except requests.RequestException:
        return jsonify({"error": "Device unreachable"}), 503
    except Exception as e:
        logger.error(f"Error in peer_update_api for peer {peer_id}: {e}")
        return jsonify({"error": "Unable to process update"}), 500


@client_bp.route('/api/peers/<peer_id>/update/config', methods=['GET', 'PUT'])
@login_required
def peer_update_config_api(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(get_api_base_url(), get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Device unreachable"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/update/config"

    try:
        if request.method == 'PUT':
            if not customer.is_subscription_active or customer.subscription_status in ('inactive', 'limit_control'):
                return jsonify({"error": "Modifications locked in Read-Only mode"}), 403

            data = request.get_json() or {}
            agent_payload = {}

            if "auto_update_enabled" in data:
                agent_payload["auto_update_enabled"] = bool(data["auto_update_enabled"])

            # Support interval in hours or seconds with minimum 3 hours (10,800 seconds)
            if "update_check_interval_hours" in data:
                try:
                    hours = float(data["update_check_interval_hours"])
                    if hours < 3:
                        return jsonify({"error": "Minimum interval is 3 hours"}), 400
                    agent_payload["update_check_interval_seconds"] = int(hours * 3600)
                except (ValueError, TypeError):
                    return jsonify({"error": "Invalid interval value"}), 400
            elif "update_check_interval_seconds" in data:
                try:
                    secs = int(data["update_check_interval_seconds"])
                    if secs < 10800:
                        return jsonify({"error": "Minimum interval is 3 hours"}), 400
                    agent_payload["update_check_interval_seconds"] = secs
                except (ValueError, TypeError):
                    return jsonify({"error": "Invalid interval value"}), 400

            if not agent_payload:
                return jsonify({"error": "No configuration parameters provided"}), 400

            resp = requests.put(agent_url, json=agent_payload, timeout=(2, 10))
        else:
            resp = requests.get(agent_url, timeout=(2, 10))

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
    except requests.RequestException:
        return jsonify({"error": "Device unreachable"}), 503
    except Exception as e:
        logger.error(f"Error in peer_update_config_api for peer {peer_id}: {e}")
        return jsonify({"error": "Unable to process update config"}), 500

