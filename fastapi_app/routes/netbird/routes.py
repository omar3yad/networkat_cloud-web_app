# /opt/networkat_sdwan/core/web_app/fastapi_app/routes/netbird/routes.py
from fastapi import APIRouter, HTTPException, status
from typing import List
from fastapi_app.schemas.netbird.routes import NetBirdRouteResponse, NetBirdRouteCreateUpdate
from fastapi_app.services.netbird.routes import NetBirdRouteService
router = APIRouter(prefix="/api/v2/netbird/routes", tags=["NetBird Routes"])

def handle_result(result):
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=result["status_code"], detail=f"NetBird Error: {result['detail']}")
    return result

@router.get("", response_model=List[NetBirdRouteResponse])
def list_routes():
    return handle_result(NetBirdRouteService.list_routes())

@router.post("", response_model=NetBirdRouteResponse, status_code=status.HTTP_201_CREATED)
def create_route(payload: NetBirdRouteCreateUpdate):
    return handle_result(NetBirdRouteService.create_route(payload))

@router.get("/{route_id}", response_model=NetBirdRouteResponse)
def retrieve_route(route_id: str):
    return handle_result(NetBirdRouteService.get_route(route_id))

@router.put("/{route_id}", response_model=NetBirdRouteResponse)
def update_route(route_id: str, payload: NetBirdRouteCreateUpdate):
    return handle_result(NetBirdRouteService.update_route(route_id, payload))

@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(route_id: str):
    result = NetBirdRouteService.delete_route(route_id)
    handle_result(result)
    return