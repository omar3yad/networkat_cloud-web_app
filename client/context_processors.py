import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import session, current_app
from models import Client
from services.netbird_service import NetBirdService

logger = logging.getLogger(__name__)
_sidebar_executor = ThreadPoolExecutor(max_workers=20)


def inject_client_sidebar():
    customer_id = session.get('client_customer_id')
    if not customer_id:
        return dict(sidebar_peers=[])

    customer = Client.query.get(customer_id)
    if not customer:
        return dict(sidebar_peers=[])

    try:
        allowed_peer_ids = NetBirdService.get_cached_customer_peer_ids(customer)
        base_url = NetBirdService.get_api_base_url()
        headers = NetBirdService.get_api_headers()
        peers_data = NetBirdService.get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
        customer_peers = [p for p in peers_data if p.get("id") in allowed_peer_ids]

        processed_peers = []
        if customer_peers:
            futures = {
                _sidebar_executor.submit(
                    NetBirdService.check_single_peer_handshake,
                    peer, base_url, headers
                ): peer
                for peer in customer_peers
            }
            for future in as_completed(futures, timeout=5):
                try:
                    res = future.result()
                    processed_peers.append(res)
                except Exception as err:
                    current_app.logger.error(f"Peer handshake check error in inject_client_sidebar: {err}")

        sidebar_peers = [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "connected": p.get("is_online", False),
                "ip": p.get("ip")
            }
            for p in processed_peers
        ]
        sidebar_peers.sort(key=lambda p: (p.get("name") or "").lower())
        return dict(sidebar_peers=sidebar_peers)
    except Exception as e:
        current_app.logger.error(f"Error in sidebar context processor: {e}")
        return dict(sidebar_peers=[])
