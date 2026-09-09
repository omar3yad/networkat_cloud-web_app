# /opt/networkat_sdwan/core/web_app/tests/test_subscription_phase2.py
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add application path
sys.path.insert(0, '/app')

from client_app import create_client_app
from config.database import db
from models import Client, SubscriptionPlan


class TestSubscriptionSetupKey(unittest.TestCase):

    def setUp(self):
        self.app = create_client_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_missing_or_bad_json(self):
        # 415 when Content-Type is not JSON
        res = self.client.post('/api/v1/auth/setup-key', data="not json")
        self.assertEqual(res.status_code, 415)

        # 400 when empty json
        res = self.client.post('/api/v1/auth/setup-key', json={})
        self.assertEqual(res.status_code, 400)
        self.assertIn("required", res.get_json()["message"])

    def test_invalid_credentials(self):
        res = self.client.post('/api/v1/auth/setup-key', json={
            "username": "non_existent_user_xyz",
            "password": "wrongpassword"
        })
        self.assertEqual(res.status_code, 401)

    @patch('services.customer_service.CustomerService.authenticate_client_user')
    @patch('repositories.client_repository.ClientRepository.get_by_id')
    @patch('services.subscription_service.SubscriptionService.get_client_peer_count')
    def test_forbidden_when_limit_control(self, mock_count, mock_get_client, mock_auth):
        mock_auth.return_value = (True, {"customer_id": "test-uuid"})
        mock_client = MagicMock()
        mock_client.username = "testuser"
        mock_client.active = True
        mock_client.subscription_status = "limit_control"
        mock_client.is_subscription_active = False
        mock_client.peer_limit = 5
        mock_client.plan = MagicMock(peer_limit=5)
        mock_get_client.return_value = mock_client
        mock_count.return_value = 2

        res = self.client.post('/api/v1/auth/setup-key', json={
            "username": "testuser",
            "password": "validpassword"
        })
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data["error"], "Forbidden")
        self.assertIn("read-only mode", data["message"])
        self.assertEqual(data["subscription_status"], "limit_control")
        self.assertEqual(data["remaining_peers"], 0)

    @patch('services.customer_service.CustomerService.authenticate_client_user')
    @patch('repositories.client_repository.ClientRepository.get_by_id')
    @patch('services.subscription_service.SubscriptionService.get_client_peer_count')
    def test_forbidden_when_quota_reached(self, mock_count, mock_get_client, mock_auth):
        mock_auth.return_value = (True, {"customer_id": "test-uuid"})
        mock_client = MagicMock()
        mock_client.username = "testuser"
        mock_client.active = True
        mock_client.subscription_status = "active"
        mock_client.is_subscription_active = True
        mock_client.peer_limit = 5
        mock_client.plan = MagicMock(peer_limit=5)
        mock_get_client.return_value = mock_client
        mock_count.return_value = 5  # Already 5 out of 5

        res = self.client.post('/api/v1/auth/setup-key', json={
            "username": "testuser",
            "password": "validpassword"
        })
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data["error"], "Forbidden")
        self.assertIn("Peer limit reached", data["message"])
        self.assertEqual(data["current_peers"], 5)
        self.assertEqual(data["peer_limit"], 5)
        self.assertEqual(data["remaining_peers"], 0)

    @patch('services.customer_service.CustomerService.authenticate_client_user')
    @patch('repositories.client_repository.ClientRepository.get_by_id')
    @patch('services.subscription_service.SubscriptionService.get_client_peer_count')
    @patch('requests.post')
    def test_success_one_off_setup_key(self, mock_post, mock_count, mock_get_client, mock_auth):
        mock_auth.return_value = (True, {"customer_id": "test-uuid"})
        mock_client = MagicMock()
        mock_client.username = "testuser"
        mock_client.active = True
        mock_client.subscription_status = "active"
        mock_client.is_subscription_active = True
        mock_client.peer_limit = 5
        mock_client.netbird_group_id = "group-123"
        mock_client.plan = MagicMock()
        mock_client.plan.name = "starter"
        mock_client.plan.peer_limit = 5
        mock_get_client.return_value = mock_client
        mock_count.return_value = 2  # 2 of 5 used -> 3 remaining before key, 2 after

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "id": "key-id-999",
            "key": "A1B2C3D4-E5F6-7890",
            "type": "one-off",
            "usage_limit": 1
        }
        mock_post.return_value = mock_resp

        res = self.client.post('/api/v1/auth/setup-key', json={
            "username": "testuser",
            "password": "validpassword"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["setup_key"], "A1B2C3D4-E5F6-7890")
        self.assertEqual(data["username"], "testuser")
        self.assertEqual(data["plan"], "starter")
        self.assertEqual(data["peer_limit"], 5)
        self.assertEqual(data["current_peers"], 2)
        self.assertEqual(data["remaining_peers"], 2)  # (5 - 2 - 1)
        self.assertEqual(data["expires_in"], 86400)


if __name__ == '__main__':
    unittest.main()
