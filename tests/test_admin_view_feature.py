import pytest
from app import create_app
from client_app import create_client_app
from flask import render_template
import uuid

@pytest.fixture
def admin_app():
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    return app

@pytest.fixture
def client_app():
    app = create_client_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    return app

def test_admin_app_static_fallback(admin_app):
    with admin_app.test_client() as c:
        # Admin root static asset
        r1 = c.get('/static/logo.png')
        assert r1.status_code == 200, f"Expected 200 for logo.png, got {r1.status_code}"
        
        # Client static assets served through admin fallback
        r2 = c.get('/static/js/peer_details.js')
        assert r2.status_code == 200, f"Expected 200 for js/peer_details.js, got {r2.status_code}"
        
        r3 = c.get('/static/css/peer_details.css')
        assert r3.status_code == 200, f"Expected 200 for css/peer_details.css, got {r3.status_code}"

        r4 = c.get('/static/js/firewall.js')
        assert r4.status_code == 200, f"Expected 200 for js/firewall.js, got {r4.status_code}"

        r5 = c.get('/static/css/firewall.css')
        assert r5.status_code == 200, f"Expected 200 for css/firewall.css, got {r5.status_code}"

        r6 = c.get('/static/js/web_filter.js')
        assert r6.status_code == 200, f"Expected 200 for js/web_filter.js, got {r6.status_code}"

        r7 = c.get('/static/js/aliases.js')
        assert r7.status_code == 200, f"Expected 200 for js/aliases.js, got {r7.status_code}"

def test_client_app_static_assets(client_app):
    with client_app.test_client() as c:
        r1 = c.get('/static/logo.png')
        assert r1.status_code == 200
        r2 = c.get('/static/js/peer_details.js')
        assert r2.status_code == 200
        r3 = c.get('/static/css/peer_details.css')
        assert r3.status_code == 200

def test_admin_view_unauthenticated_redirect(admin_app):
    with admin_app.test_client() as c:
        dummy_cid = str(uuid.uuid4())
        r1 = c.get(f'/admin/view/{dummy_cid}/peers/dummy-peer-id')
        assert r1.status_code == 302
        assert '/login' in r1.headers.get('Location', '')

        r2 = c.get(f'/admin/view/{dummy_cid}/peers/dummy-peer-id/firewall')
        assert r2.status_code == 302

        r3 = c.get(f'/admin/view/{dummy_cid}/peers/dummy-peer-id/web-filter')
        assert r3.status_code == 302

        r4 = c.get(f'/admin/view/{dummy_cid}/peers/aliases')
        assert r4.status_code == 302

def test_admin_view_authenticated_nonexistent_peer(admin_app):
    with admin_app.test_client() as c:
        with c.session_transaction() as sess:
            sess['admin_logged_in'] = True
            sess['admin_role'] = 'admin'
            sess['admin_username'] = 'admin'

        dummy_cid = str(uuid.uuid4())
        r = c.get(f'/admin/view/{dummy_cid}/peers/nonexistent-peer')
        assert r.status_code == 302
        assert f'/customers/{dummy_cid}' in r.headers.get('Location', '')

def test_admin_view_api_unauthorized_when_not_logged_in(admin_app):
    with admin_app.test_client() as c:
        dummy_cid = str(uuid.uuid4())
        r = c.get(f'/admin/view/{dummy_cid}/api/peers')
        assert r.status_code == 302

def test_template_rendering_admin_view(admin_app):
    """Test that all 4 templates render without syntax/Jinja errors in admin view mode."""
    sidebar_peers_data = [
        {'id': 'test-peer-123', 'name': 'Test Peer 1', 'connected': True, 'ip': '100.64.0.5', 'status_title': 'Connected'},
        {'id': 'test-peer-456', 'name': 'Test Peer 2', 'connected': False, 'ip': '100.64.0.6', 'status_title': 'Offline'}
    ]
    with admin_app.test_request_context():
        # 1. Peer Details
        html1 = render_template(
            'peer_details.html',
            peer_id='test-peer-123',
            peer_name='Test Peer 1',
            customer_name='Acme Corp',
            is_online=True,
            peer_ip='100.64.0.5',
            peer_public_ip='203.0.113.1',
            peer_os='Linux',
            peer_version='1.0.0',
            peer_uptime='2d 04:12:00',
            peer_uptime_seconds=187920,
            peer_last_seen='17/09/2026 12:00:00',
            peer_network='192.168.1.0/24',
            peer_route_id='route-123',
            peer_route_network_id='net-123',
            can_manage_services=False,
            admin_view=True,
            admin_customer_id='00000000-0000-0000-0000-000000000001',
            api_base='/admin/view/00000000-0000-0000-0000-000000000001',
            sidebar_peers=sidebar_peers_data,
            sidebar_online_count=1,
            sidebar_offline_count=1,
        )
        assert 'Admin View' in html1
        assert 'btn-edit-name' not in html1
        assert 'btn-edit-network' not in html1
        assert 'sidebar-peer-test-peer-123' in html1
        assert 'sidebar-peer-test-peer-456' in html1
        assert 'Test Peer 1' in html1

        # 2. Firewall
        html2 = render_template(
            'firewall.html',
            peer_id='test-peer-123',
            peer_name='Test Peer 1',
            customer_name='Acme Corp',
            is_online=True,
            vpn_only=False,
            admin_view=True,
            admin_customer_id='00000000-0000-0000-0000-000000000001',
            api_base='/admin/view/00000000-0000-0000-0000-000000000001',
            sidebar_peers=sidebar_peers_data,
            sidebar_online_count=1,
            sidebar_offline_count=1,
        )
        assert 'Admin View' in html2
        assert 'id="add-rule-btn"' not in html2
        assert 'sidebar-peer-test-peer-123' in html2

        # 3. Web Filter
        html3 = render_template(
            'web_filter.html',
            peer_id='test-peer-123',
            peer_name='Test Peer 1',
            customer_name='Acme Corp',
            is_online=True,
            vpn_only=False,
            admin_view=True,
            admin_customer_id='00000000-0000-0000-0000-000000000001',
            api_base='/admin/view/00000000-0000-0000-0000-000000000001',
            sidebar_peers=sidebar_peers_data,
            sidebar_online_count=1,
            sidebar_offline_count=1,
        )
        assert 'Admin View' in html3
        assert 'id="add-rule-btn"' not in html3
        assert 'sidebar-peer-test-peer-123' in html3

        # 4. Aliases
        html4 = render_template(
            'aliases.html',
            customer_name='Acme Corp',
            peers=sidebar_peers_data,
            selected_peer_id='test-peer-123',
            peer_id='test-peer-123',
            peer_name='Test Peer 1',
            is_online=True,
            admin_view=True,
            admin_customer_id='00000000-0000-0000-0000-000000000001',
            api_base='/admin/view/00000000-0000-0000-0000-000000000001',
            sidebar_peers=sidebar_peers_data,
            sidebar_online_count=1,
            sidebar_offline_count=1,
        )
        assert 'Admin View' in html4
        assert 'id="add-list-btn"' not in html4
        assert 'sidebar-peer-test-peer-123' in html4
        assert 'sidebar-peer-test-peer-456' in html4

def test_template_rendering_client_view(client_app):
    """Test that all 4 templates render without issues in standard client mode (admin_view=False)."""
    with client_app.test_request_context():
        # 1. Peer Details
        html1 = render_template(
            'peer_details.html',
            peer_id='test-peer-123',
            peer_name='Test Peer',
            customer_name='Acme Corp',
            is_online=True,
            peer_ip='100.64.0.5',
            peer_public_ip='203.0.113.1',
            peer_os='Linux',
            peer_version='1.0.0',
            peer_uptime='2d 04:12:00',
            peer_uptime_seconds=187920,
            peer_last_seen='17/09/2026 12:00:00',
            peer_network='192.168.1.0/24',
            peer_route_id='route-123',
            peer_route_network_id='net-123',
            can_manage_services=True,
            admin_view=False,
            api_base='',
        )
        assert 'Admin View' not in html1
        assert 'btn-edit-name' in html1
        assert 'btn-edit-network' in html1

        # 2. Firewall
        html2 = render_template(
            'firewall.html',
            peer_id='test-peer-123',
            peer_name='Test Peer',
            customer_name='Acme Corp',
            is_online=True,
            vpn_only=False,
            admin_view=False,
            api_base='',
        )
        assert 'Admin View' not in html2
        assert 'id="add-rule-btn"' in html2

        # 3. Web Filter
        html3 = render_template(
            'web_filter.html',
            peer_id='test-peer-123',
            peer_name='Test Peer',
            customer_name='Acme Corp',
            is_online=True,
            vpn_only=False,
            admin_view=False,
            api_base='',
        )
        assert 'Admin View' not in html3
        assert 'id="add-rule-btn"' in html3

        # 4. Aliases
        html4 = render_template(
            'aliases.html',
            customer_name='Acme Corp',
            peers=[{'id': 'test-peer-123', 'name': 'Test Peer', 'connected': True, 'ip': '100.64.0.5'}],
            selected_peer_id='test-peer-123',
            peer_id='test-peer-123',
            peer_name='Test Peer',
            is_online=True,
            admin_view=False,
            api_base='',
        )
        assert 'Admin View' not in html4
        assert 'id="add-list-btn"' in html4
