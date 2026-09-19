import sys
sys.path.insert(0, '/app')

import asyncio
import unittest
from unittest.mock import patch, MagicMock

import os
from fastapi_app.routes.auth import create_peer_route, _RATE_STORE
from fastapi_app.schemas.auth import PeerRouteRequest
from fastapi_app.services.auth.download_token import make_token


class TestPeerRouteApi(unittest.TestCase):

    def setUp(self):
        _RATE_STORE.clear()
        os.environ["NETBIRD_TOKEN"] = "mock-netbird-token"
        os.environ["NETBIRD_API_URL"] = "http://netbird-server/api"
        self.mock_request = MagicMock()
        self.mock_request.client.host = "127.0.0.1"
        self.mock_request.headers = {}
        self.valid_token = make_token("omar3yad")


    def test_peer_route_unauthorized_no_token(self):
        payload = PeerRouteRequest(peer_id="peer-1", network="192.168.1.0/24")
        resp = asyncio.run(create_peer_route(payload, self.mock_request, authorization=None))
        self.assertEqual(resp.status_code, 401)
        import json
        data = json.loads(resp.body.decode())
        self.assertEqual(data["error"], "Unauthorized")

    def test_peer_route_unauthorized_invalid_token(self):
        payload = PeerRouteRequest(peer_id="peer-1", network="192.168.1.0/24")
        resp = asyncio.run(create_peer_route(payload, self.mock_request, authorization="Bearer invalid.token.value"))
        self.assertEqual(resp.status_code, 401)
        import json
        data = json.loads(resp.body.decode())
        self.assertEqual(data["error"], "Unauthorized")

    def test_peer_route_invalid_cidr(self):
        payload = PeerRouteRequest(peer_id="peer-1", network="not-a-valid-cidr")
        resp = asyncio.run(create_peer_route(payload, self.mock_request, authorization=f"Bearer {self.valid_token}"))
        self.assertEqual(resp.status_code, 400)
        import json
        data = json.loads(resp.body.decode())
        self.assertEqual(data["error"], "Bad Request")
        self.assertIn("Invalid IPv4 CIDR", data["message"])

    @patch('fastapi_app.routes.auth.SessionLocal')
    def test_peer_route_inactive_subscription(self, mock_db):
        mock_db_session = MagicMock()
        mock_db.return_value = mock_db_session
        mock_db_session.execute.return_value.fetchone.return_value = (
            "uuid-1", True, "grp-1", "inactive"
        )

        payload = PeerRouteRequest(peer_id="peer-1", network="192.168.1.0/24")
        resp = asyncio.run(create_peer_route(payload, self.mock_request, authorization=f"Bearer {self.valid_token}"))
        self.assertEqual(resp.status_code, 403)
        import json
        data = json.loads(resp.body.decode())
        self.assertEqual(data["error"], "Forbidden")
        self.assertIn("inactive", data["message"])

    @patch('fastapi_app.routes.auth.SessionLocal')
    def test_peer_route_missing_peer_identifier(self, mock_db):
        mock_db_session = MagicMock()
        mock_db.return_value = mock_db_session
        mock_db_session.execute.return_value.fetchone.return_value = (
            "uuid-1", True, "grp-1", "active"
        )

        payload = PeerRouteRequest(network="192.168.1.0/24")
        resp = asyncio.run(create_peer_route(payload, self.mock_request, authorization=f"Bearer {self.valid_token}"))
        self.assertEqual(resp.status_code, 400)
        import json
        data = json.loads(resp.body.decode())
        self.assertEqual(data["error"], "Bad Request")

    @patch('fastapi_app.routes.auth.SessionLocal')
    @patch('fastapi_app.routes.auth.requests.get')
    def test_peer_route_peer_not_found(self, mock_get, mock_db):
        mock_db_session = MagicMock()
        mock_db.return_value = mock_db_session
        mock_db_session.execute.return_value.fetchone.return_value = (
            "uuid-1", True, "grp-1", "active"
        )

        # NetBird group has no peers
        mock_grp_resp = MagicMock()
        mock_grp_resp.status_code = 200
        mock_grp_resp.json.return_value = {"id": "grp-1", "peers": []}

        # NetBird all peers has no matching peer
        mock_peers_resp = MagicMock()
        mock_peers_resp.status_code = 200
        mock_peers_resp.json.return_value = []

        mock_get.side_effect = [mock_grp_resp, mock_peers_resp]

        payload = PeerRouteRequest(peer_id="unknown-peer", network="192.168.1.0/24")
        resp = asyncio.run(create_peer_route(payload, self.mock_request, authorization=f"Bearer {self.valid_token}"))
        self.assertEqual(resp.status_code, 404)
        import json
        data = json.loads(resp.body.decode())
        self.assertEqual(data["error"], "Not Found")

    @patch('fastapi_app.routes.auth.SessionLocal')
    @patch('fastapi_app.routes.auth.requests.get')
    def test_peer_route_duplicate_subnet(self, mock_get, mock_db):
        mock_db_session = MagicMock()
        mock_db.return_value = mock_db_session
        mock_db_session.execute.return_value.fetchone.return_value = (
            "uuid-1", True, "grp-1", "active"
        )

        # NetBird group has peer-1 and peer-2
        mock_grp_resp = MagicMock()
        mock_grp_resp.status_code = 200
        mock_grp_resp.json.return_value = {"id": "grp-1", "peers": ["peer-1", "peer-2"]}

        # NetBird routes has 192.168.1.0/24 assigned to peer-2
        mock_routes_resp = MagicMock()
        mock_routes_resp.status_code = 200
        mock_routes_resp.json.return_value = [
            {"id": "r-1", "peer": "peer-2", "network": "192.168.1.0/24"}
        ]

        mock_get.side_effect = [mock_grp_resp, mock_routes_resp]

        payload = PeerRouteRequest(peer_id="peer-1", network="192.168.1.0/24")
        resp = asyncio.run(create_peer_route(payload, self.mock_request, authorization=f"Bearer {self.valid_token}"))
        self.assertEqual(resp.status_code, 400)
        import json
        data = json.loads(resp.body.decode())
        self.assertEqual(data["error"], "Bad Request")
        self.assertIn("already in use", data["message"])

    @patch('fastapi_app.routes.auth.SessionLocal')
    @patch('fastapi_app.routes.auth.requests.get')
    @patch('fastapi_app.routes.auth.requests.post')
    def test_peer_route_success_with_peer_id(self, mock_post, mock_get, mock_db):
        mock_db_session = MagicMock()
        mock_db.return_value = mock_db_session
        mock_db_session.execute.return_value.fetchone.return_value = (
            "uuid-1", True, "grp-1", "active"
        )

        # NetBird group has peer-1
        mock_grp_resp = MagicMock()
        mock_grp_resp.status_code = 200
        mock_grp_resp.json.return_value = {"id": "grp-1", "peers": ["peer-1"]}

        # NetBird routes empty
        mock_routes_resp = MagicMock()
        mock_routes_resp.status_code = 200
        mock_routes_resp.json.return_value = []

        mock_get.side_effect = [mock_grp_resp, mock_routes_resp]

        # NetBird create route response
        mock_create_resp = MagicMock()
        mock_create_resp.status_code = 201
        mock_create_resp.json.return_value = {"id": "route-123"}
        mock_post.return_value = mock_create_resp

        payload = PeerRouteRequest(peer_id="peer-1", network="192.168.1.0/24", masquerade=True, metric=9999)
        resp = asyncio.run(create_peer_route(payload, self.mock_request, authorization=f"Bearer {self.valid_token}"))
        
        self.assertEqual(resp.success, True)
        self.assertEqual(resp.route_id, "route-123")
        self.assertEqual(resp.peer_id, "peer-1")
        self.assertEqual(resp.network, "192.168.1.0/24")

    @patch('fastapi_app.routes.auth.SessionLocal')
    @patch('fastapi_app.routes.auth.requests.get')
    @patch('fastapi_app.routes.auth.requests.post')
    def test_peer_route_success_with_peer_ip(self, mock_post, mock_get, mock_db):
        mock_db_session = MagicMock()
        mock_db.return_value = mock_db_session
        mock_db_session.execute.return_value.fetchone.return_value = (
            "uuid-1", True, "grp-1", "active"
        )

        mock_grp_resp = MagicMock()
        mock_grp_resp.status_code = 200
        mock_grp_resp.json.return_value = {"id": "grp-1", "peers": ["peer-1"]}

        mock_peers_resp = MagicMock()
        mock_peers_resp.status_code = 200
        mock_peers_resp.json.return_value = [
            {"id": "peer-1", "ip": "100.64.0.10", "name": "branch-router", "groups": ["grp-1"]}
        ]

        mock_routes_resp = MagicMock()
        mock_routes_resp.status_code = 200
        mock_routes_resp.json.return_value = []

        mock_get.side_effect = [mock_grp_resp, mock_peers_resp, mock_routes_resp]

        mock_create_resp = MagicMock()
        mock_create_resp.status_code = 201
        mock_create_resp.json.return_value = {"id": "route-456"}
        mock_post.return_value = mock_create_resp

        payload = PeerRouteRequest(peer_ip="100.64.0.10", network="10.10.0.0/16")
        resp = asyncio.run(create_peer_route(payload, self.mock_request, authorization=f"Bearer {self.valid_token}"))
        
        self.assertEqual(resp.success, True)
        self.assertEqual(resp.route_id, "route-456")
        self.assertEqual(resp.peer_id, "peer-1")
        self.assertEqual(resp.network, "10.10.0.0/16")


if __name__ == '__main__':
    unittest.main()
