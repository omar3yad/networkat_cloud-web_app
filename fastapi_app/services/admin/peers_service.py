# /opt/networkat_sdwan/core/web_app/fastapi_app/services/admin/peers_service.py
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Any
from sqlalchemy.orm import Session

from models.client import Client
from models.group_peer import GroupPeer
from services.netbird_service import (
    get_cached_all_netbird_peers,
    check_single_peer_handshake,
    get_api_base_url,
    get_api_headers,
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
