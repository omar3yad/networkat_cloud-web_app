# fastapi_app/services/netbird/groups.py
import os
import requests
from typing import Optional
from fastapi_app.schemas.netbird.groups import NetBirdGroupCreate

class NetBirdService:
    @staticmethod
    def _get_headers_and_url() -> tuple[str, dict]:
        """دالة مساعدة لتوحيد الرابط والـ Headers الآمنة في كل العمليات"""
        base_url = os.getenv("NETBIRD_API_URL", "http://netbird-server/api")
        token = os.getenv("NETBIRD_TOKEN")
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {token}'
        }
        return f"{base_url}/groups", headers

    @staticmethod
    def create_group(group_data: NetBirdGroupCreate):
        # قراءة الإعدادات ديناميكياً من البيئة مع وضع قيم افتراضية احتياطية
        base_url = os.getenv("NETBIRD_API_URL", "http://netbird-server/api")
        token = os.getenv("NETBIRD_TOKEN")
        
        url = f"{base_url}/groups"
        
        # التوثيق باستخدام Bearer الذي أثبت نجاحه مع السيرفر الداخلي
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {token}'
        }
        
        payload = group_data.model_dump(exclude_none=True)
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            return {"error": True, "status_code": response.status_code, "detail": response.text}
        except requests.exceptions.RequestException as e:
            return {"error": True, "status_code": 500, "detail": str(e)}

    @staticmethod
    def get_groups(name: Optional[str] = None):
        base_url = os.getenv("NETBIRD_API_URL", "http://netbird-server/api")
        token = os.getenv("NETBIRD_TOKEN")
        
        url = f"{base_url}/groups"
        
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {token}'
        }
        
        # إضافة باراميتر الفلترة بالـ name لو المستخدم باعتها
        params = {}
        if name:
            params['name'] = name
            
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            return {"error": True, "status_code": response.status_code, "detail": response.text}
        except requests.exceptions.RequestException as e:
            return {"error": True, "status_code": 500, "detail": str(e)}

    @staticmethod
    def get_group_by_id(group_id: str):
        base_url, headers = NetBirdService._get_headers_and_url()
        url = f"{base_url}/{group_id}"
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError:
            return {"error": True, "status_code": response.status_code, "detail": response.text}
        except requests.exceptions.RequestException as e:
            return {"error": True, "status_code": 500, "detail": str(e)}

    @staticmethod
    def update_group(group_id: str, group_data: NetBirdGroupCreate):
        base_url, headers = NetBirdService._get_headers_and_url()
        url = f"{base_url}/{group_id}"
        headers['Content-Type'] = 'application/json'
        payload = group_data.model_dump(exclude_none=True)
        
        try:
            response = requests.put(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError:
            return {"error": True, "status_code": response.status_code, "detail": response.text}
        except requests.exceptions.RequestException as e:
            return {"error": True, "status_code": 500, "detail": str(e)}

    @staticmethod
    def delete_group(group_id: str):
        base_url, headers = NetBirdService._get_headers_and_url()
        url = f"{base_url}/{group_id}"
        
        try:
            response = requests.delete(url, headers=headers, timeout=10)
            response.raise_for_status()
            return {"success": True} if response.status_code in [200, 204] else response.json()
        except requests.exceptions.HTTPError:
            return {"error": True, "status_code": response.status_code, "detail": response.text}
        except requests.exceptions.RequestException as e:
            return {"error": True, "status_code": 500, "detail": str(e)}