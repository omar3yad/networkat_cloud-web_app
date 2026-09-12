import sys
sys.path.insert(0, '/app')

import unittest
from unittest.mock import patch, MagicMock
from client_app import create_client_app


class TestPeerUpdateApi(unittest.TestCase):

    def setUp(self):
        self.app = create_client_app()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-12345'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

    def test_update_unauthenticated(self):
        resp = self.client.get('/api/peers/peer-123/update')
        # client_login_required redirects unauthenticated requests
        self.assertEqual(resp.status_code, 302)

    @patch('client.routes.peer_api.Client')
    @patch('client.routes.peer_api.verify_peer_access')
    @patch('client.routes.peer_api.get_cached_all_netbird_peers')
    @patch('client.routes.peer_api.requests.get')
    def test_get_peer_health(self, mock_requests_get, mock_peers, mock_verify, mock_client_cls):
        mock_verify.return_value = True
        mock_customer = MagicMock()
        mock_customer.is_subscription_active = True
        mock_customer.subscription_status = 'active'
        mock_client_cls.query.get.return_value = mock_customer

        mock_peers.return_value = [{"id": "peer-123", "ip": "100.64.0.10"}]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": "ok", "version": "1.6.0-beta.1", "uptime": 57999}'
        mock_requests_get.return_value = mock_resp

        with self.client.session_transaction() as sess:
            sess['client_logged_in'] = True
            sess['client_id'] = 'user-123'
            sess['client_customer_id'] = 1

        resp = self.client.get('/api/peers/peer-123/health')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("version"), "1.6.0-beta.1")
        mock_requests_get.assert_called_once_with(
            "http://100.64.0.10:8765/health",
            timeout=(1, 2)
        )

    @patch('client.routes.peer_api.Client')
    @patch('client.routes.peer_api.verify_peer_access')
    @patch('client.routes.peer_api.get_cached_all_netbird_peers')
    @patch('client.routes.peer_api.requests.get')
    def test_get_peer_update_status(self, mock_requests_get, mock_peers, mock_verify, mock_client_cls):
        mock_verify.return_value = True
        mock_customer = MagicMock()
        mock_customer.is_subscription_active = True
        mock_customer.subscription_status = 'active'
        mock_client_cls.query.get.return_value = mock_customer

        mock_peers.return_value = [{"id": "peer-123", "ip": "100.64.0.10"}]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"update": {"state": "update-available", "installed_version": "1.0.0", "available_version": "1.1.0"}}'
        mock_requests_get.return_value = mock_resp

        with self.client.session_transaction() as sess:
            sess['client_logged_in'] = True
            sess['client_id'] = 'user-123'
            sess['client_customer_id'] = 1

        resp = self.client.get('/api/peers/peer-123/update')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("update", data)
        self.assertEqual(data["update"]["state"], "update-available")
        mock_requests_get.assert_called_once_with(
            "http://100.64.0.10:8765/update",
            timeout=(2, 15)
        )

    @patch('client.routes.peer_api.Client')
    @patch('client.routes.peer_api.verify_peer_access')
    @patch('client.routes.peer_api.get_cached_all_netbird_peers')
    @patch('client.routes.peer_api.requests.post')
    def test_post_peer_update_apply(self, mock_requests_post, mock_peers, mock_verify, mock_client_cls):
        mock_verify.return_value = True
        mock_customer = MagicMock()
        mock_customer.is_subscription_active = True
        mock_customer.subscription_status = 'active'
        mock_client_cls.query.get.return_value = mock_customer

        mock_peers.return_value = [{"id": "peer-123", "ip": "100.64.0.10"}]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"ok": true, "code": "ok", "message": "Upgrade completed successfully"}'
        mock_requests_post.return_value = mock_resp

        with self.client.session_transaction() as sess:
            sess['client_logged_in'] = True
            sess['client_id'] = 'user-123'
            sess['client_customer_id'] = 1

        resp = self.client.post('/api/peers/peer-123/update', json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        mock_requests_post.assert_called_once_with(
            "http://100.64.0.10:8765/update",
            json={},
            timeout=(2, 180)
        )

    @patch('client.routes.peer_api.Client')
    @patch('client.routes.peer_api.verify_peer_access')
    @patch('client.routes.peer_api.get_cached_all_netbird_peers')
    @patch('client.routes.peer_api.requests.get')
    def test_get_update_config(self, mock_requests_get, mock_peers, mock_verify, mock_client_cls):
        mock_verify.return_value = True
        mock_customer = MagicMock()
        mock_customer.is_subscription_active = True
        mock_customer.subscription_status = 'active'
        mock_client_cls.query.get.return_value = mock_customer

        mock_peers.return_value = [{"id": "peer-123", "ip": "100.64.0.10"}]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "auto_update_enabled": True,
            "update_check_interval_seconds": 43200
        }
        mock_requests_get.return_value = mock_resp

        with self.client.session_transaction() as sess:
            sess['client_logged_in'] = True
            sess['client_id'] = 'user-123'
            sess['client_customer_id'] = 1

        resp = self.client.get('/api/peers/peer-123/update/config')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("auto_update_enabled"))
        self.assertEqual(data.get("update_check_interval_hours"), 12)

    @patch('client.routes.peer_api.Client')
    @patch('client.routes.peer_api.verify_peer_access')
    @patch('client.routes.peer_api.get_cached_all_netbird_peers')
    def test_put_update_config_rejects_less_than_3_hours(self, mock_peers, mock_verify, mock_client_cls):
        mock_verify.return_value = True
        mock_customer = MagicMock()
        mock_customer.is_subscription_active = True
        mock_customer.subscription_status = 'active'
        mock_client_cls.query.get.return_value = mock_customer

        mock_peers.return_value = [{"id": "peer-123", "ip": "100.64.0.10"}]

        with self.client.session_transaction() as sess:
            sess['client_logged_in'] = True
            sess['client_id'] = 'user-123'
            sess['client_customer_id'] = 1

        # Try interval of 2 hours (7200 seconds)
        resp = self.client.put(
            '/api/peers/peer-123/update/config',
            json={
                "auto_update_enabled": True,
                "update_check_interval_seconds": 7200
            }
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("3 hours", data["error"])

    @patch('client.routes.peer_api.Client')
    @patch('client.routes.peer_api.verify_peer_access')
    @patch('client.routes.peer_api.get_cached_all_netbird_peers')
    @patch('client.routes.peer_api.requests.put')
    def test_put_update_config_accepts_valid_interval(self, mock_requests_put, mock_peers, mock_verify, mock_client_cls):
        mock_verify.return_value = True
        mock_customer = MagicMock()
        mock_customer.is_subscription_active = True
        mock_customer.subscription_status = 'active'
        mock_client_cls.query.get.return_value = mock_customer

        mock_peers.return_value = [{"id": "peer-123", "ip": "100.64.0.10"}]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "auto_update_enabled": True,
            "update_check_interval_seconds": 21600
        }
        mock_requests_put.return_value = mock_resp

        with self.client.session_transaction() as sess:
            sess['client_logged_in'] = True
            sess['client_id'] = 'user-123'
            sess['client_customer_id'] = 1

        # Valid 6 hours
        resp = self.client.put(
            '/api/peers/peer-123/update/config',
            json={
                "auto_update_enabled": True,
                "update_check_interval_seconds": 21600
            }
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        mock_requests_put.assert_called_once_with(
            "http://100.64.0.10:8765/update/config",
            json={"auto_update_enabled": True, "update_check_interval_seconds": 21600},
            timeout=(2, 10)
        )


if __name__ == '__main__':
    unittest.main()
