import os
import time
import json
import glob
from threading import Lock

# Global Threading Locks
cache_lock = Lock()
status_cache_lock = Lock()
firewall_cache_lock = Lock()
overrides_lock = Lock()

# In-Memory Cache Dictionaries
customer_groups_cache = {}        # { customer_id: (peer_ids_set, timestamp) }
firewall_rules_cache = {}         # { peer_id: (live_rules, agent_online, timestamp) }
firewall_revalidating = set()     # set of peer_ids currently revalidating in background
vpn_only_cache = {}               # { peer_id: (enabled_bool, timestamp) }


def read_file_cache(cache_key: str):
    """Reads a shared cache file from /tmp/ and returns its parsed JSON payload and timestamp."""
    path = f"/tmp/nbcache_{cache_key}.json"
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
                return data.get("payload"), data.get("timestamp", 0)
    except Exception:
        pass
    return None, 0


def write_file_cache(cache_key: str, payload):
    """Writes a shared cache payload to a JSON file in /tmp/ atomically."""
    path = f"/tmp/nbcache_{cache_key}.json"
    temp_path = f"{path}.tmp"
    try:
        data = {
            "payload": payload,
            "timestamp": time.time()
        }
        with open(temp_path, 'w') as f:
            json.dump(data, f)
        os.replace(temp_path, path)
    except Exception:
        pass


def is_revalidating(customer_id) -> bool:
    path = f"/tmp/nbstatus_reval_{customer_id}"
    try:
        if os.path.exists(path):
            # If it's less than 15 seconds old, assume it's still running
            if time.time() - os.path.getmtime(path) < 15:
                return True
    except Exception:
        pass
    return False


def start_revalidating(customer_id):
    path = f"/tmp/nbstatus_reval_{customer_id}"
    try:
        with open(path, 'w') as f:
            f.write(str(time.time()))
    except Exception:
        pass


def stop_revalidating(customer_id):
    path = f"/tmp/nbstatus_reval_{customer_id}"
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def get_name_override(peer_id: str):
    path = f"/tmp/peer_name_{peer_id}.json"
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
                name, ts = data[0], data[1]
                if time.time() - ts < 45:
                    return name
                else:
                    try:
                        os.remove(path)
                    except Exception:
                        pass
    except Exception:
        pass
    return None


def set_name_override(peer_id: str, name: str):
    path = f"/tmp/peer_name_{peer_id}.json"
    try:
        with open(path, 'w') as f:
            json.dump([name, time.time()], f)
    except Exception:
        pass


def get_route_override(peer_id: str):
    path = f"/tmp/peer_route_{peer_id}.json"
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
                route, ts = data[0], data[1]
                if time.time() - ts < 45:
                    return route
                else:
                    try:
                        os.remove(path)
                    except Exception:
                        pass
    except Exception:
        pass
    return None


def set_route_override(peer_id: str, route: str):
    path = f"/tmp/peer_route_{peer_id}.json"
    try:
        with open(path, 'w') as f:
            json.dump([route, time.time()], f)
    except Exception:
        pass


def get_active_route_overrides() -> dict:
    overrides = {}
    now = time.time()
    for filepath in glob.glob("/tmp/peer_route_*.json"):
        try:
            filename = os.path.basename(filepath)
            peer_id = filename[len("peer_route_"):-len(".json")]
            with open(filepath, 'r') as f:
                data = json.load(f)
                route, ts = data[0], data[1]
                if now - ts < 45:
                    overrides[peer_id] = route
                else:
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
        except Exception:
            pass
    return overrides


def clear_all_netbird_caches(customer_id=None):
    # Remove shared cache files
    for key in ["netbird_peers", "netbird_routes"]:
        path = f"/tmp/nbcache_{key}.json"
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    if customer_id:
        path = f"/tmp/nbcache_customer_status_{customer_id}.json"
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
