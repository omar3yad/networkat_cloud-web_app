import time
import unittest
from unittest.mock import patch
from client_app import create_client_app
from extensions import db
from models.client import Client


class TestAntiAbuseRegistration(unittest.TestCase):

    def setUp(self):
        self.client_app = create_client_app()
        self.client_app.config['TESTING'] = True
        self.client_app.config['WTF_CSRF_ENABLED'] = False
        self.client_app.config['RATELIMIT_ENABLED'] = False
        self.test_client = self.client_app.test_client()

    def test_register_bypasses_phone_otp_when_whatsapp_unconfigured(self):
        """When WhatsApp token is unset, registration must not block customer and go to /verify-card."""
        ts = int(time.time())
        with patch('client.routes.auth.is_whatsapp_configured', return_value=False):
            res = self.test_client.post('/register', data={
                'username': f'autouser_{ts}',
                'password': 'password123',
                'confirm_password': 'password123',
                'client_name': 'Auto Verified',
                'client_email': f'autouser_{ts}@example.com',
                'client_phone_number': f'+2019999{ts % 100000:05d}',
            }, follow_redirects=False)

            self.assertEqual(res.status_code, 302)
            self.assertIn('/verify-card', res.headers['Location'])

            with self.test_client.session_transaction() as sess:
                self.assertTrue(sess['reg_data']['phone_verified'])

    def test_phone_verification_success(self):
        """Valid WhatsApp OTP code should verify phone and advance to /verify-card."""
        with self.test_client.session_transaction() as sess:
            sess['reg_data'] = {
                'username': 'antiabuse_user1',
                'password': 'password123',
                'client_name': 'Anti Abuse User',
                'client_email': 'antiabuse1@example.com',
                'client_phone_number': '+201000000001',
                'subscription': 'basic',
                'is_trial': True,
                'phone_verified': False
            }
            sess['reg_phone_verification'] = {
                'code': '123456',
                'phone': '+201000000001',
                'expires_at': time.time() + 600,
                'attempts': 0
            }

        res = self.test_client.post('/verify-phone', data={'code': '123456'}, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/verify-card', res.headers['Location'])

        with self.test_client.session_transaction() as sess:
            self.assertTrue(sess['reg_data']['phone_verified'])
            self.assertNotIn('reg_phone_verification', sess)

    def test_phone_verification_max_attempts(self):
        """5 incorrect WhatsApp OTP attempts must invalidate session and redirect to register."""
        with self.test_client.session_transaction() as sess:
            sess['reg_data'] = {
                'username': 'antiabuse_user2',
                'password': 'password123',
                'client_name': 'Anti Abuse User 2',
                'client_email': 'antiabuse2@example.com',
                'client_phone_number': '+201000000002',
                'subscription': 'basic',
                'is_trial': True,
                'phone_verified': False
            }
            sess['reg_phone_verification'] = {
                'code': '123456',
                'phone': '+201000000002',
                'expires_at': time.time() + 600,
                'attempts': 4
            }

        res = self.test_client.post('/verify-phone', data={'code': '999999'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Too many failed attempts. Please register again.', res.data)

        with self.test_client.session_transaction() as sess:
            self.assertNotIn('reg_data', sess)
            self.assertNotIn('reg_phone_verification', sess)

    def test_verify_card_requires_phone_verified(self):
        """Accessing /verify-card without phone verification must redirect to register."""
        with self.test_client.session_transaction() as sess:
            sess['reg_data'] = {
                'username': 'unverified_phone',
                'phone_verified': False
            }

        res = self.test_client.get('/verify-card', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/register', res.headers['Location'])

    def test_verify_card_duplicate_fingerprint_rejected(self):
        """Submitting a card whose fingerprint is already in the database must be rejected."""
        from utils.stripe_service import verify_and_extract_card
        card_info, _ = verify_and_extract_card('pm_card_duplicate_test')
        dup_fingerprint = card_info['fingerprint']

        with self.client_app.app_context():
            # Check or create an existing client with this card fingerprint
            existing = Client.query.filter(
                (Client.username == 'cardholder_original') |
                (Client.client_email == 'original_card@example.com') |
                (Client.card_fingerprint == dup_fingerprint)
            ).first()
            if not existing:
                existing = Client(
                    username='cardholder_original',
                    password_hashed='hashed',
                    client_name='Original Cardholder',
                    client_email='original_card@example.com',
                    card_fingerprint=dup_fingerprint,
                    is_trial=True
                )
                db.session.add(existing)
            else:
                existing.card_fingerprint = dup_fingerprint
            db.session.commit()

        with self.test_client.session_transaction() as sess:
            sess['reg_data'] = {
                'username': 'abuser_clone',
                'password': 'password123',
                'client_name': 'Abuser Clone',
                'client_email': 'abuser@example.com',
                'client_phone_number': '+201000000003',
                'phone_verified': True
            }

        res = self.test_client.post('/verify-card', data={'payment_method_id': 'pm_card_duplicate_test'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'This payment card has already been used for another account.', res.data)

        # Ensure reg_data does NOT have card_verified
        with self.test_client.session_transaction() as sess:
            self.assertFalse(sess['reg_data'].get('card_verified', False))

    def test_verify_card_success_advances_to_email(self):
        """A new unique card saves the fingerprint and advances to /verify-email."""
        fresh_pm = f'pm_card_fresh_{int(time.time())}'
        from utils.stripe_service import verify_and_extract_card
        card_info, _ = verify_and_extract_card(fresh_pm)
        expected_fp = card_info['fingerprint']

        with self.test_client.session_transaction() as sess:
            sess['reg_data'] = {
                'username': 'valid_trial_user',
                'password': 'password123',
                'client_name': 'Valid Trial User',
                'client_email': 'valid_trial@example.com',
                'client_phone_number': '+201000000004',
                'phone_verified': True
            }

        with patch('client.routes.auth.send_verification_email') as mock_email:
            mock_email.return_value = (True, None)

            res = self.test_client.post('/verify-card', data={'payment_method_id': fresh_pm}, follow_redirects=False)
            self.assertEqual(res.status_code, 302)
            self.assertIn('/verify-email', res.headers['Location'])

        with self.test_client.session_transaction() as sess:
            self.assertTrue(sess['reg_data'].get('card_verified'))
            self.assertEqual(sess['reg_data'].get('card_fingerprint'), expected_fp)
            self.assertIn('reg_verification', sess)

    def test_paid_vs_trial_starter_client(self):
        """Verify is_paid property differentiates between paying Starter and unpaid Starter trial."""
        with self.client_app.app_context():
            # Trial Starter Client
            trial_client = Client(
                username='starter_trial_test',
                password_hashed='hashed',
                client_name='Trial User',
                client_email='starter_trial@example.com',
                subscription='starter',
                subscription_status='active',
                is_trial=True
            )
            # Paid Starter Client
            paid_client = Client(
                username='starter_paid_test',
                password_hashed='hashed',
                client_name='Paid User',
                client_email='starter_paid@example.com',
                subscription='starter',
                subscription_status='active',
                is_trial=False
            )

            self.assertFalse(trial_client.is_paid)
            self.assertTrue(paid_client.is_paid)


if __name__ == '__main__':
    unittest.main()
