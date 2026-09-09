# /opt/networkat_sdwan/core/web_app/tests/test_subscription_phase5.py
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Add application path
sys.path.insert(0, '/app')

from client_app import create_client_app
from scheduler.subscription_checker import check_client_subscription, check_all_subscriptions
from utils.email import send_renewal_reminder_email


class TestSubscriptionSchedulerPhase5(unittest.TestCase):

    def setUp(self):
        self.app = create_client_app()
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    @patch('smtplib.SMTP')
    def test_send_renewal_reminder_email(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value = mock_server

        renewal_date = datetime(2026, 9, 15, 12, 0, 0)
        success, err = send_renewal_reminder_email(
            to_email="customer@example.com",
            client_name="Acme Corp",
            renewal_date=renewal_date,
            plan_name="pro"
        )
        self.assertTrue(success)
        self.assertIsNone(err)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once()
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()

    @patch('config.database.db.session.commit')
    @patch('scheduler.subscription_checker.send_renewal_reminder_email')
    def test_reminder_email_triggers_once(self, mock_send_email, mock_commit):
        mock_send_email.return_value = (True, None)

        now = datetime(2026, 9, 8, 12, 0, 0)
        # Renewal date is 2 days away (within the 3-day window)
        renewal = now + timedelta(days=2)

        client = MagicMock()
        client.username = "testuser"
        client.client_name = "Test User"
        client.client_email = "test@example.com"
        client.subscription_status = "active"
        client.renewal_date = renewal
        client.renewal_notified_at = None
        client.plan = MagicMock(name="starter")

        sub_service = MagicMock()

        # 1. First run: Should send email and set renewal_notified_at
        res1 = check_client_subscription(client, sub_service, now=now)
        self.assertIn("reminder_sent", res1["actions"])
        self.assertEqual(client.renewal_notified_at, now)
        mock_send_email.assert_called_once()
        mock_commit.assert_called_once()

        # 2. Second run: Already notified, should NOT send again
        mock_send_email.reset_mock()
        res2 = check_client_subscription(client, sub_service, now=now)
        self.assertNotIn("reminder_sent", res2["actions"])
        mock_send_email.assert_not_called()

    def test_active_to_grace_period(self):
        now = datetime(2026, 9, 8, 12, 0, 0)
        # Renewal date was yesterday
        renewal = now - timedelta(days=1)

        client = MagicMock()
        client.username = "testuser"
        client.subscription_status = "active"
        client.renewal_date = renewal
        client.renewal_notified_at = now - timedelta(days=3)

        sub_service = MagicMock()

        res = check_client_subscription(client, sub_service, now=now)
        self.assertIn("transition_to_grace_period", res["actions"])
        sub_service.transition_to_grace_period.assert_called_once_with(client, days=3)

    def test_grace_period_to_limit_control(self):
        now = datetime(2026, 9, 8, 12, 0, 0)
        # Grace period expired 1 hour ago
        grace_exp = now - timedelta(hours=1)

        client = MagicMock()
        client.username = "testuser"
        client.subscription_status = "grace_period"
        client.grace_expires_at = grace_exp

        sub_service = MagicMock()

        res = check_client_subscription(client, sub_service, now=now)
        self.assertIn("transition_to_limit_control", res["actions"])
        sub_service.transition_to_limit_control.assert_called_once_with(client)

    def test_limit_control_to_inactive(self):
        now = datetime(2026, 9, 8, 12, 0, 0)
        # Grace period expired 8 days ago (> 7 days threshold)
        grace_exp = now - timedelta(days=8)

        client = MagicMock()
        client.username = "testuser"
        client.subscription_status = "limit_control"
        client.grace_expires_at = grace_exp

        sub_service = MagicMock()

        res = check_client_subscription(client, sub_service, now=now)
        self.assertIn("transition_to_inactive", res["actions"])
        sub_service.transition_to_inactive.assert_called_once_with(client)

    @patch('scheduler.subscription_checker.Client.query')
    @patch('scheduler.subscription_checker.check_client_subscription')
    def test_check_all_subscriptions(self, mock_check_single, mock_query):
        c1 = MagicMock(username="user1")
        c2 = MagicMock(username="user2")
        mock_query.all.return_value = [c1, c2]

        mock_check_single.side_effect = [
            {"username": "user1", "status": "active", "actions": ["reminder_sent"]},
            {"username": "user2", "status": "grace_period", "actions": []}
        ]

        summary = check_all_subscriptions(app=self.app)
        self.assertEqual(summary["total_clients"], 2)
        self.assertEqual(summary["actions_count"], 1)
        self.assertEqual(summary["errors"], 0)


if __name__ == '__main__':
    unittest.main()
