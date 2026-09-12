import sys
sys.path.insert(0, '/app')

import asyncio
import unittest
from unittest.mock import patch, MagicMock
from fastapi_app.routes.auth import install_peer
from fastapi_app.schemas.auth import InstallPeerRequest


class TestInstallPeerApi(unittest.TestCase):

    def setUp(self):
        self.mock_request = MagicMock()
        self.mock_request.client.host = "127.0.0.1"
        self.mock_request.headers = {}

    @patch('fastapi_app.routes.auth.SessionLocal')
    @patch('fastapi_app.routes.auth.check_password_hash')
    def test_install_peer_unauthorized(self, mock_pwd, mock_db):
        mock_db_session = MagicMock()
        mock_db.return_value = mock_db_session
        mock_db_session.execute.return_value.fetchone.return_value = None

        payload = InstallPeerRequest(username="unknown", password="pwd")
        resp = asyncio.run(install_peer(payload, self.mock_request))
        self.assertEqual(resp.status_code, 401)
        import json
        data = json.loads(resp.body.decode())
        self.assertEqual(data["error"], "Unauthorized")

    @patch('fastapi_app.routes.auth.SessionLocal')
    @patch('fastapi_app.routes.auth.check_password_hash')
    @patch('fastapi_app.routes.auth.requests.get')
    def test_install_peer_inactive_subscription(self, mock_get, mock_pwd, mock_db):
        mock_pwd.return_value = True
        mock_db_session = MagicMock()
        mock_db.return_value = mock_db_session

        # Return client row with subscription_status = 'inactive'
        mock_db_session.execute.return_value.fetchone.return_value = (
            "uuid-1", "hashed", True,
            "Mustafa Net", "Networkat", "mustafa@networkat.cloud",
            "Egypt", "pro", None,
            "group-1", "inactive", 1,
            5,
            "pro", "Pro Plan", 5
        )

        payload = InstallPeerRequest(username="mustafa", password="pwd")
        resp = asyncio.run(install_peer(payload, self.mock_request))
        self.assertEqual(resp.status_code, 403)
        import json
        data = json.loads(resp.body.decode())
        self.assertEqual(data["error"], "Forbidden")
        self.assertIn("Subscription inactive", data["message"])
        self.assertIn("account", data)

    @patch('fastapi_app.routes.auth.SessionLocal')
    @patch('fastapi_app.routes.auth.check_password_hash')
    @patch('fastapi_app.routes.auth.requests.get')
    def test_install_peer_grace_period_returns_account(self, mock_get, mock_pwd, mock_db):
        mock_pwd.return_value = True
        mock_db_session = MagicMock()
        mock_db.return_value = mock_db_session

        # Group query response returns 2 peers
        mock_grp_resp = MagicMock()
        mock_grp_resp.status_code = 200
        mock_grp_resp.json.return_value = {"peers_count": 2}
        mock_get.return_value = mock_grp_resp

        # Return client row with subscription_status = 'grace_period'
        mock_db_session.execute.return_value.fetchone.return_value = (
            "uuid-1", "hashed", True,
            "Mustafa Net", "Networkat", "mustafa@networkat.cloud",
            "Egypt", "starter", None,
            "group-1", "grace_period", 1,
            4,
            "starter", "Starter Plan", 4
        )

        payload = InstallPeerRequest(username="mustafa", password="pwd")
        resp = asyncio.run(install_peer(payload, self.mock_request))
        self.assertEqual(resp.status_code, 403)
        import json
        data = json.loads(resp.body.decode())
        self.assertEqual(data["error"], "Forbidden")
        self.assertIn("Subscription inactive", data["message"])
        self.assertIn("account", data)
        self.assertEqual(data["account"]["full_name"], "Mustafa Net")
        self.assertEqual(data["account"]["subscription"]["installed_peers_count"], 2)
        self.assertEqual(data["account"]["subscription"]["allowed_peers_count"], 4)
        self.assertEqual(data["account"]["subscription"]["remaining_peers_count"], 2)

    @patch('fastapi_app.routes.auth.SessionLocal')
    @patch('fastapi_app.routes.auth.check_password_hash')
    @patch('fastapi_app.routes.auth.requests.get')
    def test_install_peer_quota_exceeded(self, mock_get, mock_pwd, mock_db):
        mock_pwd.return_value = True
        mock_db_session = MagicMock()
        mock_db.return_value = mock_db_session

        mock_grp_resp = MagicMock()
        mock_grp_resp.status_code = 200
        mock_grp_resp.json.return_value = {"peers_count": 4}
        mock_get.return_value = mock_grp_resp

        # Return active client with 4 allowed and 4 installed
        mock_db_session.execute.return_value.fetchone.return_value = (
            "uuid-1", "hashed", True,
            "Mustafa Net", "Networkat", "mustafa@networkat.cloud",
            "Egypt", "starter", None,
            "group-1", "active", 1,
            4,
            "starter", "Starter Plan", 4
        )

        payload = InstallPeerRequest(username="mustafa", password="pwd")
        resp = asyncio.run(install_peer(payload, self.mock_request))
        self.assertEqual(resp.status_code, 403)
        import json
        data = json.loads(resp.body.decode())
        self.assertEqual(data["error"], "Forbidden")
        self.assertIn("Peer limit reached", data["message"])
        self.assertIn("account", data)
        self.assertEqual(data["account"]["subscription"]["installed_peers_count"], 4)
        self.assertEqual(data["account"]["subscription"]["remaining_peers_count"], 0)


if __name__ == '__main__':
    unittest.main()
