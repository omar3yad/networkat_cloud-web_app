# /opt/networkat_sdwan/core/web_app/tests/test_subscription_state_machine.py
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Add application path
sys.path.insert(0, '/app')

from client_app import create_client_app
from services.subscription_service import SubscriptionService


class TestSubscriptionStateMachine(unittest.TestCase):

    def setUp(self):
        self.app = create_client_app()
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.service = SubscriptionService()

    def tearDown(self):
        self.app_context.pop()

    @patch('config.database.db.session.commit')
    def test_transition_to_grace_period(self, mock_commit):
        client = MagicMock()
        client.username = "testuser"
        client.subscription_status = "active"
        client.grace_expires_at = None

        success = self.service.transition_to_grace_period(client, days=3)
        self.assertTrue(success)
        self.assertEqual(client.subscription_status, "grace_period")
        self.assertIsNotNone(client.grace_expires_at)
        self.assertGreater(client.grace_expires_at, datetime.utcnow())
        mock_commit.assert_called_once()

    @patch('config.database.db.session.commit')
    @patch.object(SubscriptionService, '_find_policy_by_name')
    @patch.object(SubscriptionService, '_set_policy_enabled')
    def test_transition_to_limit_control(self, mock_set_policy, mock_find_policy, mock_commit):
        client = MagicMock()
        client.username = "testuser"
        client.subscription_status = "grace_period"

        # Mock that testuser-pkgs policy exists
        mock_find_policy.return_value = {"id": "pkgs-pol-123", "name": "testuser-pkgs"}
        mock_set_policy.return_value = True

        success = self.service.transition_to_limit_control(client)
        self.assertTrue(success)
        self.assertEqual(client.subscription_status, "limit_control")
        mock_find_policy.assert_called_with("testuser-pkgs")
        mock_set_policy.assert_called_with("pkgs-pol-123", False)
        mock_commit.assert_called_once()

    @patch('config.database.db.session.commit')
    @patch.object(SubscriptionService, '_find_policy_by_name')
    @patch.object(SubscriptionService, '_set_policy_enabled')
    @patch.object(SubscriptionService, '_remove_peers_from_all_peers_group')
    def test_transition_to_inactive(self, mock_remove_peers, mock_set_policy, mock_find_policy, mock_commit):
        client = MagicMock()
        client.username = "testuser"
        client.subscription_status = "limit_control"

        def find_policy_side_effect(name):
            if name in ("testuser", "testuser-allow_mesh"):
                return {"id": "mesh-pol-1", "name": name}
            if name in ("testuser-pkgs", "testuser-allow_pkgs_servers"):
                return {"id": "pkgs-pol-2", "name": name}
            if name in ("testuser-controllers", "testuser-allow_controllers"):
                return {"id": "ctrl-pol-3", "name": name}
            return None

        mock_find_policy.side_effect = find_policy_side_effect
        mock_set_policy.return_value = True

        success = self.service.transition_to_inactive(client)
        self.assertTrue(success)
        self.assertEqual(client.subscription_status, "inactive")
        
        # Mesh policy disabled
        mock_set_policy.assert_any_call("mesh-pol-1", False)
        # Packages policy disabled
        mock_set_policy.assert_any_call("pkgs-pol-2", False)
        # Controllers policy NOT disabled (left intact)
        for call_item in mock_set_policy.call_args_list:
            self.assertNotEqual(call_item[0][0], "ctrl-pol-3")
        # Peers NOT removed from all-peers so controllers communication remains active
        mock_remove_peers.assert_not_called()
        mock_commit.assert_called_once()

    @patch('config.database.db.session.commit')
    @patch.object(SubscriptionService, '_find_policy_by_name')
    @patch.object(SubscriptionService, '_set_policy_enabled')
    @patch.object(SubscriptionService, '_add_peers_to_all_peers_group')
    def test_restore_active(self, mock_add_peers, mock_set_policy, mock_find_policy, mock_commit):
        client = MagicMock()
        client.username = "testuser"
        client.subscription_status = "inactive"
        client.grace_expires_at = datetime.utcnow()
        new_renewal = datetime.utcnow() + timedelta(days=30)

        def find_policy_side_effect(name):
            if name == "testuser":
                return {"id": "mesh-pol-1", "name": "testuser"}
            if name == "testuser-pkgs":
                return {"id": "pkgs-pol-2", "name": "testuser-pkgs"}
            return None

        mock_find_policy.side_effect = find_policy_side_effect
        mock_set_policy.return_value = True
        mock_add_peers.return_value = True

        success = self.service.restore_active(
            client,
            new_renewal_date=new_renewal,
            plan_id=2,
            billing_cycle="yearly"
        )
        self.assertTrue(success)
        self.assertEqual(client.subscription_status, "active")
        self.assertIsNone(client.grace_expires_at)
        self.assertEqual(client.renewal_date, new_renewal)
        self.assertEqual(client.plan_id, 2)
        self.assertEqual(client.billing_cycle, "yearly")

        # Policies re-enabled
        mock_set_policy.assert_any_call("mesh-pol-1", True)
        mock_set_policy.assert_any_call("pkgs-pol-2", True)
        # Peers re-added to all-peers group
        mock_add_peers.assert_called_once_with(client)
        mock_commit.assert_called_once()

    @patch.object(SubscriptionService, 'get_client_peer_count')
    def test_get_subscription_info(self, mock_peer_count):
        mock_peer_count.return_value = 3
        client = MagicMock()
        client.username = "testuser"
        client.subscription_status = "active"
        client.is_subscription_active = True
        client.is_subscription_readonly = False
        client.is_subscription_inactive = False
        client.billing_cycle = "monthly"
        client.renewal_date = datetime(2026, 10, 1, 0, 0, 0)
        client.grace_expires_at = None
        
        plan = MagicMock()
        plan.name = "pro"
        plan.display_name = "Professional"
        plan.allowed_peers_count = 15
        client.plan = plan

        info = self.service.get_subscription_info(client)
        self.assertEqual(info["username"], "testuser")
        self.assertEqual(info["status"], "active")
        self.assertEqual(info["plan_name"], "pro")
        self.assertEqual(info["allowed_peers_count"], 15)
        self.assertEqual(info["installed_peers_count"], 3)
        self.assertEqual(info["remaining_peers_count"], 12)
        self.assertEqual(info["billing_cycle"], "monthly")
        self.assertEqual(info["renewal_date"], "2026-10-01T00:00:00")
        self.assertIsNone(info["grace_expires_at"])
        self.assertTrue(info["can_add_peers"])

    @patch.object(SubscriptionService, 'get_client_peer_count')
    def test_cannot_install_peer_during_grace_period(self, mock_peer_count):
        mock_peer_count.return_value = 2
        client = MagicMock()
        client.username = "grace_user"
        client.active = True
        client.subscription_status = "grace_period"
        plan = MagicMock()
        plan.allowed_peers_count = 5
        client.plan = plan

        allowed, msg, quota = self.service.can_install_peer(client)
        self.assertFalse(allowed)
        self.assertIn("grace period", msg)
        self.assertEqual(quota["remaining_peers_count"], 0)

        remaining = self.service.get_remaining_peers(client)
        self.assertEqual(remaining, 0)

        info = self.service.get_subscription_info(client)
        self.assertFalse(info["can_add_peers"])
        self.assertEqual(info["remaining_peers_count"], 0)

    @patch.object(SubscriptionService, 'get_client_peer_count')
    def test_can_install_peer_when_active(self, mock_peer_count):
        mock_peer_count.return_value = 2
        client = MagicMock()
        client.username = "active_user"
        client.active = True
        client.subscription_status = "active"
        plan = MagicMock()
        plan.name = "starter"
        plan.display_name = "Starter"
        plan.allowed_peers_count = 5
        client.plan = plan
        client.allowed_peers_count = 5

        allowed, msg, quota = self.service.can_install_peer(client)
        self.assertTrue(allowed)
        self.assertEqual(quota["remaining_peers_count"], 3)

        remaining = self.service.get_remaining_peers(client)
        self.assertEqual(remaining, 3)

        info = self.service.get_subscription_info(client)
        self.assertTrue(info["can_add_peers"])
        self.assertEqual(info["remaining_peers_count"], 3)


if __name__ == '__main__':
    unittest.main()
