# /opt/networkat_sdwan/core/web_app/tests/test_subscription_phase4.py
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add application path
sys.path.insert(0, '/app')

from client_app import create_client_app
from models.client import Client


class TestSubscriptionMiddlewarePhase4(unittest.TestCase):

    def setUp(self):
        self.app = create_client_app()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret'
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    @patch('models.client.Client.query')
    def test_write_blocked_when_limit_control(self, mock_query):
        # Setup mock client in limit_control
        mock_client = MagicMock()
        mock_client.subscription_status = 'limit_control'
        mock_client.is_subscription_active = False
        mock_query.get.return_value = mock_client

        with self.client.session_transaction() as sess:
            sess['client_logged_in'] = True
            sess['client_customer_id'] = 'test-uuid'

        # Test 1: POST /api/peers/p1/firewall/rules
        res = self.client.post('/api/peers/p1/firewall/rules', json={"rule_name": "Block SSH"})
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data["error"], "Subscription Restricted")
        self.assertEqual(data["subscription_status"], "limit_control")
        self.assertTrue(data["read_only"])

        # Test 2: PUT /api/v2/netbird/routes/r1
        res = self.client.put('/api/v2/netbird/routes/r1', json={})
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data["subscription_status"], "limit_control")

        # Test 3: POST /api/peers/p1/aliases
        res = self.client.post('/api/peers/p1/aliases', json={})
        self.assertEqual(res.status_code, 403)

        # Test 4: POST /api/peers/p1/web-filter/rules
        res = self.client.post('/api/peers/p1/web-filter/rules', json={})
        self.assertEqual(res.status_code, 403)

    @patch('models.client.Client.query')
    def test_write_blocked_when_inactive(self, mock_query):
        mock_client = MagicMock()
        mock_client.subscription_status = 'inactive'
        mock_client.is_subscription_active = False
        mock_query.get.return_value = mock_client

        with self.client.session_transaction() as sess:
            sess['client_logged_in'] = True
            sess['client_customer_id'] = 'test-uuid'

        res = self.client.delete('/api/peers/p1/firewall/rules/1')
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data["error"], "Subscription Restricted")
        self.assertEqual(data["subscription_status"], "inactive")

    @patch('models.client.Client.query')
    @patch('client.routes.firewall.verify_peer_access')
    def test_write_allowed_when_grace_period(self, mock_verify, mock_query):
        mock_client = MagicMock()
        mock_client.subscription_status = 'grace_period'
        mock_client.is_subscription_active = True
        mock_query.get.return_value = mock_client
        mock_verify.return_value = False  # To test it passes decorator and reaches handler

        with self.client.session_transaction() as sess:
            sess['client_logged_in'] = True
            sess['client_customer_id'] = 'test-uuid'

        # Since mock_verify is False, handler should return 403 Unauthorized (not Subscription Restricted!)
        res = self.client.post('/api/peers/p1/firewall/rules', json={})
        data = res.get_json()
        self.assertNotEqual(data.get("error"), "Subscription Restricted")

    @patch('models.client.Client.query')
    @patch('client.routes.firewall.verify_peer_access')
    def test_write_allowed_when_active(self, mock_verify, mock_query):
        mock_client = MagicMock()
        mock_client.subscription_status = 'active'
        mock_client.is_subscription_active = True
        mock_query.get.return_value = mock_client
        mock_verify.return_value = False

        with self.client.session_transaction() as sess:
            sess['client_logged_in'] = True
            sess['client_customer_id'] = 'test-uuid'

        res = self.client.post('/api/peers/p1/firewall/rules', json={})
        data = res.get_json()
        self.assertNotEqual(data.get("error"), "Subscription Restricted")


    @patch('models.client.Client.query')
    @patch('client.routes.peer_api.read_file_cache')
    @patch('client.routes.peer_api.get_cached_customer_peer_ids')
    def test_peers_status_offline_when_inactive(self, mock_peer_ids, mock_cache, mock_query):
        """When subscription is inactive, /api/peers/status must report all peers as offline and online count as 0."""
        mock_client = MagicMock()
        mock_client.subscription_status = 'inactive'
        mock_query.get.return_value = mock_client
        mock_peer_ids.return_value = {'peer-1', 'peer-2'}

        cached_payload = {
            "peers": [
                {"id": "peer-1", "name": "Device 1", "is_online": True, "connected": True},
                {"id": "peer-2", "name": "Device 2", "is_online": True, "connected": True}
            ],
            "summary": {"total": 2, "online": 2, "offline": 0}
        }
        mock_cache.return_value = (cached_payload, 9999999999)

        with self.client.session_transaction() as sess:
            sess['client_logged_in'] = True
            sess['client_customer_id'] = 'test-uuid'

        res = self.client.get('/api/peers/status')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["summary"]["online"], 0)
        self.assertEqual(data["summary"]["offline"], 2)
        for p in data["peers"]:
            self.assertFalse(p["is_online"])
            self.assertFalse(p["connected"])

    @patch('models.client.Client.query')
    @patch('client.context_processors.read_file_cache')
    def test_sidebar_offline_when_inactive(self, mock_cache, mock_query):
        """When subscription is inactive, inject_client_sidebar must set all peers as disconnected and online count as 0."""
        from client.context_processors import inject_client_sidebar

        mock_client = MagicMock()
        mock_client.subscription_status = 'inactive'
        mock_query.get.return_value = mock_client

        cached_payload = {
            "peers": [
                {"id": "peer-1", "name": "Device 1", "is_online": True, "connected": True},
                {"id": "peer-2", "name": "Device 2", "is_online": True, "connected": True}
            ]
        }
        mock_cache.return_value = (cached_payload, 9999999999)

        with self.client.session_transaction() as sess:
            sess['client_customer_id'] = 'test-uuid'

        with self.app.test_request_context():
            from flask import session
            session['client_customer_id'] = 'test-uuid'
            ctx = inject_client_sidebar()
            self.assertEqual(ctx["sidebar_online_count"], 0)
            self.assertEqual(ctx["sidebar_offline_count"], 2)
            for p in ctx["sidebar_peers"]:
                self.assertFalse(p["connected"])


if __name__ == '__main__':
    unittest.main()

