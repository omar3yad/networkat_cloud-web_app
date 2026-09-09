import sys
import os

# Add application path
sys.path.insert(0, '/app')

from client_app import create_client_app
from flask import render_template, url_for

app = create_client_app()
app.config['TESTING'] = True
client = app.test_client()

print("=================================================================")
print("  PHASE 5: COMPREHENSIVE TEST SUITE FOR SD-WAN CLIENT WEB APP   ")
print("=================================================================")

# ----------------------------------------------------------------------
# 1. TEMPLATE RENDERING TESTS
# ----------------------------------------------------------------------
print("\n[1/5] Testing Template Rendering...")
templates_tests = [
    ('login.html', {}),
    ('register.html', {}),
    ('forgot_password.html', {}),
    ('verify_email.html', {}),
    ('reset_password.html', {}),
    ('client_base.html', {'customer_name': 'Acme Corp', 'sidebar_peers': [{'id': 'p1', 'name': 'Edge Router 1', 'connected': True}]}),
    ('dashboard.html', {'customer_name': 'Acme Corp', 'total_edges': 4, 'online_edges': 3, 'offline_edges': 1, 'netbird_peers': []}),
    ('peers.html', {'customer_name': 'Acme Corp', 'sidebar_peers': []}),
    ('peer_details.html', {'peer_id': 'p1', 'peer_name': 'Edge Router 1', 'customer_name': 'Acme Corp', 'is_online': True, 'peer_network': '192.168.10.0/24', 'peer_route_id': 'r1', 'peer_route_network_id': 'rn1', 'peer_last_seen': '01/01/2026'}),
    ('aliases.html', {'customer_name': 'Acme Corp', 'peers': [{'id': 'p1', 'name': 'Edge Router 1', 'connected': True}], 'selected_peer_id': 'p1', 'peer_id': 'p1', 'peer_name': 'Edge Router 1', 'is_online': True}),
    ('firewall.html', {'peer_id': 'p1', 'peer_name': 'Edge Router 1', 'customer_name': 'Acme Corp', 'is_online': True, 'vpn_only': False}),
    ('web_filter.html', {'peer_id': 'p1', 'peer_name': 'Edge Router 1', 'customer_name': 'Acme Corp', 'is_online': True, 'vpn_only': False}),
    ('filtering.html', {'peer_id': 'p1', 'peer_name': 'Edge Router 1', 'customer_name': 'Acme Corp', 'is_online': True}),
    ('profile.html', {'client': {'client_name': 'Acme User', 'username': 'acme', 'client_email': 'user@acme.com', 'client_company_name': 'Acme Corp', 'subscription': 'Basic', 'active': True}}),
]

with app.test_request_context('/'):
    for tmpl, ctx in templates_tests:
        try:
            rendered = render_template(tmpl, **ctx)
            assert len(rendered) > 0, f"Rendered output was empty for {tmpl}"
            print(f"  ✓ {tmpl:22} rendered successfully ({len(rendered)} bytes)")
        except Exception as e:
            print(f"  ✗ ERROR in {tmpl}: {e}")
            sys.exit(1)

# ----------------------------------------------------------------------
# 2. STATIC ASSETS SERVING TESTS
# ----------------------------------------------------------------------
print("\n[2/5] Testing Static CSS & JS Assets...")
static_files = [
    'css/base.css',
    'css/dashboard.css',
    'css/peers.css',
    'css/peer_details.css',
    'css/firewall.css',
    'css/aliases.css',
    ('css/web_filter.css'),
    ('css/filtering.css'),
    ('css/profile.css'),
    ('js/network_math.js'),
    ('js/toast.js'),
    ('js/dashboard.js'),
    ('js/peers.js'),
    ('js/peer_details.js'),
    ('js/firewall.js'),
    ('js/aliases.js'),
    ('js/web_filter.js'),
    ('js/filtering.js'),
    ('js/profile.js'),
]

for sf in static_files:
    resp = client.get(f'/static/{sf}')
    if resp.status_code == 200 and len(resp.data) > 0:
        print(f"  ✓ /static/{sf:22} HTTP 200 OK ({len(resp.data)} bytes)")
    else:
        print(f"  ✗ FAILED static file /static/{sf}: HTTP {resp.status_code}")
        sys.exit(1)

# ----------------------------------------------------------------------
# 3. ROUTE & ENDPOINT NAMING INTEGRITY
# ----------------------------------------------------------------------
print("\n[3/5] Testing Endpoint & URL Resolution...")
with app.test_request_context('/'):
    endpoints_to_test = [
        ('client.login', {}, '/login'),
        ('client.logout', {}, '/logout'),
        ('client.register', {}, '/register'),
        ('client.verify_email', {}, '/verify-email'),
        ('client.resend_code', {}, '/resend-code'),
        ('client.forgot_password', {}, '/forgot-password'),
        ('client.reset_password', {}, '/reset-password'),
        ('client.resend_reset_code', {}, '/resend-reset-code'),
        ('client.dashboard', {}, '/'),
        ('client.peers_page', {}, '/peers'),
        ('client.aliases_page', {}, '/peers/aliases'),
        ('client.peer_details', {'peer_id': 'peer123'}, '/peers/peer123'),
        ('client.peer_firewall', {'peer_id': 'peer123'}, '/peers/peer123/firewall'),
        ('client.peer_aliases', {'peer_id': 'peer123'}, '/peers/peer123/aliases'),
        ('client.peer_web_filter', {'peer_id': 'peer123'}, '/peers/peer123/web-filter'),
        ('client.peer_filtering', {'peer_id': 'peer123'}, '/peers/peer123/filtering'),
        ('client.proxy_peers', {}, '/api/peers'),
        ('client.get_peers_status_api', {}, '/api/peers/status'),
        ('client.proxy_get_routes', {}, '/api/v2/netbird/routes'),
        ('client.profile', {}, '/profile'),
        ('client.change_password', {}, '/profile/change-password'),
    ]

    for ep, kwargs, expected_url in endpoints_to_test:
        generated = url_for(ep, **kwargs)
        assert generated == expected_url, f"Endpoint {ep} generated '{generated}' instead of '{expected_url}'"
        print(f"  ✓ url_for('{ep}'): {generated}")

# ----------------------------------------------------------------------
# 4. PYTHON NETWORK VALIDATOR UNIT TESTS
# ----------------------------------------------------------------------
print("\n[4/5] Testing Python Network Validators (utils/network_validators.py)...")
from utils.network_validators import validate_address_spec, validate_port_spec, validate_route_network

# Address spec tests
assert validate_address_spec("192.168.1.1") == ["192.168.1.1"]
assert validate_address_spec("192.168.1.0/24") == ["192.168.1.0/24"]
assert validate_address_spec("@my_alias") == ["@alias_my_alias"]
assert validate_address_spec(None) is None
print("  ✓ validate_address_spec passed")

# Port spec tests
assert validate_port_spec("80,443") == "80,443"
assert validate_port_spec("8080-8090") == "8080-8090"
assert validate_port_spec("") is None
print("  ✓ validate_port_spec passed")

# Mathematical normalization tests
v, msg, norm = validate_route_network("192.168.10.2/24", "p1", {"p1", "p2"}, [])
assert v is True and norm == "192.168.10.0/24", f"Normalization failed: {norm}"

v, msg, norm = validate_route_network("10.50.25.65/26", "p1", {"p1", "p2"}, [])
assert v is True and norm == "10.50.25.64/26", f"Normalization failed: {norm}"

# Collision test
all_routes = [{"peer": "p2", "network": "192.168.10.0/24"}]
v, msg, norm = validate_route_network("192.168.10.5/24", "p1", {"p1", "p2"}, all_routes)
assert v is False and "Subnet already in use" in msg, f"Collision check failed: {v}, {msg}"
print("  ✓ Mathematical subnet normalization and collision check in validate_route_network passed")

# ----------------------------------------------------------------------
# 5. LIVE HTTP RESPONSE TESTS
# ----------------------------------------------------------------------
print("\n[5/5] Testing HTTP Request Handling...")
res = client.get('/login')
assert res.status_code == 200, f"Expected 200 on /login, got {res.status_code}"
print("  ✓ GET /login -> HTTP 200 OK")

res = client.get('/register')
assert res.status_code == 200, f"Expected 200 on /register, got {res.status_code}"
print("  ✓ GET /register -> HTTP 200 OK")

res = client.get('/forgot-password')
assert res.status_code == 200, f"Expected 200 on /forgot-password, got {res.status_code}"
print("  ✓ GET /forgot-password -> HTTP 200 OK")

print("\n=================================================================")
print("  ALL TESTS PASSED WITH 100% SUCCESS AND ZERO REGRESSIONS!      ")
print("=================================================================")
