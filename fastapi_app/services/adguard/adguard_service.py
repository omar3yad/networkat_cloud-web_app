# /opt/networkat_sdwan/core/web_app/fastapi_app/services/adguard/adguard_service.py
import os
from typing import Any, Optional
from fastapi import HTTPException, status
import requests
from starlette.concurrency import run_in_threadpool

from fastapi_app.services.netbird.peers import NetBirdPeerService

ADGUARD_USER = os.getenv("ADGUARD_USER", "admin")
ADGUARD_PASSWORD = os.getenv("ADGUARD_PASSWORD", "adguard-api")
ADGUARD_PORT = int(os.getenv("ADGUARD_PORT", "29300"))
ADGUARD_TIMEOUT = 3.0


class AdGuardService:
    @classmethod
    async def _get_validated_peer_ip(cls, peer_id: str) -> str:
        peer = await run_in_threadpool(NetBirdPeerService.get_peer, peer_id)
        if not peer or (isinstance(peer, dict) and peer.get("error")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Peer not found in NetBird",
            )

        if not peer.get("connected"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Peer is currently offline",
            )

        peer_ip = peer.get("ip")
        if not peer_ip:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Peer has no mesh IP assigned",
            )

        return peer_ip

    @classmethod
    async def _get_adguard_password(cls, peer_id: str, peer_ip: str) -> str:
        from fastapi_app.database import SessionLocal
        from sqlalchemy import text

        # 1. Try to fetch from database
        try:
            with SessionLocal() as session:
                query = text("SELECT adguard_password FROM group_peers WHERE peer_id = :peer_id LIMIT 1")
                result = session.execute(query, {"peer_id": peer_id}).fetchone()
                if result and result[0] and result[0] not in ("default_password", ADGUARD_PASSWORD):
                    return result[0]
        except Exception:
            pass

        # 2. Try to query the peer's agent API
        try:
            url = f"http://{peer_ip}:8765/adguard-credential"
            response = requests.get(url, timeout=3.0)
            if response.status_code == 200:
                try:
                    data = response.json()
                    password = data.get("password") if isinstance(data, dict) else response.text.strip()
                except Exception:
                    password = response.text.strip()

                if password:
                    # Save it back to our DB if table exists (UPDATE only to avoid logical replication conflicts)
                    try:
                        with SessionLocal() as session:
                            update_query = text(
                                "UPDATE group_peers SET adguard_password = :password WHERE peer_id = :peer_id"
                            )
                            session.execute(update_query, {"password": password, "peer_id": peer_id})
                            session.commit()
                    except Exception:
                        pass
                    return password
        except Exception:
            pass

        # 3. Fallback to global ADGUARD_PASSWORD from .env
        return ADGUARD_PASSWORD

    @classmethod
    def _sync_call_adguard_api(
        cls,
        peer_id: str,
        peer_ip: str,
        adguard_password: str,
        endpoint: str,
        method: str = "GET",
        json_data: Optional[dict] = None,
        params: Optional[dict] = None,
        is_retry: bool = False,
    ) -> Any:
        url = f"http://{peer_ip}:{ADGUARD_PORT}/control/{endpoint.lstrip('/')}"
        auth = (ADGUARD_USER, adguard_password)

        try:
            response = requests.request(
                method=method,
                url=url,
                auth=auth,
                json=json_data,
                params=params,
                timeout=ADGUARD_TIMEOUT,
            )
            response.raise_for_status()
            if response.status_code == 204 or not response.content:
                return {"success": True}
            return response.json()
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else 500
            
            # If 401 Unauthorized and we haven't retried yet, query agent for fresh password
            if status_code == 401 and not is_retry:
                try:
                    agent_url = f"http://{peer_ip}:8765/adguard-credential"
                    agent_resp = requests.get(agent_url, timeout=3.0)
                    if agent_resp.status_code == 200:
                        try:
                            data = agent_resp.json()
                            new_password = data.get("password") if isinstance(data, dict) else agent_resp.text.strip()
                        except Exception:
                            new_password = agent_resp.text.strip()
                            
                        if new_password and new_password != adguard_password:
                            # Save new password to DB
                            from fastapi_app.database import SessionLocal
                            from sqlalchemy import text
                            try:
                                with SessionLocal() as session:
                                    update_query = text(
                                        "UPDATE group_peers SET adguard_password = :password WHERE peer_id = :peer_id"
                                    )
                                    session.execute(update_query, {"password": new_password, "peer_id": peer_id})
                                    session.commit()
                            except Exception:
                                pass
                            
                            # Retry the request with the new password
                            return cls._sync_call_adguard_api(
                                peer_id=peer_id,
                                peer_ip=peer_ip,
                                adguard_password=new_password,
                                endpoint=endpoint,
                                method=method,
                                json_data=json_data,
                                params=params,
                                is_retry=True,
                            )
                except Exception:
                    pass

            text_err = exc.response.text if exc.response is not None else str(exc)
            raise HTTPException(
                status_code=status_code,
                detail=f"AdGuard API error: {text_err}",
            )
        except requests.Timeout:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"AdGuard API on peer timed out after {ADGUARD_TIMEOUT}s",
            )
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not connect to AdGuard on peer: {str(exc)}",
            )

    @classmethod
    async def _call_adguard_api(
        cls,
        peer_id: str,
        peer_ip: str,
        adguard_password: str,
        endpoint: str,
        method: str = "GET",
        json_data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> Any:
        return await run_in_threadpool(
            cls._sync_call_adguard_api, peer_id, peer_ip, adguard_password, endpoint, method, json_data, params
        )

    @classmethod
    async def get_status(cls, peer_id: str) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "status")

    @classmethod
    async def toggle_protection(
        cls, peer_id: str, enabled: bool, duration: int = 0
    ) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        payload = {"enabled": enabled, "duration": duration}
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "protection", method="POST", json_data=payload)

    @classmethod
    async def get_stats(cls, peer_id: str) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "stats")

    @classmethod
    async def get_querylog(
        cls, peer_id: str, limit: int = 50, search: Optional[str] = None
    ) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        params = {"limit": limit}
        if search:
            params["search"] = search
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "querylog", params=params)

    @classmethod
    async def get_rewrites(cls, peer_id: str) -> list:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "rewrite/list")

    @classmethod
    async def add_rewrite(
        cls, peer_id: str, domain: str, answer: str
    ) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        payload = {"domain": domain, "answer": answer}
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "rewrite/add", method="POST", json_data=payload)

    @classmethod
    async def delete_rewrite(
        cls, peer_id: str, domain: str, answer: str
    ) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        payload = {"domain": domain, "answer": answer}
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "rewrite/delete", method="POST", json_data=payload)

    @classmethod
    async def get_filtering(cls, peer_id: str) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "filtering/status")

    @classmethod
    async def set_user_rules(
        cls, peer_id: str, rules: list[str]
    ) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        payload = {"rules": rules}
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "filtering/set_rules", method="POST", json_data=payload)

    @classmethod
    async def get_blocked_services(cls, peer_id: str) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "blocked_services/list")

    @classmethod
    async def set_blocked_services(
        cls, peer_id: str, ids: list[str]
    ) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "blocked_services/set", method="POST", json_data=ids)

    @classmethod
    async def get_client_blocked_services(cls, peer_id: str, client_name: str) -> list[str]:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        res = await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "clients")
        clients = (res.get("clients") or []) if isinstance(res, dict) else []
        client = next((c for c in clients if c.get("name") == client_name), None)
        if client:
            return client.get("blocked_services", [])
        return []

    @classmethod
    async def _get_alias_ids(cls, peer_id: str, peer_ip: str, alias_name: str) -> list[str]:
        try:
            agent_url = f"http://{peer_ip}:8765/aliases"
            def do_get():
                return requests.get(agent_url, timeout=5.0)
            resp = await run_in_threadpool(do_get)
            if resp.status_code == 200:
                data = resp.json()
                lists = data.get("lists", [])
                alias = next((l for l in lists if str(l.get("id")) == str(alias_name) or str(l.get("slug")) == str(alias_name)), None)
                if alias:
                    ids = []
                    for item in alias.get("list", []):
                        if item.get("address"):
                            ids.append(item.get("address"))
                        elif item.get("hostname") or item.get("domain"):
                            resolved = item.get("resolved_addresses") or []
                            for ip in resolved:
                                if ip:
                                    ids.append(ip)
                    return ids
        except Exception:
            pass
        return []

    @classmethod
    async def set_client_blocked_services(
        cls, peer_id: str, client_name: str, ids: list[str]
    ) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        res = await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "clients")
        clients = (res.get("clients") or []) if isinstance(res, dict) else []
        client = next((c for c in clients if c.get("name") == client_name), None)
        
        if not client:
            # Client not found in AdGuard Home, let's fetch its IDs from the agent and create it
            alias_ids = await cls._get_alias_ids(peer_id, peer_ip, client_name)
            if not alias_ids:
                raise HTTPException(
                    status_code=404,
                    detail=f"Client '{client_name}' not found in AdGuard Home and could not be synced from Agent."
                )
            
            payload = {
                "name": client_name,
                "ids": alias_ids,
                "use_global_settings": False,
                "filtering_enabled": True,
                "parental_enabled": False,
                "safesearch_enabled": False,
                "use_global_blocked_services": False,
                "blocked_services": ids,
                "upstreams": []
            }
            return await cls._call_adguard_api(
                peer_id, peer_ip, adguard_password, "clients/add", method="POST", json_data=payload
            )
        
        # Prepare client update data based on existing client fields
        client_data = client.copy()
        client_data["blocked_services"] = ids
        client_data["use_global_blocked_services"] = False
        client_data["use_global_settings"] = False
        
        payload = {
            "name": client_name,
            "data": client_data
        }
        return await cls._call_adguard_api(
            peer_id, peer_ip, adguard_password, "clients/update", method="POST", json_data=payload
        )

    @classmethod
    async def get_dns_info(cls, peer_id: str) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "dns_info")

    @classmethod
    async def set_dns_config(cls, peer_id: str, payload: dict) -> dict:
        peer_ip = await cls._get_validated_peer_ip(peer_id)
        adguard_password = await cls._get_adguard_password(peer_id, peer_ip)
        return await cls._call_adguard_api(peer_id, peer_ip, adguard_password, "dns_config", method="POST", json_data=payload)