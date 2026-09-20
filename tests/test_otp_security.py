import time
import unittest
from unittest.mock import patch
from app import create_app
from client_app import create_client_app


class TestOtpSecurity(unittest.TestCase):

    def setUp(self):
        self.admin_app = create_app()
        self.admin_app.config['TESTING'] = True
        self.admin_app.config['WTF_CSRF_ENABLED'] = False
        self.admin_app.config['RATELIMIT_ENABLED'] = False
        self.admin_client = self.admin_app.test_client()

        self.client_app = create_client_app()
        self.client_app.config['TESTING'] = True
        self.client_app.config['WTF_CSRF_ENABLED'] = False
        self.client_app.config['RATELIMIT_ENABLED'] = False
        self.client_client = self.client_app.test_client()

    def test_verify_email_attempt_limit(self):
        """5 failed attempts on /verify-email must invalidate session and redirect to register."""
        with self.client_client.session_transaction() as sess:
            sess['reg_data'] = {
                'username': 'newuser',
                'password': 'password123',
                'client_name': 'New User',
                'client_company_name': None,
                'client_email': 'newuser@example.com',
                'client_phone_number': '+1234567890',
                'client_country': None,
                'subscription': 'basic'
            }
            sess['reg_verification'] = {
                'code': '654321',
                'email': 'newuser@example.com',
                'expires_at': time.time() + 600,
                'attempts': 0
            }

        for _ in range(4):
            res = self.client_client.post('/verify-email', data={'code': '000000'})
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'Invalid verification code', res.data)

        # 5th failed attempt should invalidate session and redirect to register
        res_5 = self.client_client.post('/verify-email', data={'code': '000000'}, follow_redirects=True)
        self.assertEqual(res_5.status_code, 200)
        self.assertIn(b'Too many failed attempts. Please register again.', res_5.data)

        with self.client_client.session_transaction() as sess:
            self.assertNotIn('reg_verification', sess)
            self.assertNotIn('reg_data', sess)

    def test_reset_password_attempt_limit(self):
        """5 failed attempts on /reset-password must invalidate session and redirect to forgot_password."""
        with self.client_client.session_transaction() as sess:
            sess['reset_password_data'] = {
                'client_id': '00000000-0000-0000-0000-000000000001',
                'email': 'user@example.com',
                'code': '123456',
                'expires_at': time.time() + 600,
                'attempts': 0
            }

        for _ in range(4):
            res = self.client_client.post('/reset-password', data={
                'code': '000000',
                'new_password': 'newpassword123',
                'confirm_password': 'newpassword123'
            })
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'Invalid verification code', res.data)

        # 5th failed attempt should invalidate session and redirect to forgot_password
        res_5 = self.client_client.post('/reset-password', data={
            'code': '000000',
            'new_password': 'newpassword123',
            'confirm_password': 'newpassword123'
        }, follow_redirects=True)
        self.assertEqual(res_5.status_code, 200)
        self.assertIn(b'Too many failed attempts. Please request a new code.', res_5.data)

        with self.client_client.session_transaction() as sess:
            self.assertNotIn('reset_password_data', sess)


if __name__ == '__main__':
    unittest.main()
