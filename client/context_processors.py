import datetime
import logging
from flask import session, current_app
from models import Client
from services.netbird_service import NetBirdService
from utils.cache_manager import get_name_override, read_file_cache

logger = logging.getLogger(__name__)


def _format_offline_duration(last_seen_val):
    if not last_seen_val:
        return ""
    try:
        if isinstance(last_seen_val, str):
            clean_str = last_seen_val.replace('Z', '+00:00')
            dt = datetime.datetime.fromisoformat(clean_str)
        elif isinstance(last_seen_val, datetime.datetime):
            dt = last_seen_val
        else:
            return ""
        now = datetime.datetime.now(datetime.timezone.utc) if dt.tzinfo else datetime.datetime.utcnow()
        diff = now - dt
        secs = max(0, int(diff.total_seconds()))
        if secs < 60:
            return "1m"
        elif secs < 3600:
            return f"{secs // 60}m"
        elif secs < 86400:
            return f"{secs // 3600}h"
        else:
            return f"{secs // 86400}d"
    except Exception:
        return ""


def inject_client_sidebar():
    customer_id = session.get('client_customer_id')
    if not customer_id:
        return dict(sidebar_peers=[])

    customer = Client.query.get(customer_id)
    if not customer:
        return dict(sidebar_peers=[])

    try:
        # 1. Use the status cache from peer_api if available (contains true is_online handshake check)
        cached_status, _ = read_file_cache(f"customer_status_{customer_id}")
        if cached_status and cached_status.get("peers"):
            sidebar_peers = []
            for p in cached_status.get("peers", []):
                peer_id = p.get("id")
                pname = get_name_override(peer_id) or p.get("name") or "Edge Device"
                is_online = p.get("is_online")
                if is_online is None:
                    is_online = p.get("connected", False)
                is_connected = bool(is_online)
                offline_dur = _format_offline_duration(p.get("last_seen")) if not is_connected else ""
                sidebar_peers.append({
                    "id": peer_id,
                    "name": pname,
                    "connected": is_connected,
                    "ip": p.get("ip"),
                    "last_seen": p.get("last_seen"),
                    "offline_duration": offline_dur,
                    "last_seen_human": f"{offline_dur} ago" if offline_dur else "",
                    "status_title": f"Offline for {offline_dur}" if offline_dur else ("Connected" if is_connected else "Offline")
                })
            sidebar_peers.sort(key=lambda p: (p.get("name") or "").lower())
            return dict(sidebar_peers=sidebar_peers)

        # 2. Fallback to NetBird cached peers list
        allowed_peer_ids = NetBirdService.get_cached_customer_peer_ids(customer)
        base_url = NetBirdService.get_api_base_url()
        headers = NetBirdService.get_api_headers()
        peers_data = NetBirdService.get_cached_all_netbird_peers(base_url, headers, cache_ttl=15)
        customer_peers = [p for p in peers_data if p.get("id") in allowed_peer_ids]

        sidebar_peers = []
        for p in customer_peers:
            peer_id = p.get("id")
            pname = get_name_override(peer_id) or p.get("name") or "Edge Device"
            is_connected = bool(p.get("connected", False))
            offline_dur = _format_offline_duration(p.get("last_seen")) if not is_connected else ""
            sidebar_peers.append({
                "id": peer_id,
                "name": pname,
                "connected": is_connected,
                "ip": p.get("ip"),
                "last_seen": p.get("last_seen"),
                "offline_duration": offline_dur,
                "last_seen_human": f"{offline_dur} ago" if offline_dur else "",
                "status_title": f"Offline for {offline_dur}" if offline_dur else ("Connected" if is_connected else "Offline")
            })

        sidebar_peers.sort(key=lambda p: (p.get("name") or "").lower())
        return dict(sidebar_peers=sidebar_peers)
    except Exception as e:
        current_app.logger.error(f"Error in sidebar context processor: {e}")
        return dict(sidebar_peers=[])
