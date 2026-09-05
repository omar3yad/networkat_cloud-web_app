import time
import requests
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app
from utils.cache_manager import (
    cache_lock,
    customer_groups_cache,
    vpn_only_cache,
    read_file_cache,
    write_file_cache,
    get_name_override,
    is_revalidating,
    start_revalidating,
    stop_revalidating
)

logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=20)

_HANDSHAKE_CACHE = {}  # { peer_id: (is_reachable, timestamp) }


class NetBirdService:
    @staticmethod
    def get_api_base_url() -> str:
        try:
            return current_app.config.get('NETBIRD_API_BASE_URL', 'https://api.networkat.cloud')
        except RuntimeError:
            return 'https://api.networkat.cloud'

    @staticmethod
    def get_api_headers(extra_headers: dict = None) -> dict:
        token = "57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874"
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {token}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ClientApp/1.0'
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    @classmethod
    def get_customer_group_peer_ids(cls, customer) -> set:
        """Return the set of NetBird peer IDs that belong to this customer's group."""
        if not customer or not getattr(customer, 'netbird_group_id', None):
            return set()
        try:
            base_url = cls.get_api_base_url()
            headers = cls.get_api_headers()

            resp = requests.get(
                f"{base_url}/api/v2/netbird/groups/{customer.netbird_group_id}",
                headers=headers,
                timeout=5
            )
            if resp.status_code != 200:
                logger.error(
                    f"NetBird API Group Fetch Failed [Status {resp.status_code}]: {resp.text}"
                )
                return set()

            group_data = resp.json()
            peers = group_data.get("peers") or []
            return {p["id"] for p in peers}
        except Exception as e:
            logger.error(f"Failed to fetch customer peer group: {e}")
            return set()

    @classmethod
    def get_cached_customer_peer_ids(cls, customer) -> set:
        """Fetch allowed peer IDs for a customer with a 60-second cache."""
        if not customer or not getattr(customer, 'netbird_group_id', None):
            return set()

        cid = getattr(customer, 'user_id', getattr(customer, 'customer_id', getattr(customer, 'id', None)))
        now = time.time()

        with cache_lock:
            if cid in customer_groups_cache:
                peer_ids, cached_time = customer_groups_cache[cid]
                if now - cached_time < 60:
                    return peer_ids

        peer_ids = cls.get_customer_group_peer_ids(customer)

        with cache_lock:
            customer_groups_cache[cid] = (peer_ids, now)
        return peer_ids

    @classmethod
    def verify_peer_access(cls, customer, peer_id: str) -> bool:
        """Check if customer has access to the specified peer_id using the cached group."""
        allowed_peers = cls.get_cached_customer_peer_ids(customer)
        return peer_id in allowed_peers

    @classmethod
    def get_cached_all_netbird_peers(cls, base_url: str = None, headers: dict = None, cache_ttl: int = 5) -> list:
        """Fetch all NetBird peers with atomic shared file cache."""
        base_url = base_url or cls.get_api_base_url()
        headers = headers or cls.get_api_headers()
        now = time.time()

        cached_data, cached_time = read_file_cache("netbird_peers")
        if cached_data is not None and (now - cached_time < cache_ttl):
            return cached_data

        try:
            resp = requests.get(f"{base_url}/api/v2/netbird/peers", headers=headers, timeout=5)
            if resp.status_code == 200:
                peers_data = resp.json()
                if isinstance(peers_data, dict):
                    peers_data = [peers_data]
                write_file_cache("netbird_peers", peers_data)
                return peers_data
        except Exception as e:
            logger.error(f"Error fetching netbird peers: {e}")

        return cached_data or []

    @classmethod
    def get_cached_all_netbird_routes(cls, base_url: str = None, headers: dict = None, cache_ttl: int = 10) -> list:
        """Fetch all NetBird routes with atomic shared file cache."""
        base_url = base_url or cls.get_api_base_url()
        headers = headers or cls.get_api_headers()
        now = time.time()

        cached_data, cached_time = read_file_cache("netbird_routes")
        if cached_data is not None and (now - cached_time < cache_ttl):
            return cached_data

        try:
            resp = requests.get(f"{base_url}/api/v2/netbird/routes", headers=headers, timeout=5)
            if resp.status_code == 200:
                routes_data = resp.json()
                write_file_cache("netbird_routes", routes_data)
                return routes_data
        except Exception as e:
            logger.error(f"Error fetching netbird routes: {e}")

        return cached_data or []

    @classmethod
    def get_cached_peer_handshake(cls, peer_id: str, base_url: str = None, headers: dict = None, cache_ttl: int = 4) -> bool:
        """Fetch peer handshake status with in-memory TTL cache."""
        base_url = base_url or cls.get_api_base_url()
        headers = headers or cls.get_api_headers()
        now = time.time()

        with cache_lock:
            if peer_id in _HANDSHAKE_CACHE:
                is_reachable, cached_time = _HANDSHAKE_CACHE[peer_id]
                if now - cached_time < cache_ttl:
                    return is_reachable

        is_reachable = False
        try:
            hs_resp = requests.get(
                f"{base_url}/api/v1/peers/{peer_id}/handshake",
                headers=headers,
                timeout=5.0
            )
            if hs_resp.ok:
                is_reachable = hs_resp.json().get("is_reachable", False)
        except Exception:
            is_reachable = False

        with cache_lock:
            _HANDSHAKE_CACHE[peer_id] = (is_reachable, now)

        return is_reachable

    @classmethod
    def get_cached_peer_vpn_only(cls, peer_id: str, peer_ip: str, cache_ttl: int = 15) -> bool:
        """Fetch peer VPN-only status from edge agent with in-memory TTL cache."""
        now = time.time()

        with cache_lock:
            if peer_id in vpn_only_cache:
                enabled, cached_time = vpn_only_cache[peer_id]
                if now - cached_time < cache_ttl:
                    return enabled

        enabled = False
        try:
            url = f"http://{peer_ip}:8765/vpn-only"
            resp = requests.get(url, timeout=1.5)
            if resp.ok:
                enabled = resp.json().get("enabled", False)
        except Exception:
            enabled = False

        with cache_lock:
            vpn_only_cache[peer_id] = (enabled, now)

        return enabled

    @classmethod
    def check_single_peer_handshake(cls, peer: dict, base_url: str = None, headers: dict = None) -> dict:
        """Computes live connectivity status, handshake and name override for a peer."""
        base_url = base_url or cls.get_api_base_url()
        headers = headers or cls.get_api_headers()

        peer_id = peer.get("id")
        is_connected = peer.get("connected", False)
        is_reachable = False
        vpn_only = False

        if is_connected:
            is_reachable = cls.get_cached_peer_handshake(peer_id, base_url, headers, cache_ttl=60)
            if is_reachable and peer.get("ip"):
                vpn_only = cls.get_cached_peer_vpn_only(peer_id, peer.get("ip"), cache_ttl=60)

        real_online = is_connected and is_reachable
        pname = peer.get("name")
        ov_name = get_name_override(peer_id)
        if ov_name:
            pname = ov_name

        return {
            "id": peer_id,
            "name": pname,
            "connected": is_connected,
            "is_reachable": is_reachable,
            "is_online": real_online,
            "last_seen": peer.get("last_seen"),
            "ip": peer.get("ip"),
            "connection_ip": peer.get("connection_ip"),
            "vpn_only": vpn_only
        }

    @classmethod
    def revalidate_customer_peers_status(cls, customer_id, customer, base_url: str = None, headers: dict = None, allowed_peer_ids: set = None):
        """Asynchronously updates customer status cache in the background."""
        base_url = base_url or cls.get_api_base_url()
        headers = headers or cls.get_api_headers()
        allowed_peer_ids = allowed_peer_ids or cls.get_cached_customer_peer_ids(customer)

        try:
            peers_data = cls.get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
            customer_peers = [p for p in peers_data if p.get("id") in allowed_peer_ids]

            processed_peers = []
            online_count = 0

            if customer_peers:
                futures = {
                    executor.submit(cls.check_single_peer_handshake, peer, base_url, headers): peer
                    for peer in customer_peers
                }
                for future in as_completed(futures, timeout=5):
                    try:
                        res = future.result()
                        processed_peers.append(res)
                        if res["is_online"]:
                            online_count += 1
                    except Exception as err:
                        logger.error(f"Peer check error in background revalidation: {err}")

            processed_peers.sort(key=lambda p: (p.get("name") or "").lower())

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


def clear_all_netbird_caches(customer_id=None):
    """Invalidate customer status cache and netbird cached files."""
    import os
    if customer_id:
        path = f"/tmp/nbcache_customer_status_{customer_id}.json"
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    for name in ["netbird_peers", "netbird_routes"]:
        path = f"/tmp/nbcache_{name}.json"
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


get_api_base_url = NetBirdService.get_api_base_url
get_api_headers = NetBirdService.get_api_headers
get_cached_customer_peer_ids = NetBirdService.get_cached_customer_peer_ids
get_cached_all_netbird_peers = NetBirdService.get_cached_all_netbird_peers
get_cached_all_netbird_routes = NetBirdService.get_cached_all_netbird_routes
get_cached_peer_handshake = NetBirdService.get_cached_peer_handshake
get_cached_peer_vpn_only = NetBirdService.get_cached_peer_vpn_only
check_single_peer_handshake = NetBirdService.check_single_peer_handshake
revalidate_customer_peers_status = NetBirdService.revalidate_customer_peers_status
verify_peer_access = NetBirdService.verify_peer_access

