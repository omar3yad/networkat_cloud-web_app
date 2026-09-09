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


def _is_offline_ge_7d(last_seen_val, is_connected):
    if is_connected:
        return False
    if not last_seen_val:
        return True
    try:
        if isinstance(last_seen_val, str):
            clean_str = last_seen_val.replace('Z', '+00:00')
            dt = datetime.datetime.fromisoformat(clean_str)
        elif isinstance(last_seen_val, datetime.datetime):
            dt = last_seen_val
        else:
            return True
        now = datetime.datetime.now(datetime.timezone.utc) if dt.tzinfo else datetime.datetime.utcnow()
        diff = now - dt
        return diff.total_seconds() >= (7 * 86400)
    except Exception:
        return False


def inject_client_sidebar():
    customer_id = session.get('client_customer_id')
    if not customer_id:
        return dict(sidebar_peers=[], sidebar_online_count=0, sidebar_offline_count=0)

    customer = Client.query.get(customer_id)
    if not customer:
        return dict(sidebar_peers=[], sidebar_online_count=0, sidebar_offline_count=0)

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
                offline_ge_7d = _is_offline_ge_7d(p.get("last_seen"), is_connected)
                sidebar_peers.append({
                    "id": peer_id,
                    "name": pname,
                    "connected": is_connected,
                    "ip": p.get("ip"),
                    "last_seen": p.get("last_seen"),
                    "offline_duration": offline_dur,
                    "offline_ge_7d": offline_ge_7d,
                    "last_seen_human": f"{offline_dur} ago" if offline_dur else "",
                    "status_title": f"Offline for {offline_dur}" if offline_dur else ("Connected" if is_connected else "Offline")
                })
            sidebar_peers.sort(key=lambda p: (p.get("name") or "").lower())
            sidebar_online_count = sum(1 for p in sidebar_peers if p.get("connected"))
            sidebar_offline_count = len(sidebar_peers) - sidebar_online_count
            return dict(
                sidebar_peers=sidebar_peers,
                sidebar_online_count=sidebar_online_count,
                sidebar_offline_count=sidebar_offline_count
            )

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
            offline_ge_7d = _is_offline_ge_7d(p.get("last_seen"), is_connected)
            sidebar_peers.append({
                "id": peer_id,
                "name": pname,
                "connected": is_connected,
                "ip": p.get("ip"),
                "last_seen": p.get("last_seen"),
                "offline_duration": offline_dur,
                "offline_ge_7d": offline_ge_7d,
                "last_seen_human": f"{offline_dur} ago" if offline_dur else "",
                "status_title": f"Offline for {offline_dur}" if offline_dur else ("Connected" if is_connected else "Offline")
            })

        sidebar_peers.sort(key=lambda p: (p.get("name") or "").lower())
        sidebar_online_count = sum(1 for p in sidebar_peers if p.get("connected"))
        sidebar_offline_count = len(sidebar_peers) - sidebar_online_count
        return dict(
            sidebar_peers=sidebar_peers,
            sidebar_online_count=sidebar_online_count,
            sidebar_offline_count=sidebar_offline_count
        )
    except Exception as e:
        current_app.logger.error(f"Error in sidebar context processor: {e}")
        return dict(sidebar_peers=[], sidebar_online_count=0, sidebar_offline_count=0)


def inject_subscription_context():
    customer_id = session.get('client_customer_id') or session.get('client_user_id')
    if not customer_id:
        return dict(
            subscription_info={},
            subscription_banner=None,
            is_readonly_subscription=False
        )

    try:
        from models.client import Client
        from services.subscription_service import SubscriptionService

        customer = Client.query.get(customer_id)
        if not customer:
            return dict(
                subscription_info={},
                subscription_banner=None,
                is_readonly_subscription=False
            )

        sub_service = SubscriptionService()
        sub_info = sub_service.get_subscription_info(customer)
        status = customer.subscription_status

        # Create alert banner for non-active states
        banner = None
        if status == 'grace_period':
            days_msg = "A grace period is active."
            if customer.grace_expires_at:
                now_utc = datetime.datetime.utcnow()
                exp = customer.grace_expires_at.replace(tzinfo=None) if customer.grace_expires_at.tzinfo else customer.grace_expires_at
                days_rem = max(0, (exp - now_utc).days)
                days_msg = f"{days_rem} day(s) remaining in grace period."
            banner = {
                "type": "warning",
                "icon": "fas fa-exclamation-triangle",
                "title": "Subscription Expired — Grace Period Active",
                "message": f"Your plan has expired. {days_msg} Full control is temporarily maintained. Please renew soon.",
                "status": "grace_period"
            }
        elif status == 'limit_control':
            banner = {
                "type": "danger",
                "icon": "fas fa-lock",
                "title": "Account Restricted — Read-Only Mode",
                "message": "Your subscription is expired and grace period ended. Modifying rules, routes, and adding peers are locked.",
                "status": "limit_control"
            }
        elif status == 'inactive':
            banner = {
                "type": "critical",
                "icon": "fas fa-ban",
                "title": "Subscription Inactive — Mesh Disconnected",
                "message": "Your subscription is inactive. Peer mesh connectivity and controller access are disabled.",
                "status": "inactive"
            }

        is_readonly = (status in ('limit_control', 'inactive'))

        return dict(
            subscription_info=sub_info,
            subscription_banner=banner,
            is_readonly_subscription=is_readonly
        )
    except Exception as exc:
        logger.error(f"Error in subscription context processor: {exc}")
        return dict(
            subscription_info={},
            subscription_banner=None,
            is_readonly_subscription=False
        )

