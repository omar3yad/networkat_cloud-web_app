import requests
import logging

logger = logging.getLogger(__name__)


class WebFilterService:
    @staticmethod
    def get_peer_rules(peer_ip: str) -> tuple:
        """Fetches web filter rules from edge device agent."""
        agent_url = f"http://{peer_ip}:8765/web-filter/rules"
        try:
            resp = requests.get(agent_url, timeout=10)
            if resp.ok:
                data = resp.json()
                return {"rules": data.get("rules", []), "agent_online": True}, 200
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"rules": [], "agent_online": False, "error": str(e)}, 200

    @staticmethod
    def add_peer_rule(peer_ip: str, payload: dict) -> tuple:
        """Creates a new web filter rule on edge device agent."""
        agent_url = f"http://{peer_ip}:8765/web-filter/rules"
        try:
            resp = requests.post(agent_url, json=payload, timeout=15)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"error": f"Device agent is offline or unreachable: {e}"}, 503

    @staticmethod
    def update_peer_rule(peer_ip: str, rule_id: str, payload: dict) -> tuple:
        """Updates an existing web filter rule on edge device agent."""
        agent_url = f"http://{peer_ip}:8765/web-filter/rules/{rule_id}"
        try:
            resp = requests.put(agent_url, json=payload, timeout=15)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"error": f"Device agent is offline or unreachable: {e}"}, 503

    @staticmethod
    def remove_peer_rules(peer_ip: str, rule_ids: list) -> tuple:
        """Removes one or more web filter rules from edge device agent."""
        agent_url = f"http://{peer_ip}:8765/web-filter/rules/remove"
        try:
            resp = requests.post(agent_url, json={"ids": rule_ids}, timeout=15)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"error": f"Device agent is offline or unreachable: {e}"}, 503

    @staticmethod
    def enable_peer_rules(peer_ip: str, rule_ids: list) -> tuple:
        """Enables one or more web filter rules on edge device agent."""
        agent_url = f"http://{peer_ip}:8765/web-filter/rules/enable"
        try:
            resp = requests.post(agent_url, json={"ids": rule_ids}, timeout=15)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"error": f"Device agent is offline or unreachable: {e}"}, 503

    @staticmethod
    def disable_peer_rules(peer_ip: str, rule_ids: list) -> tuple:
        """Disables one or more web filter rules on edge device agent."""
        agent_url = f"http://{peer_ip}:8765/web-filter/rules/disable"
        try:
            resp = requests.post(agent_url, json={"ids": rule_ids}, timeout=15)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"error": f"Device agent is offline or unreachable: {e}"}, 503

    @staticmethod
    def reorder_peer_rules(peer_ip: str, items: list) -> tuple:
        """Reorders web filter rules on edge device agent."""
        agent_url = f"http://{peer_ip}:8765/web-filter/rules/reorder"
        try:
            resp = requests.post(agent_url, json={"items": items}, timeout=15)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"error": f"Device agent is offline or unreachable: {e}"}, 503

    @staticmethod
    def get_adguard_blocked_services(peer_id: str, base_url: str, headers: dict) -> tuple:
        """Fetches global AdGuard blocked services for a peer."""
        url = f"{base_url}/api/v1/peers/{peer_id}/adguard/blocked_services"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"detail": f"AdGuard service is offline or unreachable: {e}"}, 503

    @staticmethod
    def update_adguard_blocked_services(peer_id: str, base_url: str, headers: dict, data: dict) -> tuple:
        """Updates global AdGuard blocked services for a peer."""
        url = f"{base_url}/api/v1/peers/{peer_id}/adguard/blocked_services"
        try:
            resp = requests.post(url, json=data, headers=headers, timeout=10)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"detail": f"AdGuard service is offline or unreachable: {e}"}, 503

    @staticmethod
    def get_adguard_client_blocked_services(peer_id: str, client_name: str, base_url: str, headers: dict) -> tuple:
        """Fetches client-specific AdGuard blocked services."""
        url = f"{base_url}/api/v1/peers/{peer_id}/adguard/clients/{client_name}/blocked_services"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"detail": f"AdGuard service is offline or unreachable: {e}"}, 503

    @staticmethod
    def update_adguard_client_blocked_services(peer_id: str, client_name: str, base_url: str, headers: dict, data: dict) -> tuple:
        """Updates client-specific AdGuard blocked services."""
        url = f"{base_url}/api/v1/peers/{peer_id}/adguard/clients/{client_name}/blocked_services"
        try:
            resp = requests.post(url, json=data, headers=headers, timeout=10)
            return resp.text, resp.status_code
        except requests.RequestException as e:
            return {"detail": f"AdGuard service is offline or unreachable: {e}"}, 503
