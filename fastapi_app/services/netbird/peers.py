# /opt/networkat_sdwan/core/web_app/fastapi_app/services/netbird/peers.py
import requests
import os
from typing import Optional
from fastapi_app.schemas.netbird.peers import NetBirdPeerUpdate, TemporaryAccessRequest

class NetBirdPeerService:
    
    @staticmethod
    def _get_headers_and_base_url() -> tuple[str, dict]:
        base_url = os.getenv("NETBIRD_API_URL", "http://netbird-server/api")
        token = os.getenv("NETBIRD_TOKEN")
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {token}'
        }
        return base_url, headers

    @staticmethod
    def _handle_response(response: requests.Response, check_empty: bool = False):
        try:
            response.raise_for_status()
            if check_empty and response.status_code in [200, 204] and not response.text:
                return {"success": True}
            return response.json() if response.text else {"success": True}
        except requests.exceptions.HTTPError:
            return {"error": True, "status_code": response.status_code, "detail": response.text}
        except requests.exceptions.RequestException as e:
            return {"error": True, "status_code": 500, "detail": str(e)}

    @staticmethod
    def list_peers(name: Optional[str] = None, ip: Optional[str] = None):
        base_url, headers = NetBirdPeerService._get_headers_and_base_url()
        params = {}
        if name:
            params["name"] = name
        if ip:
            params["ip"] = ip
            
        response = requests.get(f"{base_url}/peers", headers=headers, params=params, timeout=10)
        return NetBirdPeerService._handle_response(response)

    @staticmethod
    def get_peer(peer_id: str):
        base_url, headers = NetBirdPeerService._get_headers_and_base_url()
        response = requests.get(f"{base_url}/peers/{peer_id}", headers=headers, timeout=10)
        return NetBirdPeerService._handle_response(response)

    @staticmethod
    def update_peer(peer_id: str, payload: NetBirdPeerUpdate):
        base_url, headers = NetBirdPeerService._get_headers_and_base_url()
        headers['Content-Type'] = 'application/json'
        
        response = requests.put(
            f"{base_url}/peers/{peer_id}", 
            headers=headers, 
            json=payload.model_dump(exclude_none=True), 
            timeout=10
        )
        return NetBirdPeerService._handle_response(response)

    @staticmethod
    def delete_peer(peer_id: str):
        base_url, headers = NetBirdPeerService._get_headers_and_base_url()
        response = requests.delete(f"{base_url}/peers/{peer_id}", headers=headers, timeout=10)
        return NetBirdPeerService._handle_response(response, check_empty=True)

    @staticmethod
    def list_accessible_peers(peer_id: str):
        base_url, headers = NetBirdPeerService._get_headers_and_base_url()
        response = requests.get(f"{base_url}/peers/{peer_id}/accessible-peers", headers=headers, timeout=10)
        return NetBirdPeerService._handle_response(response)

    @staticmethod
    def create_temporary_access(peer_id: str, payload: TemporaryAccessRequest):
        base_url, headers = NetBirdPeerService._get_headers_and_base_url()
        headers['Content-Type'] = 'application/json'
        
        response = requests.post(
            f"{base_url}/peers/{peer_id}/temporary-access", 
            headers=headers, 
            json=payload.model_dump(), 
            timeout=10
        )
        return NetBirdPeerService._handle_response(response)