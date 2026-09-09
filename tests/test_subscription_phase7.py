# tests/test_subscription_phase7.py
import sys
import unittest
import uuid
from unittest.mock import patch, MagicMock
from datetime import datetime

# Add application path
sys.path.insert(0, '/app')

from app import create_app
from extensions import db
from models.client import Client
from models.subscription_plan import SubscriptionPlan


class TestSubscriptionAdminPhase7(unittest.TestCase):

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-admin-phase7'
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_unauthorized_access_redirects(self):
        """Unauthenticated requests to admin subscription API must be redirected to login."""
        cust_id = str(uuid.uuid4())
        resp = self.client.get(f'/api/customers/{cust_id}/subscription')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    @patch('models.client.Client.query')
    @patch('services.subscription_service.SubscriptionService.get_subscription_info')
    def test_get_customer_subscription(self, mock_get_info, mock_client_query):
        """Admin GET /api/customers/<id>/subscription returns subscription info."""
        cust_id = uuid.uuid4()
        mock_customer = MagicMock(spec=Client)
        mock_customer.user_id = cust_id
        mock_client_query.get.return_value = mock_customer

        mock_get_info.return_value = {
            'plan_name': 'starter',
            'plan_display': 'Starter Plan',
            'status': 'active',
            'allowed_peers_count': 5,
            'installed_peers_count': 2,
            'remaining_peers_count': 3
        }

        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        resp = self.client.get(f'/api/customers/{cust_id}/subscription')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['subscription']['plan_name'], 'starter')
        self.assertEqual(data['subscription']['allowed_peers_count'], 5)

    @patch('extensions.db.session.commit')
    @patch('models.subscription_plan.SubscriptionPlan.query')
    @patch('models.client.Client.query')
    @patch('services.subscription_service.SubscriptionService.get_subscription_info')
    def test_update_customer_subscription(self, mock_get_info, mock_client_query, mock_plan_query, mock_commit):
        """Admin POST /api/customers/<id>/subscription/update updates plan, billing cycle, renewal date."""
        cust_id = uuid.uuid4()
        mock_customer = MagicMock(spec=Client)
        mock_customer.user_id = cust_id
        mock_customer.subscription_status = 'active'
        mock_client_query.get.return_value = mock_customer

        mock_plan = MagicMock(spec=SubscriptionPlan)
        mock_plan.id = 2
        mock_plan.name = 'pro'
        mock_plan_query.get.return_value = mock_plan

        mock_get_info.return_value = {
            'plan_name': 'pro',
            'plan_display': 'Pro Plan',
            'status': 'active',
            'allowed_peers_count': 15,
            'billing_cycle': 'yearly'
        }

        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        payload = {
            'plan_id': 2,
            'billing_cycle': 'yearly',
            'renewal_date': '2027-01-01',
            'status': 'active'
        }

        resp = self.client.post(
            f'/api/customers/{cust_id}/subscription/update',
            json=payload
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['subscription']['plan_name'], 'pro')
        self.assertEqual(mock_customer.plan_id, 2)
        self.assertEqual(mock_customer.billing_cycle, 'yearly')

    @patch('services.subscription_service.SubscriptionService.restore_active')
    @patch('services.subscription_service.SubscriptionService.get_subscription_info')
    @patch('models.client.Client.query')
    def test_activate_customer_subscription(self, mock_client_query, mock_get_info, mock_restore):
        """Admin POST /api/customers/<id>/subscription/activate activates customer."""
        cust_id = uuid.uuid4()
        mock_customer = MagicMock(spec=Client)
        mock_customer.user_id = cust_id
        mock_customer.username = 'john_doe'
        mock_client_query.get.return_value = mock_customer

        mock_restore.return_value = True
        mock_get_info.return_value = {
            'status': 'active',
            'is_active': True
        }

        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        resp = self.client.post(f'/api/customers/{cust_id}/subscription/activate', json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertIn('activated successfully', data['message'])
        mock_restore.assert_called_once()

    @patch('services.subscription_service.SubscriptionService.transition_to_inactive')
    @patch('services.subscription_service.SubscriptionService.get_subscription_info')
    @patch('models.client.Client.query')
    def test_suspend_customer_subscription(self, mock_client_query, mock_get_info, mock_suspend):
        """Admin POST /api/customers/<id>/subscription/suspend suspends customer."""
        cust_id = uuid.uuid4()
        mock_customer = MagicMock(spec=Client)
        mock_customer.user_id = cust_id
        mock_customer.username = 'john_doe'
        mock_client_query.get.return_value = mock_customer

        mock_suspend.return_value = True
        mock_get_info.return_value = {
            'status': 'inactive',
            'is_inactive': True
        }

        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        resp = self.client.post(f'/api/customers/{cust_id}/subscription/suspend', json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertIn('suspended successfully', data['message'])
        mock_suspend.assert_called_once()

    @patch('extensions.db.session.commit')
    @patch('utils.email.send_renewal_reminder_email')
    @patch('models.client.Client.query')
    def test_send_renewal_reminder(self, mock_client_query, mock_send_email, mock_commit):
        """Admin POST /api/customers/<id>/subscription/send-reminder triggers reminder email."""
        cust_id = uuid.uuid4()
        mock_customer = MagicMock(spec=Client)
        mock_customer.user_id = cust_id
        mock_customer.client_name = 'Acme Corp'
        mock_customer.client_email = 'billing@acme.com'
        mock_customer.renewal_date = datetime(2026, 9, 20)
        mock_customer.plan = MagicMock()
        mock_customer.plan.name = 'starter'
        mock_client_query.get.return_value = mock_customer

        mock_send_email.return_value = (True, None)

        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        resp = self.client.post(f'/api/customers/{cust_id}/subscription/send-reminder')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertIn('Renewal reminder sent', data['message'])
        mock_send_email.assert_called_once()


if __name__ == '__main__':
    unittest.main()
