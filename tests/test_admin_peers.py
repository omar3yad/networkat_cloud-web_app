# /opt/networkat_sdwan/core/web_app/tests/test_admin_peers.py
"""
Unit and integration tests for Phase 2: Peers & Network Management (FastAPI).
Covers:
- Listing peers with aggregate statistics (get_all_peers)
- Retrieving single peer details and associated routes (get_peer)
- Peer reconnection and live handshake checking (reconnect_peer)
- Deleting peers and cascading network cleanup (delete_peer)
- Proper 404 handling for nonexistent peers
"""
from unittest.mock import patch, MagicMock
import pytest
from fastapi import HTTPException
from fastapi_app.database import SessionLocal
from fastapi_app.routes.admin.peers import (
    get_all_peers,
    get_peer,
    delete_peer,
    reconnect_peer,
)
from fastapi_app.services.admin.peers_service import AdminPeersService


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_admin_peers_list_inventory(db_session):
    result = get_all_peers(refresh=False, db=db_session)
    assert result["success"] is True
    assert "peers" in result
    assert "stats" in result
    assert "customers" in result
    assert isinstance(result["peers"], list)
    assert isinstance(result["customers"], list)
    assert "total" in result["stats"]
    assert "online" in result["stats"]
    assert "offline" in result["stats"]


def test_admin_peers_get_nonexistent_returns_404(db_session):
    with pytest.raises(HTTPException) as exc_info:
        get_peer(peer_id="nonexistent-peer-xyz-999", db=db_session)
    assert exc_info.value.status_code == 404
    assert "Peer not found" in exc_info.value.detail


def test_admin_peers_reconnect_nonexistent_returns_404(db_session):
    with pytest.raises(HTTPException) as exc_info:
        reconnect_peer(peer_id="nonexistent-peer-xyz-999", db=db_session)
    assert exc_info.value.status_code == 404
    assert "Peer not found" in exc_info.value.detail


def test_admin_peers_get_detail_mocked(db_session):
    mock_raw_peer = {
        "id": "peer-test-1",
        "name": "Edge Test 1",
        "ip": "100.123.0.10/32",
        "connection_ip": "198.51.100.1",
        "connected": True,
        "os": "Linux",
        "version": "1.2.0",
        "last_seen": "2026-10-08T12:00:00Z"
    }
    mock_hs = {
        "id": "peer-test-1",
        "name": "Edge Test 1",
        "is_online": True,
        "is_reachable": True,
        "connected": True,
        "ip": "100.123.0.10/32",
        "vpn_only": False
    }

    with patch("fastapi_app.services.admin.peers_service.requests.get") as mock_get, \
         patch("fastapi_app.services.admin.peers_service.check_single_peer_handshake", return_value=mock_hs):

        resp_obj = MagicMock()
        resp_obj.status_code = 200
        resp_obj.ok = True
        resp_obj.json.side_effect = [
            mock_raw_peer,  # peer detail
            [{"id": "route-1", "peer_id": "peer-test-1", "network": "192.168.1.0/24"}]  # routes
        ]
        mock_get.return_value = resp_obj

        data = get_peer(peer_id="peer-test-1", db=db_session)
        assert data["success"] is True
        assert data["peer"]["id"] == "peer-test-1"
        assert data["peer"]["name"] == "Edge Test 1"
        assert data["peer"]["is_online"] is True
        assert len(data["routes"]) == 1
        assert data["routes"][0]["id"] == "route-1"


def test_admin_peers_delete_mocked(db_session):
    with patch("fastapi_app.services.admin.peers_service.requests.get") as mock_get, \
         patch("fastapi_app.services.admin.peers_service.requests.post") as mock_post, \
         patch("fastapi_app.services.admin.peers_service.requests.delete") as mock_del:

        # 1. peer IP fetch
        peer_resp = MagicMock()
        peer_resp.ok = True
        peer_resp.json.return_value = {"ip": "100.123.0.10"}

        # 2. routes query
        routes_resp = MagicMock()
        routes_resp.ok = True
        routes_resp.json.return_value = [{"id": "r-10", "peer_id": "peer-test-del"}]

        mock_get.side_effect = [peer_resp, routes_resp]

        # 3. del route and del peer responses
        del_resp = MagicMock()
        del_resp.ok = True
        del_resp.status_code = 200
        mock_del.return_value = del_resp

        res = delete_peer(peer_id="peer-test-del", db=db_session)
        assert res["success"] is True
        assert res["message"] == "Peer deleted"
        assert mock_del.call_count == 2  # route delete + peer delete


def test_admin_peers_reconnect_mocked(db_session):
    mock_raw = {"id": "peer-rec", "name": "Reconn Peer"}
    mock_hs = {"is_online": True, "is_reachable": True}

    with patch("fastapi_app.services.admin.peers_service.requests.get") as mock_get, \
         patch("fastapi_app.services.admin.peers_service.check_single_peer_handshake", return_value=mock_hs):

        p_resp = MagicMock()
        p_resp.ok = True
        p_resp.status_code = 200
        p_resp.json.return_value = mock_raw
        mock_get.return_value = p_resp

        res = reconnect_peer(peer_id="peer-rec", db=db_session)
        assert res["success"] is True
        assert res["peer_id"] == "peer-rec"
        assert res["is_online"] is True
        assert res["message"] == "Peer reconnected"
