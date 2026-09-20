import re
import unittest
from app import create_app
from client_app import create_client_app


class TestCsrfProtection(unittest.TestCase):

    def setUp(self):
        # Admin App with CSRF explicitly enabled
        self.admin_app = create_app()
        self.admin_app.config['TESTING'] = True
        self.admin_app.config['WTF_CSRF_ENABLED'] = True
        self.admin_app.config['SECRET_KEY'] = 'test-secret-key-csrf-validation'
        self.admin_client = self.admin_app.test_client()

        # Client App with CSRF explicitly enabled
        self.client_app = create_client_app()
        self.client_app.config['TESTING'] = True
        self.client_app.config['WTF_CSRF_ENABLED'] = True
        self.client_app.config['SECRET_KEY'] = 'test-secret-key-csrf-validation'
        self.client_client = self.client_app.test_client()

    def _extract_csrf_from_html(self, html_text):
        match = re.search(r'name="csrf[_-]token"\s+(?:value|content)="([^"]+)"', html_text)
        if not match:
            match = re.search(r'content="([^"]+)"\s+name="csrf[_-]token"', html_text)
        if match:
            return match.group(1)
        return None

    def test_admin_post_without_csrf_token_blocked(self):
        """Admin POST request without CSRF token must return 400 Bad Request."""
        res = self.admin_client.post('/login', data={'username': 'admin', 'password': 'pwd'})
        self.assertEqual(res.status_code, 400)

    def test_admin_post_with_valid_form_token_accepted(self):
        """Admin POST request with CSRF token rendered in form must pass CSRF validation."""
        get_res = self.admin_client.get('/login')
        token = self._extract_csrf_from_html(get_res.data.decode('utf-8'))
        self.assertIsNotNone(token, "CSRF token must be rendered in admin login form")

        res = self.admin_client.post(
            '/login',
            data={'username': 'admin', 'password': 'wrongpassword', 'csrf_token': token}
        )
        self.assertNotEqual(res.status_code, 400)

    def test_admin_api_post_with_header_accepted(self):
        """Admin API request with X-CSRFToken header must pass CSRF validation."""
        get_res = self.admin_client.get('/login')
        token = self._extract_csrf_from_html(get_res.data.decode('utf-8'))
        self.assertIsNotNone(token, "CSRF token must be available from admin session/head")

        res = self.admin_client.post(
            '/customers/create',
            json={'username': 'test'},
            headers={'X-CSRFToken': token}
        )
        self.assertNotEqual(res.status_code, 400)

    def test_client_post_without_csrf_token_blocked(self):
        """Client POST request without CSRF token must return 400 Bad Request."""
        res = self.client_client.post('/login', data={'username': 'user', 'password': 'pwd'})
        self.assertEqual(res.status_code, 400)

    def test_client_post_with_valid_form_token_accepted(self):
        """Client POST request with CSRF token rendered in form must pass CSRF validation."""
        get_res = self.client_client.get('/login')
        token = self._extract_csrf_from_html(get_res.data.decode('utf-8'))
        self.assertIsNotNone(token, "CSRF token must be rendered in client login form")

        res = self.client_client.post(
            '/login',
            data={'username': 'user', 'password': 'wrongpassword', 'csrf_token': token}
        )
        self.assertNotEqual(res.status_code, 400)

    def test_client_api_post_with_header_accepted(self):
        """Client API mutation with X-CSRFToken header must pass CSRF validation."""
        get_res = self.client_client.get('/login')
        token = self._extract_csrf_from_html(get_res.data.decode('utf-8'))
        self.assertIsNotNone(token, "CSRF token must be available from client session/head")

        res = self.client_client.post(
            '/send-2fa-email-otp',
            json={},
            headers={'X-CSRFToken': token}
        )
        self.assertNotEqual(res.status_code, 400)

    def test_safe_methods_not_blocked(self):
        """Safe methods (GET, HEAD, OPTIONS) must not require CSRF token."""
        res_admin = self.admin_client.get('/login')
        self.assertEqual(res_admin.status_code, 200)

        res_client = self.client_client.get('/login')
        self.assertEqual(res_client.status_code, 200)
