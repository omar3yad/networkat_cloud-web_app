import requests
import os
from fastapi_app.schemas.netbird.tokens import NetBirdTokenCreate

class NetBirdTokenService:
    
    @staticmethod
    def _get_headers_and_base_url() -> tuple[str, dict]:
        """دالة مساعدة لتوحيد الرابط والـ Headers"""
        base_url = os.getenv("NETBIRD_API_URL", "http://netbird-server/api")
        token = os.getenv("NETBIRD_TOKEN")
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {token}'
        }
        return base_url, headers

    @staticmethod
    def list_tokens(user_id: str):
        base_url, headers = NetBirdTokenService._get_headers_and_base_url()
        url = f"{base_url}/users/{user_id}/tokens"
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError:
            return {"error": True, "status_code": response.status_code, "detail": response.text}
        except requests.exceptions.RequestException as e:
            return {"error": True, "status_code": 500, "detail": str(e)}

    @staticmethod
    def create_token(user_id: str, token_data: NetBirdTokenCreate):
        base_url, headers = NetBirdTokenService._get_headers_and_base_url()
        url = f"{base_url}/users/{user_id}/tokens"
        headers['Content-Type'] = 'application/json'
        
        payload = token_data.model_dump(exclude_none=True)
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError:
            return {"error": True, "status_code": response.status_code, "detail": response.text}
        except requests.exceptions.RequestException as e:
            return {"error": True, "status_code": 500, "detail": str(e)}

    @staticmethod
    def get_token(user_id: str, token_id: str):
        base_url, headers = NetBirdTokenService._get_headers_and_base_url()
        url = f"{base_url}/users/{user_id}/tokens/{token_id}"
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError:
            return {"error": True, "status_code": response.status_code, "detail": response.text}
        except requests.exceptions.RequestException as e:
            return {"error": True, "status_code": 500, "detail": str(e)}

    @staticmethod
    def delete_token(user_id: str, token_id: str):
        base_url, headers = NetBirdTokenService._get_headers_and_base_url()
        url = f"{base_url}/users/{user_id}/tokens/{token_id}"
        
        try:
            response = requests.delete(url, headers=headers, timeout=10)
            response.raise_for_status()
            return {"success": True} if response.status_code in [200, 204] else response.json()
        except requests.exceptions.HTTPError:
            return {"error": True, "status_code": response.status_code, "detail": response.text}
        except requests.exceptions.RequestException as e:
            return {"error": True, "status_code": 500, "detail": str(e)}