import requests
import os
from typing import Optional
from fastapi_app.schemas.netbird.users import (
    NetBirdUserCreate, NetBirdUserUpdate, ChangePasswordRequest,
    InviteCreateRequest, InviteRegenerateRequest, AcceptInviteRequest
)

class NetBirdUserService:
    
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

    # --- Core User Methods ---
    @staticmethod
    def list_users(service_user: Optional[bool] = None):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        params = {"service_user": service_user} if service_user is not None else {}
        response = requests.get(f"{base_url}/users", headers=headers, params=params, timeout=10)
        return NetBirdUserService._handle_response(response)

    @staticmethod
    def create_user(payload: NetBirdUserCreate):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        headers['Content-Type'] = 'application/json'
        response = requests.post(f"{base_url}/users", headers=headers, json=payload.model_dump(exclude_none=True), timeout=10)
        return NetBirdUserService._handle_response(response)

    @staticmethod
    def get_current_user():
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        response = requests.get(f"{base_url}/users/current", headers=headers, timeout=10)
        return NetBirdUserService._handle_response(response)

    @staticmethod
    def update_user(user_id: str, payload: NetBirdUserUpdate):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        headers['Content-Type'] = 'application/json'
        response = requests.put(f"{base_url}/users/{user_id}", headers=headers, json=payload.model_dump(), timeout=10)
        return NetBirdUserService._handle_response(response)

    @staticmethod
    def delete_user(user_id: str):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        response = requests.delete(f"{base_url}/users/{user_id}", headers=headers, timeout=10)
        return NetBirdUserService._handle_response(response, check_empty=True)

    @staticmethod
    def resend_invite(user_id: str):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        response = requests.post(f"{base_url}/users/{user_id}/invite", headers=headers, timeout=10)
        return NetBirdUserService._handle_response(response, check_empty=True)

    @staticmethod
    def approve_user(user_id: str):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        response = requests.post(f"{base_url}/users/{user_id}/approve", headers=headers, timeout=10)
        return NetBirdUserService._handle_response(response)

    @staticmethod
    def reject_user(user_id: str):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        response = requests.delete(f"{base_url}/users/{user_id}/reject", headers=headers, timeout=10)
        return NetBirdUserService._handle_response(response, check_empty=True)

    @staticmethod
    def change_password(user_id: str, payload: ChangePasswordRequest):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        headers['Content-Type'] = 'application/json'
        response = requests.put(f"{base_url}/users/{user_id}/password", headers=headers, json=payload.model_dump(), timeout=10)
        return NetBirdUserService._handle_response(response, check_empty=True)

    # --- Invites Methods ---
    @staticmethod
    def list_invites():
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        response = requests.get(f"{base_url}/users/invites", headers=headers, timeout=10)
        return NetBirdUserService._handle_response(response)

    @staticmethod
    def create_invite(payload: InviteCreateRequest):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        headers['Content-Type'] = 'application/json'
        response = requests.post(f"{base_url}/users/invites", headers=headers, json=payload.model_dump(exclude_none=True), timeout=10)
        return NetBirdUserService._handle_response(response)

    @staticmethod
    def delete_invite(invite_id: str):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        response = requests.delete(f"{base_url}/users/invites/{invite_id}", headers=headers, timeout=10)
        return NetBirdUserService._handle_response(response, check_empty=True)

    @staticmethod
    def regenerate_invite(invite_id: str, payload: InviteRegenerateRequest):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        headers['Content-Type'] = 'application/json'
        response = requests.post(f"{base_url}/users/invites/{invite_id}/regenerate", headers=headers, json=payload.model_dump(exclude_none=True), timeout=10)
        return NetBirdUserService._handle_response(response)

    @staticmethod
    def get_invite_info(token: str):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        response = requests.get(f"{base_url}/users/invites/{token}", headers=headers, timeout=10)
        return NetBirdUserService._handle_response(response)

    @staticmethod
    def accept_invite(token: str, payload: AcceptInviteRequest):
        base_url, headers = NetBirdUserService._get_headers_and_base_url()
        headers['Content-Type'] = 'application/json'
        response = requests.post(f"{base_url}/users/invites/{token}/accept", headers=headers, json=payload.model_dump(), timeout=10)
        return NetBirdUserService._handle_response(response, check_empty=True)