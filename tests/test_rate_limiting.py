import unittest
from app import create_app
from client_app import create_client_app


class TestRateLimiting(unittest.TestCase):

    def setUp(self):
        self.admin_app = create_app()
        self.admin_app.config['TESTING'] = True
        self.admin_app.config['WTF_CSRF_ENABLED'] = False
        self.admin_app.config['RATELIMIT_ENABLED'] = True
        self.admin_client = self.admin_app.test_client()

        self.client_app = create_client_app()
        self.client_app.config['TESTING'] = True
        self.client_app.config['WTF_CSRF_ENABLED'] = False
        self.client_app.config['RATELIMIT_ENABLED'] = True
        self.client_client = self.client_app.test_client()

    def test_admin_login_rate_limit_exceeded(self):
        """10 POST requests allowed per minute; 11th should return 429."""
        for i in range(10):
            res = self.admin_client.post('/login', data={'username': 'wrong_admin', 'password': 'bad_password'})
            self.assertNotEqual(res.status_code, 429, f"Request {i+1} was unexpectedly rate limited")

        # 11th request should hit rate limit
        res_11 = self.admin_client.post('/login', data={'username': 'wrong_admin', 'password': 'bad_password'})
        self.assertEqual(res_11.status_code, 429)

    def test_client_login_rate_limit_exceeded(self):
        """10 POST requests allowed per minute; 11th should return 429."""
        for i in range(10):
            res = self.client_client.post('/login', data={'username': 'wrong_user', 'password': 'bad_password'})
            self.assertNotEqual(res.status_code, 429, f"Request {i+1} was unexpectedly rate limited")

        # 11th request should hit rate limit
        res_11 = self.client_client.post('/login', data={'username': 'wrong_user', 'password': 'bad_password'})
        self.assertEqual(res_11.status_code, 429)

    def test_client_forgot_password_rate_limit(self):
        """5 POST requests allowed per minute on /forgot-password; 6th returns 429."""
        for i in range(5):
            res = self.client_client.post('/forgot-password', data={'identifier': f'user_{i}@example.com'})
            self.assertNotEqual(res.status_code, 429, f"Request {i+1} was unexpectedly rate limited")

        res_6 = self.client_client.post('/forgot-password', data={'identifier': 'user_6@example.com'})
        self.assertEqual(res_6.status_code, 429)

    def test_client_send_2fa_otp_rate_limit_json_response(self):
        """5 POST requests allowed per minute on /send-2fa-email-otp; 6th returns JSON 429."""
        # Setup session for pending 2fa with valid UUID format
        with self.client_client.session_transaction() as sess:
            sess['pending_2fa'] = {'type': 'client', 'client_id': '00000000-0000-0000-0000-000000000001'}


        for i in range(5):
            res = self.client_client.post('/send-2fa-email-otp', json={})
            self.assertNotEqual(res.status_code, 429, f"Request {i+1} was unexpectedly rate limited")

        res_6 = self.client_client.post('/send-2fa-email-otp', json={})
        self.assertEqual(res_6.status_code, 429)
        self.assertTrue(res_6.is_json)
        self.assertFalse(res_6.get_json().get('success'))


if __name__ == '__main__':
    unittest.main()
