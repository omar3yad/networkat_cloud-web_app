# /opt/networkat_sdwan/core/web_app/fastapi_app/routes/adguard/dns.py
from typing import Optional
from fastapi import APIRouter, Query
from fastapi_app.schemas.adguard import BlockedServicesRequest

from fastapi_app.schemas.adguard import (
    DNSRewriteRule,
    FilteringRulesRequest,
    ProtectionToggleRequest,
)
from fastapi_app.services.adguard.adguard_service import AdGuardService

router = APIRouter(
    prefix="/api/v1/peers/{peer_id}/adguard",
    tags=["AdGuard DNS Control"],
)


@router.get("/status")
async def get_adguard_status(peer_id: str):
    return await AdGuardService.get_status(peer_id)


@router.post("/protection")
async def toggle_protection(
    peer_id: str,
    payload: ProtectionToggleRequest,
):
    return await AdGuardService.toggle_protection(
        peer_id, enabled=payload.enabled, duration=payload.duration
    )


@router.get("/stats")
async def get_adguard_stats(peer_id: str):
    return await AdGuardService.get_stats(peer_id)


@router.get("/querylog")
async def get_query_logs(
    peer_id: str,
    limit: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None),
):
    return await AdGuardService.get_querylog(peer_id, limit=limit, search=search)


@router.get("/rewrites")
async def list_dns_rewrites(peer_id: str):
    return await AdGuardService.get_rewrites(peer_id)


@router.post("/rewrites")
async def add_dns_rewrite(
    peer_id: str,
    payload: DNSRewriteRule,
):
    return await AdGuardService.add_rewrite(
        peer_id, domain=payload.domain, answer=payload.answer
    )


@router.delete("/rewrites")
async def delete_dns_rewrite(
    peer_id: str,
    payload: DNSRewriteRule,
):
    return await AdGuardService.delete_rewrite(
        peer_id, domain=payload.domain, answer=payload.answer
    )


@router.get("/filtering")
async def get_filtering_rules(peer_id: str):
    return await AdGuardService.get_filtering(peer_id)


@router.post("/filtering/rules")
async def set_user_rules(
    peer_id: str,
    payload: FilteringRulesRequest,
):
    return await AdGuardService.set_user_rules(peer_id, rules=payload.rules)
# /opt/networkat_sdwan/core/web_app/fastapi_app/routes/adguard/dns.py

@router.get("/blocked_services")
async def get_blocked_services(peer_id: str):
    return await AdGuardService.get_blocked_services(peer_id)

@router.post("/blocked_services")
@router.put("/blocked_services")
async def set_blocked_services(
    peer_id: str,
    payload: BlockedServicesRequest,
):
    return await AdGuardService.set_blocked_services(peer_id, ids=payload.ids)

@router.get("/clients/{client_name}/blocked_services")
async def get_client_blocked_services(peer_id: str, client_name: str):
    return await AdGuardService.get_client_blocked_services(peer_id, client_name)

@router.post("/clients/{client_name}/blocked_services")
@router.put("/clients/{client_name}/blocked_services")
async def set_client_blocked_services(
    peer_id: str,
    client_name: str,
    payload: BlockedServicesRequest,
):
    return await AdGuardService.set_client_blocked_services(peer_id, client_name, ids=payload.ids)

@router.get("/dns_info")
async def get_adguard_dns_info(peer_id: str):
    return await AdGuardService.get_dns_info(peer_id)

@router.post("/dns_config")
async def set_adguard_dns_config(peer_id: str, payload: dict):
    return await AdGuardService.set_dns_config(peer_id, payload)