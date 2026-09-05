import re
import requests
import logging

logger = logging.getLogger(__name__)


class AliasService:
    @staticmethod
    def get_peer_aliases(peer_ip: str) -> tuple:
        """Fetch all alias lists from edge device agent."""
        agent_url = f"http://{peer_ip}:8765/aliases"
        try:
            resp = requests.get(agent_url, timeout=10)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"detail": f"Device agent is offline or unreachable: {e}"}, 503

    @staticmethod
    def create_peer_alias(peer_ip: str, payload: dict) -> tuple:
        """Create an alias list on edge device agent."""
        agent_url = f"http://{peer_ip}:8765/aliases"
        try:
            resp = requests.post(agent_url, json=payload, timeout=10)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"detail": f"Device agent is offline or unreachable: {e}"}, 503

    @staticmethod
    def modify_peer_alias(peer_ip: str, slug: str, method: str, payload: dict = None) -> tuple:
        """Update or delete an alias list on edge device agent."""
        agent_url = f"http://{peer_ip}:8765/aliases/{slug}"
        try:
            if method.upper() == 'PUT':
                resp = requests.put(agent_url, json=payload or {}, timeout=10)
            elif method.upper() == 'PATCH':
                resp = requests.patch(agent_url, json=payload or {}, timeout=10)
            else:
                resp = requests.delete(agent_url, timeout=10)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"detail": f"Device agent is offline or unreachable: {e}"}, 503

    @staticmethod
    def sync_peer_aliases(peer_ip: str) -> tuple:
        """Triggers alias sync on the edge device agent."""
        agent_url = f"http://{peer_ip}:8765/aliases/sync"
        try:
            resp = requests.post(agent_url, timeout=10)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"detail": f"Device agent is offline or unreachable: {e}"}, 503

    @staticmethod
    def get_resolver_config(peer_id: str, base_url: str, headers: dict) -> tuple:
        """Fetches DNS resolver info from AdGuard API."""
        url = f"{base_url}/api/v1/peers/{peer_id}/adguard/dns_info"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"detail": f"AdGuard service is offline or unreachable: {e}"}, 503

    @staticmethod
    def update_resolver_config(peer_id: str, peer_ip: str, base_url: str, headers: dict, data: dict) -> tuple:
        """Updates DNS resolver config in AdGuard and syncs domain forwarding with edge agent."""
        url = f"{base_url}/api/v1/peers/{peer_id}/adguard/dns_config"
        try:
            # 1. Update AdGuard via FastAPI
            resp = requests.post(url, json=data, headers=headers, timeout=10)

            # 2. Extract forwarding config and send to Peer Agent's /dns-forwarding endpoint if peer_ip is available
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

            if peer_ip:
                try:
                    agent_url = f"http://{peer_ip}:8765/dns-forwarding"
                    requests.post(agent_url, json={"forwarding": forwarding_config}, timeout=5)
                except Exception as agent_err:
                    logger.warning(f"Failed to sync forwarding config to peer agent {peer_id}: {agent_err}")

            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"detail": f"AdGuard service is offline or unreachable: {e}"}, 503
