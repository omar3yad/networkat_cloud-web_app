# /opt/networkat_sdwan/core/web_app/fastapi_app/services/admin/peers_service.py
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from models.client import Client
from models.group_peer import GroupPeer
from services.netbird_service import (
    get_cached_all_netbird_peers,
    check_single_peer_handshake,
    get_api_base_url,
    get_api_headers,
    clear_all_netbird_caches,
)

logger = logging.getLogger(__name__)
_admin_executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="AdminPeers")


class AdminPeersService:
    """Service layer for Admin Peers live inventory, status validation, and aggregation."""

    @classmethod
    def get_all_peers_data(cls, db: Session, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Retrieves all customer peers with live/cached status, mapped to their client owners.
        Returns a dictionary with 'peers', 'stats', and 'customers'.
        """
        # 1. Fetch all clients and map netbird group IDs
        clients: List[Client] = db.query(Client).all()
        client_group_ids = {c.netbird_group_id for c in clients if c.netbird_group_id}
        group_to_client = {c.netbird_group_id: c for c in clients if c.netbird_group_id}

        # 2. Query group-peer mappings
        all_gps: List[GroupPeer] = (
            db.query(GroupPeer).filter(GroupPeer.group_id.in_(client_group_ids)).all()
            if client_group_ids else []
        )
        peer_to_client = {}
        for gp in all_gps:
            if gp.peer_id and gp.group_id in group_to_client:
                peer_to_client[gp.peer_id] = group_to_client[gp.group_id]

        # 3. Fetch NetBird peers
        base_url = get_api_base_url()
        headers = get_api_headers()
        cache_ttl = 0 if force_refresh else 10
        all_nb_peers = get_cached_all_netbird_peers(base_url, headers, cache_ttl=cache_ttl)

        # 4. Target peers (filter to client-owned peers or all if unmapped)
        target_peers = [p for p in all_nb_peers if p.get('id') in peer_to_client] if peer_to_client else all_nb_peers

        # 5. Concurrent handshake check
        processed_peers = []
        if target_peers:
            futures = {
                _admin_executor.submit(check_single_peer_handshake, p, base_url, headers): p
                for p in target_peers
            }
            for future in as_completed(futures, timeout=10):
                try:
                    processed_peers.append(future.result())
                except Exception as err:
                    logger.error(f"Admin peer handshake check failed: {err}")

        raw_by_id = {p.get('id'): p for p in target_peers}
        peers_list = []
        online_count = 0

        # 6. Format and map peers
        for p in processed_peers:
            pid = p.get('id')
            raw = raw_by_id.get(pid, {})
            client = peer_to_client.get(pid)
            is_online = bool(p.get('is_online'))
            if is_online:
                online_count += 1

            os_str = raw.get('os') or ''
            version_str = raw.get('version') or ''

            customer_data = None
            if client:
                plan_name = 'Standard'
                if getattr(client, 'plan', None) and getattr(client.plan, 'name', None):
                    plan_name = client.plan.name
                elif getattr(client, 'subscription', None):
                    plan_name = client.subscription

                customer_data = {
                    'id': str(client.user_id),
                    'name': client.client_name or client.username or 'Customer',
                    'username': client.username or '',
                    'company': client.client_company_name or '',
                    'email': client.client_email or '',
                    'plan': plan_name
                }

            peers_list.append({
                'id': pid,
                'name': p.get('name') or raw.get('name') or 'Unnamed peer',
                'hostname': raw.get('hostname') or p.get('name') or '',
                'ip': p.get('ip') or raw.get('ip') or '—',
                'connection_ip': p.get('connection_ip') or raw.get('connection_ip') or '—',
                'connected': bool(p.get('connected', False)),
                'is_reachable': bool(p.get('is_reachable', False)),
                'is_online': is_online,
                'status_label': 'Online' if is_online else ('Unreachable' if p.get('connected') else 'Offline'),
                'last_seen': raw.get('last_seen') or p.get('last_seen') or '',
                'os': os_str,
                'version': version_str,
                'vpn_only': bool(p.get('vpn_only', False)),
                'customer': customer_data
            })

        # Sort: Online peers first, then alphabetically by name
        peers_list.sort(key=lambda x: (not x['is_online'], (x['name'] or '').lower()))

        total = len(peers_list)
        offline_count = max(0, total - online_count)
        customers_with_peers = len({p['customer']['id'] for p in peers_list if p['customer']})

        stats = {
            'total': total,
            'online': online_count,
            'offline': offline_count,
            'customers_count': customers_with_peers,
            'online_pct': round((online_count / total * 100) if total > 0 else 0)
        }

        unique_customers = []
        seen_cids = set()
        for p in peers_list:
            if p['customer'] and p['customer']['id'] not in seen_cids:
                seen_cids.add(p['customer']['id'])
                unique_customers.append(p['customer'])
        unique_customers.sort(key=lambda c: (c['name'] or '').lower())

        return {
            'peers': peers_list,
            'stats': stats,
            'customers': unique_customers
        }

    @classmethod
    def get_peer_detail(cls, db: Session, peer_id: str) -> Dict[str, Any]:
        """
        Retrieves detailed metadata for a single peer, including live handshake,
        customer assignment, and associated routes.
        """
        base_url = get_api_base_url()
        headers = get_api_headers()

        resp = requests.get(f"{base_url}/api/v2/netbird/peers/{peer_id}", headers=headers, timeout=5)
        if resp.status_code == 404 or not resp.ok:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Peer not found")
        raw_peer = resp.json()

        hs = check_single_peer_handshake(raw_peer, base_url, headers)
        is_online = bool(hs.get('is_online'))
        is_reachable = bool(hs.get('is_reachable'))

        customer_data = None
        gp = db.query(GroupPeer).filter(GroupPeer.peer_id == peer_id).first()
        if gp:
            client = db.query(Client).filter(Client.netbird_group_id == gp.group_id).first()
            if client:
                plan_name = 'Standard'
                if getattr(client, 'plan', None) and getattr(client.plan, 'name', None):
                    plan_name = client.plan.name
                elif getattr(client, 'subscription', None):
                    plan_name = client.subscription

                customer_data = {
                    'id': str(client.user_id),
                    'name': client.client_name or client.username or 'Customer',
                    'username': client.username or '',
                    'company': client.client_company_name or '',
                    'email': client.client_email or '',
                    'plan': plan_name
                }

        peer_routes = []
        try:
            r_resp = requests.get(f"{base_url}/api/v2/netbird/routes", headers=headers, timeout=5)
            if r_resp.ok:
                for r in r_resp.json():
                    if r.get('peer_id') == peer_id or r.get('peer') == peer_id:
                        peer_routes.append(r)
        except Exception as e:
            logger.warning(f"Could not load routes for peer {peer_id}: {e}")

        formatted_peer = {
            'id': peer_id,
            'name': hs.get('name') or raw_peer.get('name') or 'Unnamed peer',
            'hostname': raw_peer.get('hostname') or hs.get('name') or '',
            'ip': hs.get('ip') or raw_peer.get('ip') or '—',
            'connection_ip': hs.get('connection_ip') or raw_peer.get('connection_ip') or '—',
            'connected': bool(hs.get('connected', False)),
            'is_reachable': is_reachable,
            'is_online': is_online,
            'status_label': 'Online' if is_online else ('Unreachable' if hs.get('connected') else 'Offline'),
            'last_seen': raw_peer.get('last_seen') or hs.get('last_seen') or '',
            'os': raw_peer.get('os') or '',
            'version': raw_peer.get('version') or '',
            'vpn_only': bool(hs.get('vpn_only', False)),
            'customer': customer_data
        }

        return {
            'success': True,
            'peer': formatted_peer,
            'routes': peer_routes
        }

    @classmethod
    def delete_peer(cls, db: Session, peer_id: str) -> Dict[str, Any]:
        """
        Safely deletes a peer:
        1. Calls uninstall on device agent (best-effort).
        2. Deletes associated NetBird network routes.
        3. Deletes peer from NetBird.
        4. Cleans up GroupPeer DB mapping and NetBird caches.
        """
        headers = get_api_headers()
        base_url = get_api_base_url()

        # Step 0: Get peer IP for agent uninstall
        peer_ip = None
        try:
            p_resp = requests.get(f"{base_url}/api/v2/netbird/peers/{peer_id}", headers=headers, timeout=5)
            if p_resp.ok:
                peer_ip = p_resp.json().get('ip')
        except Exception:
            pass

        if peer_ip:
            try:
                requests.post(f"http://{peer_ip}:8765/uninstall", timeout=(1, 3))
            except Exception as agent_err:
                logger.info(f"Agent uninstall skipped/failed for {peer_ip}: {agent_err}")

        # Step 1: Delete associated routes
        try:
            r_resp = requests.get(f"{base_url}/api/v2/netbird/routes", headers=headers, timeout=5)
            if r_resp.ok:
                for route in r_resp.json():
                    if route.get('peer_id') == peer_id or route.get('peer') == peer_id:
                        route_id = route.get('id')
                        if route_id:
                            del_r = requests.delete(f"{base_url}/api/v2/netbird/routes/{route_id}", headers=headers, timeout=5)
                            if not del_r.ok:
                                logger.warning(f"Failed to delete route {route_id}: {del_r.text}")
        except Exception as route_err:
            logger.warning(f"Error querying routes during peer deletion: {route_err}")

        # Step 2: Delete peer from NetBird
        del_res = requests.delete(f"{base_url}/api/v2/netbird/peers/{peer_id}", headers=headers, timeout=5)
        if not (del_res.ok or del_res.status_code == 204 or del_res.status_code == 404):
            raise HTTPException(
                status_code=del_res.status_code,
                detail=f"Failed to delete peer from NetBird: {del_res.text}"
            )

        # Step 3: Remove DB records and clear cache
        try:
            db.query(GroupPeer).filter(GroupPeer.peer_id == peer_id).delete()
            db.commit()
        except Exception as db_err:
            db.rollback()
            logger.error(f"Error deleting GroupPeer for {peer_id}: {db_err}")

        try:
            clear_all_netbird_caches()
        except Exception as c_err:
            logger.warning(f"Error clearing netbird cache: {c_err}")

        return {
            'success': True,
            'message': 'Peer deleted'
        }

    @classmethod
    def reconnect_peer(cls, db: Session, peer_id: str) -> Dict[str, Any]:
        """
        Triggers live handshake check and revalidates peer reachability.
        """
        headers = get_api_headers()
        base_url = get_api_base_url()

        p_resp = requests.get(f"{base_url}/api/v2/netbird/peers/{peer_id}", headers=headers, timeout=5)
        if p_resp.status_code == 404 or not p_resp.ok:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Peer not found")

        hs = check_single_peer_handshake(p_resp.json(), base_url, headers)
        is_online = bool(hs.get('is_online'))
        is_reachable = bool(hs.get('is_reachable'))

        return {
            'success': True,
            'peer_id': peer_id,
            'is_online': is_online,
            'is_reachable': is_reachable,
            'message': 'Peer reconnected' if is_online else 'Connection checked'
        }
