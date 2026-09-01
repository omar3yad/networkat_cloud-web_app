import requests
import os
from fastapi_app.schemas.netbird.routes import NetBirdRouteCreateUpdate

class NetBirdRouteService:
    
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
    def list_routes():
        base_url, headers = NetBirdRouteService._get_headers_and_base_url()
        response = requests.get(f"{base_url}/routes", headers=headers, timeout=10)
        return NetBirdRouteService._handle_response(response)

    @staticmethod
    def create_route(payload: NetBirdRouteCreateUpdate):
        base_url, headers = NetBirdRouteService._get_headers_and_base_url()
        headers['Content-Type'] = 'application/json'
        
        response = requests.post(
            f"{base_url}/routes", 
            headers=headers, 
            json=payload.model_dump(exclude_none=True), 
            timeout=10
        )
        return NetBirdRouteService._handle_response(response)

    @staticmethod
    def get_route(route_id: str):
        base_url, headers = NetBirdRouteService._get_headers_and_base_url()
        response = requests.get(f"{base_url}/routes/{route_id}", headers=headers, timeout=10)
        return NetBirdRouteService._handle_response(response)

    @staticmethod
    def update_route(route_id: str, payload: NetBirdRouteCreateUpdate):
        base_url, headers = NetBirdRouteService._get_headers_and_base_url()
        headers['Content-Type'] = 'application/json'
        
        response = requests.put(
            f"{base_url}/routes/{route_id}", 
            headers=headers, 
            json=payload.model_dump(exclude_none=True), 
            timeout=10
        )
        return NetBirdRouteService._handle_response(response)

    @staticmethod
    def delete_route(route_id: str):
        base_url, headers = NetBirdRouteService._get_headers_and_base_url()
        response = requests.delete(f"{base_url}/routes/{route_id}", headers=headers, timeout=10)
        return NetBirdRouteService._handle_response(response, check_empty=True)