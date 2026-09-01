import re
import time
import requests
from threading import Lock
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app

from models import Token, Client, Edge, FirewallRule
from extensions import db
from services.edge_service import EdgeService
from services.customer_service import CustomerService
import random
from utils.email import send_verification_email, send_password_reset_email

client_bp = Blueprint('client', __name__, template_folder='templates', static_folder='static')
customer_service = CustomerService()
edge_service = EdgeService()

# --------------------------------------------------------------------------
# Global Caches, Locks & ThreadPool
# --------------------------------------------------------------------------
executor = ThreadPoolExecutor(max_workers=20)
_cache_lock = Lock()

import os
import json

def _read_file_cache(cache_key):
    """Reads a shared cache file from /tmp/ and returns its parsed JSON payload and timestamp."""
    path = f"/tmp/nbcache_{cache_key}.json"
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
                return data.get("payload"), data.get("timestamp", 0)
    except Exception:
        pass
    return None, 0

def _write_file_cache(cache_key, payload):
    """Writes a shared cache payload to a JSON file in /tmp/ atomically."""
    path = f"/tmp/nbcache_{cache_key}.json"
    temp_path = f"{path}.tmp"
    try:
        data = {
            "payload": payload,
            "timestamp": time.time()
        }
        with open(temp_path, 'w') as f:
            json.dump(data, f)
        os.replace(temp_path, path)
    except Exception:
        pass

def _is_revalidating(customer_id):
    path = f"/tmp/nbstatus_reval_{customer_id}"
    try:
        if os.path.exists(path):
            # If it's less than 15 seconds old, assume it's still running
            if time.time() - os.path.getmtime(path) < 15:
                return True
    except Exception:
        pass
    return False

def _start_revalidating(customer_id):
    path = f"/tmp/nbstatus_reval_{customer_id}"
    try:
        with open(path, 'w') as f:
            f.write(str(time.time()))
    except Exception:
        pass

def _stop_revalidating(customer_id):
    path = f"/tmp/nbstatus_reval_{customer_id}"
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

_CUSTOMER_GROUPS_CACHE = {}
_STATUS_CACHE_LOCK = Lock()
_FIREWALL_RULES_CACHE = {}         # { peer_id: (live_rules, agent_online, timestamp) }
_FIREWALL_CACHE_LOCK = Lock()
_FIREWALL_REVALIDATING = set()     # set of peer_ids currently revalidating in background

import os
import json
import glob

_OVERRIDES_LOCK = Lock()

def _get_name_override(peer_id):
    path = f"/tmp/peer_name_{peer_id}.json"
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
                name, ts = data[0], data[1]
                if time.time() - ts < 45:
                    return name
                else:
                    try:
                        os.remove(path)
                    except Exception:
                        pass
    except Exception:
        pass
    return None

def _set_name_override(peer_id, name):
    path = f"/tmp/peer_name_{peer_id}.json"
    try:
        with open(path, 'w') as f:
            json.dump([name, time.time()], f)
    except Exception:
        pass

def _get_route_override(peer_id):
    path = f"/tmp/peer_route_{peer_id}.json"
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
                route, ts = data[0], data[1]
                if time.time() - ts < 45:
                    return route
                else:
                    try:
                        os.remove(path)
                    except Exception:
                        pass
    except Exception:
        pass
    return None

def _set_route_override(peer_id, route):
    path = f"/tmp/peer_route_{peer_id}.json"
    try:
        with open(path, 'w') as f:
            json.dump([route, time.time()], f)
    except Exception:
        pass

def _get_active_route_overrides():
    overrides = {}
    now = time.time()
    for filepath in glob.glob("/tmp/peer_route_*.json"):
        try:
            filename = os.path.basename(filepath)
            peer_id = filename[len("peer_route_"):-len(".json")]
            with open(filepath, 'r') as f:
                data = json.load(f)
                route, ts = data[0], data[1]
                if now - ts < 45:
                    overrides[peer_id] = route
                else:
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
        except Exception:
            pass
    return overrides



def _validate_address_spec(addr_str):
    import re
    import ipaddress
    if not addr_str:
        return None
    
    parts = [p.strip() for p in addr_str.split(',') if p.strip()]
    if not parts:        return None
        
    has_alias = any(p.startswith('@') for p in parts)
    
    if has_alias:
        if len(parts) > 1:
            raise ValueError("alias must be the only element (no mixing)")
        alias = parts[0]
        # Convert @om to @alias_om internally
        if alias.startswith('@') and not alias.startswith('@alias_'):
            alias = '@alias_' + alias[1:]
        # Check alias format
        if not re.match(r"^@alias_[a-zA-Z0-9_-]{1,64}$", alias):
            raise ValueError(f"Invalid alias format: {alias}")
        parts[0] = alias
    else:
        # Check that each part is a valid IPv4 network or address
        seen = set()
        for p in parts:
            if p in seen:
                raise ValueError(f"Duplicate address: {p}")
            seen.add(p)
            try:
                # Can be an address or network
                ipaddress.IPv4Network(p, strict=False)
            except ValueError:
                raise ValueError(f"Invalid IPv4 address or CIDR network: {p}")
                
    if len(parts) > 64:
        raise ValueError("Addresses list cannot exceed 64 elements")
        
    return parts


def _validate_port_spec(port_val):
    if not port_val:
        return None
        
    # If it is integer, convert to string
    if isinstance(port_val, int):
        port_val = str(port_val)
        
    if not isinstance(port_val, str):
        raise ValueError("Port must be a string or integer")
        
    # Check for whitespace, trailing/double commas
    if ' ' in port_val:
        raise ValueError("Whitespace is not allowed in port specification")
    if port_val.startswith(',') or port_val.endswith(',') or ',,' in port_val:
        raise ValueError("Malformed port specification with empty elements")
        
    parts = port_val.split(',')
    if len(parts) > 64:
        raise ValueError("Ports specification cannot exceed 64 elements")
        
    parsed_ranges = []
    seen_elements = set()
    
    for part in parts:
        if not part:
            raise ValueError("Malformed port specification with empty elements")
        if part in seen_elements:
            raise ValueError(f"Duplicate element: {part}")
        seen_elements.add(part)
        
        if '-' in part:
            # Range format lo-hi
            range_parts = part.split('-')
            if len(range_parts) != 2:
                raise ValueError(f"Invalid range format: {part}")
            lo_str, hi_str = range_parts
            if not lo_str.isdigit() or not hi_str.isdigit():
                raise ValueError(f"Port range values must be digits: {part}")
            lo, hi = int(lo_str), int(hi_str)
            if not (1 <= lo <= 65535) or not (1 <= hi <= 65535):
                raise ValueError(f"Port range out of bounds (1-65535): {part}")
            if lo >= hi:
                raise ValueError(f"Port range start must be less than its end: {part}")
            parsed_ranges.append((lo, hi))
        else:
            # Single port
            if not part.isdigit():
                raise ValueError(f"Invalid port value: {part}")
            port = int(part)
            if not (1 <= port <= 65535):
                raise ValueError(f"Port out of bounds (1-65535): {port}")
            parsed_ranges.append((port, port))
            
    # Check for overlaps between all ranges
    for i in range(len(parsed_ranges)):
        for j in range(i + 1, len(parsed_ranges)):
            r1 = parsed_ranges[i]
            r2 = parsed_ranges[j]
            if max(r1[0], r2[0]) <= min(r1[1], r2[1]):
                raise ValueError(f"Overlapping or duplicate elements: {parts[i]} and {parts[j]}")
                
    return port_val


# --------------------------------------------------------------------------
# Helper Functions & Caching Helpers
# --------------------------------------------------------------------------
def _get_api_headers(extra_headers=None):
    token = "57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {token}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ClientApp/1.0'
    }
    if extra_headers:
        headers.update(extra_headers)
    return headers

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('client_logged_in'):
            return redirect(url_for('client.login'))
        return f(*args, **kwargs)
    return decorated_function

def _get_api_base_url():
    return current_app.config.get('NETBIRD_API_BASE_URL', 'https://api.networkat.cloud')

def _get_customer_group_peer_ids(customer):
    """Return the set of NetBird peer IDs that belong to this customer's group."""
    if not customer or not getattr(customer, 'netbird_group_id', None):
        return set()
    try:
        base_url = _get_api_base_url()
        headers = _get_api_headers()
        
        resp = requests.get(
            f"{base_url}/api/v2/netbird/groups/{customer.netbird_group_id}",
            headers=headers,
            timeout=5
        )
        if resp.status_code != 200:
            current_app.logger.error(
                f"NetBird API Group Fetch Failed [Status {resp.status_code}]: {resp.text}"
            )
            return set()
            
        group_data = resp.json()
        peers = group_data.get("peers") or []
        return {p["id"] for p in peers}
    except Exception as e:
        current_app.logger.error(f"Failed to fetch customer peer group: {e}")
        return set()

def get_cached_customer_peer_ids(customer):
    """جلب قائمة الـ Peers المسموحة للعميل مع كاش لمدة 60 ثانية"""
    if not customer or not getattr(customer, 'netbird_group_id', None):
        return set()

    cid = getattr(customer, 'user_id', getattr(customer, 'customer_id', getattr(customer, 'id', None)))
    now = time.time()
    
    with _cache_lock:
        if cid in _CUSTOMER_GROUPS_CACHE:
            peer_ids, cached_time = _CUSTOMER_GROUPS_CACHE[cid]
            if now - cached_time < 60:  # 60 ثانية كاش
                return peer_ids

    peer_ids = _get_customer_group_peer_ids(customer)
    
    with _cache_lock:
        _CUSTOMER_GROUPS_CACHE[cid] = (peer_ids, now)
    return peer_ids

def get_cached_all_netbird_peers(base_url, headers, cache_ttl=5):
    """كاش لقائمة كل الـ Peers من NetBird لمنع التكرار الشديد"""
    now = time.time()
    
    # Check shared file cache first
    cached_data, cached_time = _read_file_cache("netbird_peers")
    if cached_data is not None and (now - cached_time < cache_ttl):
        return cached_data

    try:
        resp = requests.get(f"{base_url}/api/v2/netbird/peers", headers=headers, timeout=5)
        if resp.status_code == 200:
            peers_data = resp.json()
            if isinstance(peers_data, dict):
                peers_data = [peers_data]
            _write_file_cache("netbird_peers", peers_data)
            return peers_data
    except Exception as e:
        current_app.logger.error(f"Error fetching netbird peers: {e}")

    # Fallback to whatever is in the file cache, or empty list
    return cached_data or []

def get_cached_all_netbird_routes(base_url, headers, cache_ttl=10):
    """كاش لقائمة كل الـ Routes من NetBird لمنع التكرار الشديد"""
    now = time.time()
    
    # Check shared file cache first
    cached_data, cached_time = _read_file_cache("netbird_routes")
    if cached_data is not None and (now - cached_time < cache_ttl):
        return cached_data

    try:
        resp = requests.get(f"{base_url}/api/v2/netbird/routes", headers=headers, timeout=5)
        if resp.status_code == 200:
            routes_data = resp.json()
            _write_file_cache("netbird_routes", routes_data)
            return routes_data
    except Exception as e:
        current_app.logger.error(f"Error fetching netbird routes: {e}")

    # Fallback to whatever is in the file cache, or empty list
    return cached_data or []

def clear_all_netbird_caches(customer_id=None):
    # Remove shared cache files
    for key in ["netbird_peers", "netbird_routes"]:
        path = f"/tmp/nbcache_{key}.json"
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    if customer_id:
        path = f"/tmp/nbcache_customer_status_{customer_id}.json"
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

def no_cache_json(payload, status_code=200):
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp, status_code

def _verify_peer_access(customer, peer_id):
    """استخدام الكاش للتحقق من الصلاحيات بسرعة بدون طلب API جديد"""
    allowed_peers = get_cached_customer_peer_ids(customer)
    return peer_id in allowed_peers


# --------------------------------------------------------------------------
# Public REST API — Setup Key Retrieval
# --------------------------------------------------------------------------
# Rate-limit store: { ip: [timestamp, ...] }
_SETUP_KEY_RATE_LIMIT: dict = {}
_SETUP_KEY_RATE_LOCK = Lock()
_SETUP_KEY_MAX_REQUESTS = 5    # max attempts
_SETUP_KEY_WINDOW_SEC  = 60    # per 60 seconds


def _check_rate_limit(ip: str) -> bool:
    """Returns True if the request is allowed, False if rate-limited."""
    now = time.time()
    with _SETUP_KEY_RATE_LOCK:
        hits = _SETUP_KEY_RATE_LIMIT.get(ip, [])
        hits = [t for t in hits if now - t < _SETUP_KEY_WINDOW_SEC]
        if len(hits) >= _SETUP_KEY_MAX_REQUESTS:
            return False
        hits.append(now)
        _SETUP_KEY_RATE_LIMIT[ip] = hits
    return True


@client_bp.route('/api/v1/auth/setup-key', methods=['POST'])
def api_get_setup_key():
    """
    Secure API endpoint to retrieve the NetBird Setup Key for a client.

    Request (JSON):
        {
            "username": "your_username",
            "password": "your_password"
        }

    Responses:
        200 OK:
            {
                "setup_key": "<netbird-setup-key>",
                "username": "your_username"
            }
        400 Bad Request  — missing or empty fields
        401 Unauthorized — wrong credentials or account disabled
        429 Too Many Requests — rate limit exceeded
        500 Internal Server Error
    """
    # ── 1. Content-Type guard ─────────────────────────────────────────────
    if not request.is_json:
        return jsonify({
            "error": "Unsupported Media Type",
            "message": "Content-Type must be application/json"
        }), 415

    # ── 2. Rate limiting ──────────────────────────────────────────────────
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_rate_limit(client_ip):
        return jsonify({
            "error": "Too Many Requests",
            "message": f"Maximum {_SETUP_KEY_MAX_REQUESTS} attempts per {_SETUP_KEY_WINDOW_SEC} seconds exceeded. Please wait."
        }), 429

    # ── 3. Parse & validate body ──────────────────────────────────────────
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "")

    if not username or not password:
        return jsonify({
            "error": "Bad Request",
            "message": "Both 'username' and 'password' fields are required."
        }), 400

    if len(username) > 128 or len(password) > 256:
        return jsonify({
            "error": "Bad Request",
            "message": "Input exceeds maximum allowed length."
        }), 400

    # ── 4. Authenticate (generic error to prevent user enumeration) ───────
    try:
        success, res = customer_service.authenticate_client_user(username, password)
    except Exception as exc:
        current_app.logger.error(f"[setup-key-api] Auth exception for '{username}': {exc}")
        return jsonify({
            "error": "Internal Server Error",
            "message": "An unexpected error occurred. Please try again later."
        }), 500

    if not success:
        # Identical message for wrong password AND unknown user (anti-enumeration)
        return jsonify({
            "error": "Unauthorized",
            "message": "Invalid credentials or account is not active."
        }), 401

    customer_id = res.get("customer_id")

    # ── 5. Fetch active setup key ─────────────────────────────────────────
    try:
        from repositories.token_repository import TokenRepository
        tokens = TokenRepository.get_by_client(customer_id)
        active_tokens = [t for t in tokens if t.is_active]
    except Exception as exc:
        current_app.logger.error(f"[setup-key-api] Token fetch error for customer '{customer_id}': {exc}")
        return jsonify({
            "error": "Internal Server Error",
            "message": "Could not retrieve setup key. Please contact support."
        }), 500

    if not active_tokens:
        return jsonify({
            "error": "Not Found",
            "message": "No active setup key found for this account. Please contact your administrator."
        }), 404

    setup_key = active_tokens[0].token

    # ── 6. Log access (audit trail) ───────────────────────────────────────
    current_app.logger.info(
        f"[setup-key-api] Setup key retrieved — user='{username}' ip={client_ip}"
    )

    # ── 7. Return key ─────────────────────────────────────────────────────
    return jsonify({
        "setup_key": setup_key,
        "username":  username
    }), 200


# --------------------------------------------------------------------------
# Auth Routes
# --------------------------------------------------------------------------

@client_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        success, res = customer_service.authenticate_client_user(username, password)
        if success:
            session['client_logged_in'] = True
            session['client_user_id'] = res['id']
            session['client_customer_id'] = res['customer_id']
            session['client_customer_name'] = res['customer_name']
            session['client_username'] = username
            return redirect(url_for('client.dashboard'))
        flash(res, 'error')
    return render_template('login.html')


@client_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('client.login'))


@client_bp.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('client_logged_in'):
        return redirect(url_for('client.dashboard'))
        
    recaptcha_site_key = current_app.config.get('RECAPTCHA_SITE_KEY')
    recaptcha_secret = current_app.config.get('RECAPTCHA_SECRET_KEY')

    if request.method == 'POST':
        # reCAPTCHA v3 verification
        if recaptcha_site_key and recaptcha_secret:
            recaptcha_response = request.form.get('g-recaptcha-response')
            if not recaptcha_response:
                flash("Security verification token is missing. Please try again.", "error")
                return render_template('register.html', recaptcha_site_key=recaptcha_site_key)
            try:
                import requests
                verify_response = requests.post(
                    'https://www.google.com/recaptcha/api/siteverify',
                    data={
                        'secret': recaptcha_secret,
                        'response': recaptcha_response
                    },
                    timeout=5
                )
                res_data = verify_response.json()
                if not res_data.get('success') or res_data.get('score', 0.0) < 0.5:
                    current_app.logger.warning(f"reCAPTCHA validation failed or score too low: {res_data}")
                    flash("Security verification failed. Please try again.", "error")
                    return render_template('register.html', recaptcha_site_key=recaptcha_site_key)
            except Exception as e:
                current_app.logger.error(f"Error during reCAPTCHA verification: {e}")
                flash("Security check service error. Please try again.", "error")
                return render_template('register.html', recaptcha_site_key=recaptcha_site_key)

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        client_name = request.form.get('client_name', '').strip()
        client_company_name = request.form.get('client_company_name', '').strip()
        client_email = request.form.get('client_email', '').strip()
        client_phone_number = request.form.get('client_phone_number', '').strip()
        client_country = request.form.get('client_country', '').strip()
        subscription = request.form.get('subscription', 'basic').strip()

        if not username or not password or not client_name or not client_email:
            flash("All fields marked with * are required.", "error")
            return render_template('register.html', recaptcha_site_key=recaptcha_site_key)
        
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template('register.html', recaptcha_site_key=recaptcha_site_key)

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template('register.html', recaptcha_site_key=recaptcha_site_key)

        existing_user = customer_service.client_repo.get_by_username(username)
        if existing_user:
            flash(f'Username "{username}" is already taken. Please choose another.', "error")
            return render_template('register.html', recaptcha_site_key=recaptcha_site_key)

        existing_email = customer_service.client_repo.get_by_email(client_email)
        if existing_email:
            flash(f'Email "{client_email}" is already registered. Please choose another.', "error")
            return render_template('register.html', recaptcha_site_key=recaptcha_site_key)

        # Store in session and send verification code
        code = str(random.randint(100000, 999999))
        session['reg_data'] = {
            'username': username,
            'password': password,
            'client_name': client_name,
            'client_company_name': client_company_name or None,
            'client_email': client_email,
            'client_phone_number': client_phone_number or None,
            'client_country': client_country or None,
            'subscription': subscription
        }
        session['reg_verification'] = {
            'code': code,
            'email': client_email,
            'expires_at': time.time() + 600
        }

        ok, err = send_verification_email(client_email, code)
        if not ok:
            current_app.logger.error(f"Failed to send email verification to {client_email}: {err}")
            flash("Failed to send verification email. Please verify your email address or try again later.", "error")
            return render_template('register.html', recaptcha_site_key=recaptcha_site_key)

        flash("A verification code has been sent to your email. Please enter it below to complete registration.", "success")
        return redirect(url_for('client.verify_email'))

    return render_template('register.html', recaptcha_site_key=recaptcha_site_key)


@client_bp.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    if session.get('client_logged_in'):
        return redirect(url_for('client.dashboard'))
        
    verification = session.get('reg_verification')
    reg_data = session.get('reg_data')
    
    if not verification or not reg_data:
        flash("Registration session expired or invalid. Please start again.", "error")
        return redirect(url_for('client.register'))
        
    if request.method == 'POST':
        entered_code = request.form.get('code', '').strip()
        
        # Check expiration
        if time.time() > verification.get('expires_at', 0):
            flash("Verification code has expired. Please register again.", "error")
            session.pop('reg_verification', None)
            session.pop('reg_data', None)
            return redirect(url_for('client.register'))
            
        if entered_code != verification.get('code'):
            flash("Invalid verification code. Please try again.", "error")
            return render_template('verify_email.html', email=verification.get('email'))
            
        # Success! Clear verification session and create the customer
        session.pop('reg_verification', None)
        session.pop('reg_data', None)
        
        success, res = customer_service.create_customer(reg_data)
        if success:
            flash("Account created and email verified successfully! Please sign in.", "success")
            return redirect(url_for('client.login'))
            
        error_msg = str(res)
        if "clients_username_key" in error_msg or "client_users_username_key" in error_msg or "duplicate key" in error_msg and "username" in error_msg:
            error_msg = f'Username "{reg_data["username"]}" already exists.'
        elif "clients_client_email_key" in error_msg or "duplicate key" in error_msg and "client_email" in error_msg:
            error_msg = f'Email "{reg_data["client_email"]}" already exists.'
        elif "clients_client_phone_number_key" in error_msg or "duplicate key" in error_msg and "client_phone_number" in error_msg:
            error_msg = f'Phone number "{reg_data["client_phone_number"]}" is already registered.'
        elif "duplicate key value violates unique constraint" in error_msg:
            error_msg = 'One of the unique values (username, email, or phone number) already exists.'
        flash(error_msg, "error")
        return redirect(url_for('client.register'))
        
    return render_template('verify_email.html', email=verification.get('email'))


@client_bp.route('/resend-code', methods=['GET', 'POST'])
def resend_code():
    if session.get('client_logged_in'):
        return redirect(url_for('client.dashboard'))
        
    reg_data = session.get('reg_data')
    if not reg_data:
        flash("Registration session expired. Please register again.", "error")
        return redirect(url_for('client.register'))
        
    code = str(random.randint(100000, 999999))
    session['reg_verification'] = {
        'code': code,
        'email': reg_data['client_email'],
        'expires_at': time.time() + 600
    }
    
    ok, err = send_verification_email(reg_data['client_email'], code)
    if not ok:
        current_app.logger.error(f"Failed to resend email verification to {reg_data['client_email']}: {err}")
        flash("Failed to send verification email. Please try again later.", "error")
    else:
        flash("A new verification code has been sent to your email.", "success")
        
    return redirect(url_for('client.verify_email'))


@client_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if session.get('client_logged_in'):
        return redirect(url_for('client.dashboard'))

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        if not identifier:
            flash("Please enter your email address or username.", "error")
            return render_template('forgot_password.html')

        client = None
        if '@' in identifier:
            client = customer_service.client_repo.get_by_email(identifier)
        if not client:
            client = customer_service.client_repo.get_by_username(identifier)

        if not client:
            flash("No account found matching this email address or username.", "error")
            return render_template('forgot_password.html')

        if not client.client_email:
            flash("This account does not have a registered email address. Please contact support.", "error")
            return render_template('forgot_password.html')

        code = str(random.randint(100000, 999999))
        session['reset_password_data'] = {
            'client_id': str(client.user_id),
            'email': client.client_email,
            'code': code,
            'expires_at': time.time() + 600
        }

        ok, err = send_password_reset_email(client.client_email, code)
        if not ok:
            current_app.logger.error(f"Failed to send password reset email to {client.client_email}: {err}")
            flash("Failed to send verification email. Please try again later.", "error")
            return render_template('forgot_password.html')

        flash("A 6-digit password reset code has been sent to your email.", "success")
        return redirect(url_for('client.reset_password'))

    return render_template('forgot_password.html')


@client_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if session.get('client_logged_in'):
        return redirect(url_for('client.dashboard'))

    reset_data = session.get('reset_password_data')
    if not reset_data:
        flash("Password reset session expired or invalid. Please request a new code.", "error")
        return redirect(url_for('client.forgot_password'))

    if request.method == 'POST':
        entered_code = request.form.get('code', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if time.time() > reset_data.get('expires_at', 0):
            flash("Verification code has expired. Please request a new one.", "error")
            session.pop('reset_password_data', None)
            return redirect(url_for('client.forgot_password'))

        if entered_code != reset_data.get('code'):
            flash("Invalid verification code. Please try again.", "error")
            return render_template('reset_password.html', email=reset_data.get('email'))

        if not new_password or len(new_password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template('reset_password.html', email=reset_data.get('email'))

        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template('reset_password.html', email=reset_data.get('email'))

        client = customer_service.client_repo.get_by_id(reset_data.get('client_id'))
        if not client:
            flash("Account not found. Please try again.", "error")
            session.pop('reset_password_data', None)
            return redirect(url_for('client.forgot_password'))

        customer_service.client_repo.update_password(client, new_password)
        customer_service.client_repo.commit()

        session.pop('reset_password_data', None)
        flash("Your password has been successfully reset! Please sign in with your new credentials.", "success")
        return redirect(url_for('client.login'))

    return render_template('reset_password.html', email=reset_data.get('email'))


@client_bp.route('/resend-reset-code', methods=['GET', 'POST'])
def resend_reset_code():
    if session.get('client_logged_in'):
        return redirect(url_for('client.dashboard'))

    reset_data = session.get('reset_password_data')
    if not reset_data:
        flash("Password reset session expired. Please start again.", "error")
        return redirect(url_for('client.forgot_password'))

    code = str(random.randint(100000, 999999))
    session['reset_password_data']['code'] = code
    session['reset_password_data']['expires_at'] = time.time() + 600

    ok, err = send_password_reset_email(reset_data['email'], code)
    if not ok:
        current_app.logger.error(f"Failed to resend reset email to {reset_data['email']}: {err}")
        flash("Failed to send verification email. Please try again later.", "error")
    else:
        flash("A new verification code has been sent to your email.", "success")

    return redirect(url_for('client.reset_password'))


# --------------------------------------------------------------------------
# Dashboard & Views
# --------------------------------------------------------------------------

@client_bp.route('/')
@login_required
def dashboard():
    customer_id = session.get('client_customer_id')
    customer_name = session.get('client_customer_name')
    if not customer_id:
        flash("Customer not found", "error")
        return redirect(url_for('client.login'))
    
    # Get total edges count from database directly (extremely fast, no API calls)
    total_edges = edge_service.edge_repo.count_by_customer(customer_id)
    
    return render_template(
        'dashboard.html',
        customer_name=customer_name,
        total_edges=total_edges,
        online_edges=0,
        offline_edges=total_edges,
        netbird_peers=[]
    )


@client_bp.route('/peers', strict_slashes=False)
@login_required
def peers_page():
    customer_id = session.get('client_customer_id')
    customer_name = session.get('client_customer_name')
    if not customer_id:
        flash("Customer not found", "error")
        return redirect(url_for('client.login'))
    
    return render_template(
        'peers.html',
        customer_name=customer_name,
        netbird_peers=[]
    )

@client_bp.route('/peers/aliases')
@login_required
def aliases_page():
    customer_id = session.get('client_customer_id')
    customer_name = session.get('client_customer_name')
    if not customer_id:
        flash("Customer not found", "error")
        return redirect(url_for('client.login'))
    
    customer = Client.query.get(customer_id)
    peers_list = []
    if customer:
        try:
            allowed_peer_ids = get_cached_customer_peer_ids(customer)
            base_url = _get_api_base_url()
            headers = _get_api_headers()
            peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
            customer_peers = [p for p in peers_data if p.get("id") in allowed_peer_ids]
            
            processed_peers = []
            if customer_peers:
                futures = {
                    executor.submit(
                        _check_single_peer_handshake,
                        peer, base_url, headers
                    ): peer
                    for peer in customer_peers
                }
                for future in as_completed(futures, timeout=5):
                    try:
                        res = future.result()
                        processed_peers.append(res)
                    except Exception as err:
                        current_app.logger.error(f"Peer handshake check error in aliases_page: {err}")
            
            peers_list = [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "connected": p.get("is_online", False),
                    "ip": p.get("ip")
                }
                for p in processed_peers
            ]
            peers_list.sort(key=lambda p: (p.get("name") or "").lower())
        except Exception as e:
            current_app.logger.error(f"Error fetching peers for aliases page: {e}")

    return render_template(
        'aliases.html',
        customer_name=customer_name,
        peers=peers_list
)

@client_bp.route('/peers/<peer_id>/aliases')
@login_required
def peer_aliases(peer_id):
    customer_id = session.get('client_customer_id')
    customer_name = session.get('client_customer_name')
    if not customer_id:
        flash("Customer not found", "error")
        return redirect(url_for('client.login'))
    
    customer = Client.query.get(customer_id)
    if not customer or not _verify_peer_access(customer, peer_id):
        flash("Unauthorized access to this device.", "error")
        return redirect(url_for('client.dashboard'))
        
    peers_list = []
    if customer:
        try:
            allowed_peer_ids = get_cached_customer_peer_ids(customer)
            base_url = _get_api_base_url()
            headers = _get_api_headers()
            peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
            customer_peers = [p for p in peers_data if p.get("id") in allowed_peer_ids]
            
            processed_peers = []
            if customer_peers:
                futures = {
                    executor.submit(
                        _check_single_peer_handshake,
                        peer, base_url, headers
                    ): peer
                    for peer in customer_peers
                }
                for future in as_completed(futures, timeout=5):
                    try:
                        res = future.result()
                        processed_peers.append(res)
                    except Exception as err:
                        current_app.logger.error(f"Peer handshake check error in peer_aliases: {err}")
            
            peers_list = [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "connected": p.get("is_online", False),
                    "ip": p.get("ip")
                }
                for p in processed_peers
            ]
            peers_list.sort(key=lambda p: (p.get("name") or "").lower())
        except Exception as e:
            current_app.logger.error(f"Error fetching peers for peer_aliases: {e}")

    # Check if selected peer exists in list
    selected_peer = next((p for p in peers_list if p["id"] == peer_id), None)
    selected_peer_name = selected_peer["name"] if selected_peer else "Peer Device"

    return render_template(
        'aliases.html',
        customer_name=customer_name,
        peers=peers_list,
        selected_peer_id=peer_id,
        peer_name=selected_peer_name
    )

@client_bp.route('/peers/<peer_id>')
@login_required
def peer_details(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    
    if not customer or not _verify_peer_access(customer, peer_id):
        flash("Unauthorized access to this device.", "error")
        return redirect(url_for('client.dashboard'))
        
    peer_name = request.args.get('name', 'Peer Device')
    
    # Check online status and details of the peer
    is_online = False
    peer_ip = "Unknown"
    peer_public_ip = "Unknown"
    peer_os = "Unknown"
    peer_version = "Unknown"
    peer_last_seen = "Never"
    
    try:
        base_url = _get_api_base_url()
        headers = _get_api_headers()
        peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
        peer_data = next((p for p in peers_data if p.get("id") == peer_id), None)
        if peer_data:
            checked_peer = _check_single_peer_handshake(peer_data, base_url, headers)
            is_online = checked_peer.get("is_online", False)
            peer_ip = checked_peer.get("ip", peer_ip)
            peer_public_ip = checked_peer.get("connection_ip", peer_public_ip) or "Unknown"
            peer_os = checked_peer.get("os", peer_os)
            peer_version = checked_peer.get("version", peer_version)
            peer_last_seen = checked_peer.get("last_seen", peer_last_seen)
            if peer_last_seen and peer_last_seen != "Never":
                try:
                    from datetime import datetime
                    clean_str = peer_last_seen.replace('Z', '+00:00')
                    dt = datetime.fromisoformat(clean_str)
                    peer_last_seen = dt.strftime("%d/%m/%Y %H:%M:%S")
                except Exception as ex:
                    current_app.logger.error(f"Failed to format last seen '{peer_last_seen}': {ex}")
            if not request.args.get('name') and checked_peer.get('name'):
                peer_name = checked_peer.get('name')
    except Exception as e:
        current_app.logger.error(f"Error checking peer status in peer details page: {e}")

    return render_template(
        'peer_details.html',
        peer_id=peer_id,
        peer_name=peer_name,
        customer_name=session.get('client_customer_name'),
        is_online=is_online,
        peer_ip=peer_ip,
        peer_os=peer_os,
        peer_version=peer_version,
        peer_last_seen=peer_last_seen
    )


@client_bp.route('/peers/<peer_id>/filtering')
@login_required
def peer_filtering(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    
    if not customer or not _verify_peer_access(customer, peer_id):
        flash("Unauthorized access to this device.", "error")
        return redirect(url_for('client.dashboard'))
    # Check if the peer is online
    is_online = False
    try:
        base_url = _get_api_base_url()
        headers = _get_api_headers()
        peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
        peer_data = next((p for p in peers_data if p.get("id") == peer_id), None)
        if peer_data:
            checked_peer = _check_single_peer_handshake(peer_data, base_url, headers)
            is_online = checked_peer.get("is_online", False)
    except Exception as e:
        current_app.logger.error(f"Error checking peer status on loading filtering page: {e}")

    peer_name = request.args.get('name', 'Edge Device')
    return render_template(
        'filtering.html',
        peer_id=peer_id,
        peer_name=peer_name,
        customer_name=session.get('client_customer_name'),
        is_online=is_online
    )


# --------------------------------------------------------------------------
# API Endpoints
# --------------------------------------------------------------------------

@client_bp.route('/api/customer/setup-keys', methods=['GET'])
@login_required
def get_customer_setup_keys():
    customer_id = session.get('client_customer_id')
    if not customer_id:
        return jsonify({"error": "Customer association not found"}), 404
    try:
        tokens = Token.query.filter_by(client_id=customer_id).all()
        
        # Fetch NetBird setup keys
        netbird_keys = []
        try:
            base_url = _get_api_base_url()
            headers = _get_api_headers()
            resp = requests.get(f"{base_url}/api/v2/netbird/setup-keys", headers=headers, timeout=5)
            if resp.status_code == 200:
                netbird_keys = resp.json()
            else:
                current_app.logger.error(f"Failed to fetch setup keys from NetBird: Status {resp.status_code}")
        except Exception as e:
            current_app.logger.error(f"Error fetching setup keys from NetBird: {e}")
            
        tokens_data = []
        for t in tokens:
            db_prefix = t.token[:5]
            
            # Find matching setup key in NetBird list
            matched = None
            for nb_key in netbird_keys:
                nb_key_val = nb_key.get("key", "")
                nb_key_clean = nb_key_val.replace("*", "")
                if nb_key_clean and (db_prefix.startswith(nb_key_clean) or nb_key_clean.startswith(db_prefix)):
                    matched = nb_key
                    break
            
            if matched:
                valid = matched.get("valid", True)
                used_times = matched.get("used_times", 0)
                usage_limit = matched.get("usage_limit", 0)
                remaining_uses = (usage_limit - used_times) if usage_limit > 0 else None
            else:
                valid = t.is_active
                used_times = 0
                usage_limit = 0
                remaining_uses = None
                
            # Mask the setup key before sending it to the client frontend
            masked_token = t.token
            if len(masked_token) > 8:
                parts = masked_token.split('-', 1)
                masked_token = f"{parts[0]}-********************"
                
            tokens_data.append({
                "token": t.token,
                "is_active": valid,  # Real-time validity from NetBird
                "used_times": used_times,
                "usage_limit": usage_limit,
                "remaining_uses": remaining_uses,
                "created_at": t.created_at.strftime("%d/%m/%Y %H:%M:%S") if t.created_at else "Unknown"
            })
            
        return jsonify({"tokens": tokens_data}), 200
    except Exception as e:
        return jsonify({"error": "Database error", "details": str(e)}), 500


@client_bp.route('/peers/<peer_id>/update', methods=['POST'])
@login_required
def update_peer(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({'success': False, 'error': 'Unauthorized peer access'}), 403

    data = request.get_json() or {}
    new_name = data.get('name', '').strip()
    if not new_name:
        return jsonify({'success': False, 'error': 'Device name cannot be empty'}), 400

    success, message = edge_service.update_peer_name(peer_id, new_name)
    if success:
        _set_name_override(peer_id, new_name)
        clear_all_netbird_caches(customer_id)
        return jsonify({'success': True, 'message': message})
    return jsonify({'success': False, 'error': message}), 400


@client_bp.route('/api/peers', methods=['GET'])
@login_required
def proxy_peers():
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer:
        return jsonify({"error": "Unauthorized"}), 401

    allowed_peer_ids = get_cached_customer_peer_ids(customer)
    peer_name = request.args.get('name', '').lower()
    
    try:
        peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())

        now = time.time()
        sanitized_peers = []
        for p in peers_data:
            pid = p.get("id")
            if pid not in allowed_peer_ids:
                continue
            
            pname = p.get("name")
            ov_name = _get_name_override(pid)
            if ov_name:
                pname = ov_name

            if peer_name and peer_name not in pname.lower():
                continue

            sanitized_peers.append({
                "id": pid,
                "name": pname,
                "connected": p.get("connected", False),
                "last_seen": p.get("last_seen"),
                "ip": p.get("ip")
            })
        sanitized_peers.sort(key=lambda p: (p.get("name") or "").lower())
        return jsonify(sanitized_peers), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/peers/<peer_id>/handshake')
@login_required
def peer_handshake(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    try:
        url = f"{_get_api_base_url()}/api/v1/peers/{peer_id}/handshake"
        resp = requests.get(url, headers=_get_api_headers(), timeout=5)
        if resp.ok:
            return jsonify(resp.json())
        return jsonify({"peer_id": peer_id, "is_reachable": False}), resp.status_code
    except Exception as e:
        return jsonify({"peer_id": peer_id, "is_reachable": False, "error": str(e)}), 500


@client_bp.route('/api/peers/<peer_id>/adguard/blocked_services', methods=['GET'])
@login_required
def get_peer_blocked_services(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None

    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized peer access"}), 403

    try:
        url = f"{_get_api_base_url()}/api/v1/peers/{peer_id}/adguard/blocked_services"
        resp = requests.get(url, headers=_get_api_headers(), timeout=10)
        if resp.ok:
            return jsonify(resp.json())
        return jsonify({"error": "Failed to fetch blocked services"}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/peers/<peer_id>/adguard/blocked_services', methods=['POST', 'PUT'])
@login_required
def update_peer_blocked_services(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None

    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized peer access"}), 403

    try:
        payload = request.get_json() or {}
        headers = _get_api_headers({'Content-Type': 'application/json'})
        url = f"{_get_api_base_url()}/api/v1/peers/{peer_id}/adguard/blocked_services"
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.ok:
            return jsonify(resp.json())
        return jsonify({"error": "Failed to update blocked services", "details": resp.text}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/peers/<peer_id>/adguard/clients/<client_name>/blocked_services', methods=['GET'])
@login_required
def get_client_blocked_services_proxy(peer_id, client_name):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None

    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized peer access"}), 403

    try:
        url = f"{_get_api_base_url()}/api/v1/peers/{peer_id}/adguard/clients/{client_name}/blocked_services"
        resp = requests.get(url, headers=_get_api_headers(), timeout=10)
        if resp.ok:
            return jsonify(resp.json())
        return jsonify({"error": f"Failed to fetch blocked services for client {client_name}"}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/peers/<peer_id>/adguard/clients/<client_name>/blocked_services', methods=['POST', 'PUT'])
@login_required
def update_client_blocked_services_proxy(peer_id, client_name):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None

    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized peer access"}), 403

    try:
        payload = request.get_json() or {}
        headers = _get_api_headers({'Content-Type': 'application/json'})
        url = f"{_get_api_base_url()}/api/v1/peers/{peer_id}/adguard/clients/{client_name}/blocked_services"
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.ok:
            return jsonify(resp.json())
        return jsonify({"error": f"Failed to update blocked services for client {client_name}", "details": resp.text}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --------------------------------------------------------------------------
# NetBird Routes Proxy
# --------------------------------------------------------------------------

@client_bp.route('/api/v2/netbird/routes', methods=['GET'])
@login_required
def proxy_get_routes():
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer:
        return jsonify({"error": "Unauthorized"}), 401

    allowed_peer_ids = get_cached_customer_peer_ids(customer)
    try:
        all_routes = get_cached_all_netbird_routes(_get_api_base_url(), _get_api_headers())
        sanitized_routes = [
            {
                "id": r.get("id"),
                "peer": r.get("peer"),
                "network": r.get("network"),
                "network_id": r.get("network_id"),
                "enabled": r.get("enabled", True),
                "description": r.get("description", "")
            }
            for r in all_routes if r.get("peer") in allowed_peer_ids
        ]

        # Apply route overrides (to circumvent Netbird API propagation delay)
        active_route_overrides = _get_active_route_overrides()

        # 1. Update/remove existing route items
        filtered_routes = []
        for r in sanitized_routes:
            pid = r.get("peer")
            if pid in active_route_overrides:
                net_val = active_route_overrides[pid]
                if net_val:  # If not empty (meaning not deleted)
                    r["network"] = net_val
                    filtered_routes.append(r)
                # If net_val is empty string, it's deleted, so we skip/remove it!
            else:
                filtered_routes.append(r)
        sanitized_routes = filtered_routes

        # 2. Inject new route items if not present
        for pid, net_val in active_route_overrides.items():
            if net_val:
                if not any(r.get("peer") == pid for r in sanitized_routes):
                    sanitized_routes.append({
                        "id": f"temp-route-{pid}",
                        "peer": pid,
                        "network": net_val,
                        "network_id": f"temp-net-{pid}",
                        "enabled": True,
                        "description": "Temporary inline route override"
                    })
        return jsonify(sanitized_routes), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/v2/netbird/routes', methods=['POST'])
@login_required
def proxy_post_route():
    headers = _get_api_headers({"Content-Type": "application/json"})
    try:
        req_data = request.get_json() or {}
        customer_id = session.get('client_customer_id')
        username = session.get('client_username', 'user')

        if not customer_id:
            return jsonify({"error": "Unauthorized"}), 401

        customer = Client.query.get(customer_id)
        if not customer or not getattr(customer, 'netbird_group_id', None):
            return jsonify({"error": "NetBird Group ID not found for this customer"}), 400

        if not _verify_peer_access(customer, req_data.get("peer")):
            return jsonify({"error": "This peer does not belong to your account"}), 403

        netbird_group_id = customer.netbird_group_id
        req_data["groups"] = [netbird_group_id]
        req_data["access_control_groups"] = [netbird_group_id]

        if not req_data.get("network_id") or req_data.get("network_id").startswith("route-"):
            peer_id = req_data.get("peer", "")[:5]
            req_data["network_id"] = f"{username.lower()}-{peer_id}"

        req_data.pop("peer_groups", None)

        url = f"{_get_api_base_url()}/api/v2/netbird/routes"
        response = requests.post(url, json=req_data, headers=headers, timeout=10)
        if response.status_code in [200, 201]:
            peer_id = req_data.get("peer")
            network = req_data.get("network")
            if peer_id and network:
                _set_route_override(peer_id, network)
            clear_all_netbird_caches(customer_id)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/v2/netbird/routes/<route_id>', methods=['PUT'])
@login_required
def proxy_put_route(route_id):
    headers = _get_api_headers({"Content-Type": "application/json"})
    try:
        req_data = request.get_json() or {}
        customer_id = session.get('client_customer_id')

        if not customer_id:
            return jsonify({"error": "Unauthorized"}), 401

        customer = Client.query.get(customer_id)
        if not customer or not getattr(customer, 'netbird_group_id', None):
            return jsonify({"error": "NetBird Group ID not found for this customer"}), 400

        if not _verify_peer_access(customer, req_data.get("peer")):
            return jsonify({"error": "This peer does not belong to your account"}), 403

        netbird_group_id = customer.netbird_group_id
        req_data["groups"] = [netbird_group_id]
        req_data["access_control_groups"] = [netbird_group_id]
        req_data.pop("peer_groups", None)

        url = f"{_get_api_base_url()}/api/v2/netbird/routes/{route_id}"
        response = requests.put(url, json=req_data, headers=headers, timeout=10)
        if response.status_code in [200, 201, 204]:
            peer_id = req_data.get("peer")
            network = req_data.get("network")
            if peer_id and network:
                _set_route_override(peer_id, network)
            clear_all_netbird_caches(customer_id)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@client_bp.route('/api/v2/netbird/routes/<route_id>', methods=['DELETE'])
@login_required
def proxy_delete_route(route_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer:
        return jsonify({"error": "Unauthorized"}), 401

    base_url = _get_api_base_url()
    peer_id = None
    try:
        allowed_peer_ids = get_cached_customer_peer_ids(customer)
        check_resp = requests.get(f"{base_url}/api/v2/netbird/routes/{route_id}", headers=_get_api_headers(), timeout=5)
        
        if check_resp.status_code == 200:
            route_data = check_resp.json()
            peer_id = route_data.get("peer")
            if route_data.get("peer") not in allowed_peer_ids:
                return jsonify({"error": "This route does not belong to your account"}), 403
        else:
            return jsonify({"error": "Failed to verify route ownership"}), check_resp.status_code
    except Exception as e:
        return jsonify({"error": "Error verifying ownership before deletion", "details": str(e)}), 500

    try:
        response = requests.delete(f"{base_url}/api/v2/netbird/routes/{route_id}", headers=_get_api_headers(), timeout=10)
        if response.status_code in [200, 204]:
            if peer_id:
                _set_route_override(peer_id, "")
            clear_all_netbird_caches(customer_id)
            return '', response.status_code
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --------------------------------------------------------------------------
# SSE Real-time Peers Stream
# --------------------------------------------------------------------------

_HANDSHAKE_CACHE = {}  # { peer_id: (is_reachable, timestamp) }
_VPN_ONLY_CACHE = {}   # { peer_id: (enabled, timestamp) }

def get_cached_peer_handshake(peer_id, base_url, headers, cache_ttl=4):
    """كاش سريع لنتيجة الـ Handshake لمنع ضرب الـ Backend بكثافة"""
    now = time.time()
    
    with _cache_lock:
        if peer_id in _HANDSHAKE_CACHE:
            is_reachable, cached_time = _HANDSHAKE_CACHE[peer_id]
            if now - cached_time < cache_ttl:
                return is_reachable

    is_reachable = False
    try:
        hs_resp = requests.get(
            f"{base_url}/api/v1/peers/{peer_id}/handshake",
            headers=headers,
            timeout=5.0
        )
        if hs_resp.ok:
            is_reachable = hs_resp.json().get("is_reachable", False)
    except Exception:
        is_reachable = False

    with _cache_lock:
        _HANDSHAKE_CACHE[peer_id] = (is_reachable, now)

    return is_reachable

def get_cached_peer_vpn_only(peer_id, peer_ip, cache_ttl=15):
    """كاش لـ VPN-Only status لتفادي الطلبات المتكررة"""
    now = time.time()
    
    with _cache_lock:
        if peer_id in _VPN_ONLY_CACHE:
            enabled, cached_time = _VPN_ONLY_CACHE[peer_id]
            if now - cached_time < cache_ttl:
                return enabled

    enabled = False
    try:
        url = f"http://{peer_ip}:8765/vpn-only"
        resp = requests.get(url, timeout=1.5)
        if resp.ok:
            enabled = resp.json().get("enabled", False)
    except Exception:
        enabled = False

    with _cache_lock:
        _VPN_ONLY_CACHE[peer_id] = (enabled, now)

    return enabled

def _check_single_peer_handshake(peer, base_url, headers):
    peer_id = peer.get("id")
    is_connected = peer.get("connected", False)
    is_reachable = False
    vpn_only = False

    if is_connected:
        is_reachable = get_cached_peer_handshake(peer_id, base_url, headers, cache_ttl=60)
        if is_reachable and peer.get("ip"):
            vpn_only = get_cached_peer_vpn_only(peer_id, peer.get("ip"), cache_ttl=60)

    real_online = is_connected and is_reachable
    pname = peer.get("name")
    ov_name = _get_name_override(peer_id)
    if ov_name:
        pname = ov_name

    return {
        "id": peer_id,
        "name": pname,
        "connected": is_connected,
        "is_reachable": is_reachable,
        "is_online": real_online,
        "last_seen": peer.get("last_seen"),
        "ip": peer.get("ip"),
        "connection_ip": peer.get("connection_ip"),
        "vpn_only": vpn_only
    }
import logging
logger = logging.getLogger(__name__)

def _revalidate_customer_peers_status(customer_id, customer, base_url, headers, allowed_peer_ids):
    """جلب حالة الأجهزة وتحديث الكاش في الخلفية لتفادي تعليق طلبات الـ AJAX للمستخدم"""
    try:
        peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
        customer_peers = [p for p in peers_data if p.get("id") in allowed_peer_ids]

        processed_peers = []
        online_count = 0

        if customer_peers:
            futures = {
                executor.submit(
                    _check_single_peer_handshake,
                    peer, base_url, headers
                ): peer
                for peer in customer_peers
            }
            for future in as_completed(futures, timeout=5):
                try:
                    res = future.result()
                    processed_peers.append(res)
                    if res["is_online"]:
                        online_count += 1
                except Exception as err:
                    logger.error(f"Peer check error in background revalidation: {err}")

        # Sort alphabetically by device name
        processed_peers.sort(key=lambda p: (p.get("name") or "").lower())

        payload = {
            "peers": processed_peers,
            "summary": {
                "total": len(processed_peers),
                "online": online_count,
                "offline": len(processed_peers) - online_count
            }
        }
        _write_file_cache(f"customer_status_{customer_id}", payload)
    except Exception as e:
        logger.error(f"Background revalidation failed for customer {customer_id}: {e}")
    finally:
        _stop_revalidating(customer_id)

@client_bp.route('/api/peers/status')
@login_required
def get_peers_status_api():
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer:
        return jsonify({"error": "Unauthorized"}), 401

    base_url = _get_api_base_url()
    headers = _get_api_headers()
    allowed_peer_ids = get_cached_customer_peer_ids(customer)

    if not allowed_peer_ids:
        return jsonify({
            "peers": [],
            "summary": {"total": 0, "online": 0, "offline": 0}
        })

    now = time.time()
    cached_payload, cached_time = _read_file_cache(f"customer_status_{customer_id}")

    # 1. إذا كان الكاش حديثاً (أقل من 30 ثانية)، يتم إرجاعه فوراً
    if cached_payload and (now - cached_time < 30):
        return no_cache_json(cached_payload)

    # 2. إذا كان الكاش قديماً (Stale) ولكنه متوفر، يتم إرجاعه فوراً لتسريع الـ Response
    # ثم نقوم بإطلاق استعلام في الخلفية (Revalidate) لتحديث الكاش
    if cached_payload:
        if not _is_revalidating(customer_id):
            _start_revalidating(customer_id)
            executor.submit(
                _revalidate_customer_peers_status,
                customer_id, customer, base_url, headers, allowed_peer_ids
            )
        return no_cache_json(cached_payload)

    # 3. إذا لم يكن هناك كاش نهائياً (عند أول تحميل)، يتم التشغيل متزامناً لمرة واحدة لتغذية الكاش
    try:
        peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
        customer_peers = [p for p in peers_data if p.get("id") in allowed_peer_ids]

        processed_peers = []
        online_count = 0

        if customer_peers:
            futures = {
                executor.submit(
                    _check_single_peer_handshake,
                    peer, base_url, headers
                ): peer
                for peer in customer_peers
            }
            for future in as_completed(futures, timeout=5):
                try:
                    res = future.result()
                    processed_peers.append(res)
                    if res["is_online"]:
                        online_count += 1
                except Exception as err:
                    logger.error(f"Peer check error: {err}")

        # Sort alphabetically by device name
        processed_peers.sort(key=lambda p: (p.get("name") or "").lower())

        payload = {
            "peers": processed_peers,
            "summary": {
                "total": len(processed_peers),
                "online": online_count,
                "offline": len(processed_peers) - online_count
            }
        }
        _write_file_cache(f"customer_status_{customer_id}", payload)
        return no_cache_json(payload)
    except Exception as e:
        logger.error(f"Failed to fetch peers status: {e}")
        return jsonify({"error": "fetch_failed"}), 500

@client_bp.route('/api/peers/<peer_id>/vpn-only', methods=['GET', 'POST'])
@login_required
def peer_vpn_only_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    # Resolve peer IP from NetBird peers cache
    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"detail": "Peer or Peer IP not found in NetBird"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/vpn-only"

    try:
        if request.method == 'POST':
            data = request.get_json() or {}
            # Normalize "action" parameter to "operation" for agent compatibility
            if "action" in data and "operation" not in data:
                data["operation"] = data.pop("action")
            resp = requests.post(agent_url, json=data, timeout=10)
        else:
            resp = requests.get(agent_url, timeout=10)

        # Update cache if toggling vpn-only was successful
        if resp.ok and request.method == 'POST':
            try:
                resp_data = resp.json()
                if resp_data.get("ok") or resp_data.get("status") == "success":
                    enabled = resp_data.get("enabled")
                    if enabled is None:
                        # Fallback to operation value from POST payload
                        op = data.get("operation", "").lower()
                        enabled = op in ("enable", "on")
                    
                    with _cache_lock:
                        _VPN_ONLY_CACHE[peer_id] = (enabled, time.time())
                    
                    # Clear the cache file so the next status poll fetches fresh data
                    clear_all_netbird_caches(customer_id)
            except Exception as cache_err:
                current_app.logger.error(f"Error updating vpn-only cache: {cache_err}")

        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "Device agent is offline or unreachable"}), 503



# --------------------------------------------------------------------------
# Firewall Rules
# --------------------------------------------------------------------------

def _revalidate_peer_firewall_rules(peer_id, peer_ip):
    try:
        url = f"http://{peer_ip}:8765/firewall/rules"
        resp = requests.get(url, timeout=5)
        live_rules = []
        agent_online = False
        if resp.ok:
            agent_online = True
            live_rules = resp.json().get("rules", [])
        
        with _FIREWALL_CACHE_LOCK:
            _FIREWALL_RULES_CACHE[peer_id] = (live_rules, agent_online, time.time())
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Background firewall rules revalidation failed for {peer_id}: {e}")
    finally:
        with _FIREWALL_CACHE_LOCK:
            _FIREWALL_REVALIDATING.discard(peer_id)


def _async_sync_firewall_rule_agent(peer_id, peer_ip, rule_id, new_enabled, old_enabled, rule_slug, app_instance):
    with app_instance.app_context():
        try:
            if new_enabled:
                url = f"http://{peer_ip}:8765/firewall/rules/enable"
            else:
                url = f"http://{peer_ip}:8765/firewall/rules/disable"
                
            payload = {"ids": [rule_slug]}
            resp = requests.post(url, json=payload, timeout=10)
            success = False
            if resp.ok:
                cmd_data = resp.json()
                if cmd_data.get("ok"):
                    success = True
            
            if not success:
                raise Exception("Agent command did not report success.")
                
        except Exception as e:
            try:
                db_rule = FirewallRule.query.get(rule_id)
                if db_rule:
                    db_rule.enabled = old_enabled
                    db.session.commit()
            except Exception as db_err:
                app_instance.logger.error(f"Error reverting database after toggle failure: {db_err}")
            
            app_instance.logger.error(f"Background firewall rule toggle sync failed for peer {peer_id}, rule {rule_id}: {e}")
        finally:
            with _FIREWALL_CACHE_LOCK:
                _FIREWALL_RULES_CACHE.pop(peer_id, None)


@client_bp.route('/peers/<peer_id>/firewall')
@login_required
def peer_firewall(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    
    if not customer or not _verify_peer_access(customer, peer_id):
        flash("Unauthorized access to this device.", "error")
        return redirect(url_for('client.dashboard'))

    # Check online status of the peer
    is_online = False
    peer_name = 'Edge Device'
    
    # Check file-backed override first
    override_name = _get_name_override(peer_id)
    if override_name:
        peer_name = override_name

    vpn_only = False
    try:
        base_url = _get_api_base_url()
        headers = _get_api_headers()
        peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
        peer_data = next((p for p in peers_data if p.get("id") == peer_id), None)
        if peer_data:
            checked_peer = _check_single_peer_handshake(peer_data, base_url, headers)
            is_online = checked_peer.get("is_online", False)
            if not override_name and checked_peer.get('name'):
                peer_name = checked_peer.get('name')
            if peer_data.get("ip"):
                vpn_only = get_cached_peer_vpn_only(peer_id, peer_data.get("ip"))
    except Exception as e:
        current_app.logger.error(f"Error checking peer status on loading firewall page: {e}")

    return render_template(
        'firewall.html',
        peer_id=peer_id,
        peer_name=peer_name,
        customer_name=session.get('client_customer_name'),
        is_online=is_online,
        vpn_only=vpn_only
    )


@client_bp.route('/api/peers/<peer_id>/firewall/rules', methods=['GET'])
@login_required
def get_peer_firewall_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    # Resolve peer IP from NetBird peers cache
    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"rules": [], "agent_online": False}), 200

    peer_ip = peer.get("ip")
    
    # Get cached live agent rules
    now = time.time()
    cached_live_rules = []
    agent_online = False
    cache_found = False
    cache_time = 0

    with _FIREWALL_CACHE_LOCK:
        if peer_id in _FIREWALL_RULES_CACHE:
            cached_live_rules, agent_online, cache_time = _FIREWALL_RULES_CACHE[peer_id]
            cache_found = True

    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    should_revalidate = force_refresh or not cache_found or (now - cache_time > 15)
    
    if should_revalidate:
        try:
            url = f"http://{peer_ip}:8765/firewall/rules"
            resp = requests.get(url, timeout=5)
            if resp.ok:
                agent_online = True
                cached_live_rules = resp.json().get("rules", [])
            
            with _FIREWALL_CACHE_LOCK:
                _FIREWALL_RULES_CACHE[peer_id] = (cached_live_rules, agent_online, time.time())
        except Exception as e:
            current_app.logger.error(f"Sync firewall rules fetch failed: {e}")

    rules_data = []
    for idx, lr in enumerate(cached_live_rules):
        src_ips = []
        for s in (lr.get("src") or []):
            if s.startswith('@alias_'):
                s = '@' + s[7:]
            src_ips.append(s)
        src_ip = ",".join(src_ips) if src_ips else "Any"

        dst_ips = []
        for d in (lr.get("dst") or []):
            if d.startswith('@alias_'):
                d = '@' + d[7:]
            dst_ips.append(d)
        dst_ip = ",".join(dst_ips) if dst_ips else "Any"

        comment = lr.get("comment", "")
        is_autogenerated = bool(re.match(r"^rule_\d{6}$", comment))
        ui_name = "" if is_autogenerated else comment

        action = lr.get("action", "DROP")
        if action.lower() == "accept" or action.lower() == "allow":
            action = "ALLOW"
        else:
            action = "DROP"

        src_ports = lr.get("src_port")
        if isinstance(src_ports, list):
            src_port = ",".join(src_ports)
        else:
            src_port = src_ports or ""

        dst_ports = lr.get("dst_port")
        if isinstance(dst_ports, list):
            dst_port = ",".join(dst_ports)
        else:
            dst_port = dst_ports or ""

        rules_data.append({
            "id": idx + 1,
            "rule_name": ui_name,
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "src_port": src_port,
            "dst_port": dst_port,
            "protocol": lr.get("protocol") or "any",
            "action": action,
            "enabled": lr.get("enabled", True),
            "active_on_agent": True,
            "direction": lr.get("id"),
            "order": lr.get("order", idx + 1),
            "packets": lr.get("packets"),
            "bytes": lr.get("bytes")
        })

    return jsonify({
        "rules": rules_data,
        "agent_online": agent_online
    }), 200


@client_bp.route('/api/peers/<peer_id>/firewall/rules', methods=['POST'])
@login_required
def add_peer_firewall_rule(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    req_data = request.get_json() or {}
    rule_name = req_data.get('rule_name')
    rule_name = rule_name.strip() if rule_name else ''
    
    action = req_data.get('action')
    action = action.lower() if action else 'drop'
    if action == 'accept':
        action = 'allow'
    
    protocol = req_data.get('protocol')
    protocol = protocol.lower() if protocol else 'any'
    
    src_ip = req_data.get('src_ip')
    src_ip = src_ip.strip() if (src_ip and isinstance(src_ip, str)) else None
    
    dst_ip = req_data.get('dst_ip')
    dst_ip = dst_ip.strip() if (dst_ip and isinstance(dst_ip, str)) else None
    
    src_port = req_data.get('src_port')
    src_port = src_port.strip() if (src_port and isinstance(src_port, str)) else None
    
    dst_port = req_data.get('dst_port')
    dst_port = dst_port.strip() if (dst_port and isinstance(dst_port, str)) else None

    order = req_data.get('order')

    # Resolve peer IP
    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": " IP not found"}), 404
    peer_ip = peer.get("ip")

    # Get live rules to validate uniqueness and default name
    try:
        live_resp = requests.get(f"http://{peer_ip}:8765/firewall/rules", timeout=10)
        live_rules = live_resp.json().get("rules", []) if live_resp.ok else []
    except Exception:
        live_rules = []

    if not rule_name:
        import random
        rule_name = f"rule_{random.randint(100000, 999999)}"
        while any(lr.get("comment") == rule_name for lr in live_rules):
            rule_name = f"rule_{random.randint(100000, 999999)}"
    # Name uniqueness check removed to allow duplicate comments (Standard Netbird behavior)

    if action not in ('allow', 'drop'):
        return jsonify({"error": "Action must be 'allow' or 'drop'"}), 400

    if protocol not in ('tcp', 'udp', 'tcp+udp', 'icmp', 'any'):
        return jsonify({"error": "Protocol must be 'tcp', 'udp', 'tcp+udp', 'icmp', or 'any'"}), 400

    try:
        src_parts = _validate_address_spec(src_ip)
    except ValueError as e:
        return jsonify({"error": f"Source Address Error: {str(e)}"}), 400

    try:
        dst_parts = _validate_address_spec(dst_ip)
    except ValueError as e:
        return jsonify({"error": f"Destination Address Error: {str(e)}"}), 400

    try:
        src_port_parts = _validate_port_spec(src_port)
    except ValueError as e:
        return jsonify({"error": f"Source Port Error: {str(e)}"}), 400

    try:
        dst_port_parts = _validate_port_spec(dst_port)
    except ValueError as e:
        return jsonify({"error": f"Destination Port Error: {str(e)}"}), 400

    if protocol in ('icmp', 'any') and (src_port_parts or dst_port_parts):
        return jsonify({"error": "Ports are not allowed with protocol ICMP or ANY"}), 400

    if order is not None:
        try:
            order = int(order)
            if order < 0:
                raise ValueError()
        except ValueError:
            return jsonify({"error": "Order must be a non-negative integer"}), 400

    agent_url = f"http://{peer_ip}:8765/firewall/rules"
    agent_payload = {
        "comment": rule_name,
        "action": action,
        "protocol": protocol,
        "src": src_parts,
        "src_port": src_port_parts,
        "dst": dst_parts,
        "dst_port": dst_port_parts,
        "enabled": True
    }
    if order is not None:
        agent_payload["order"] = order

    try:
        resp = requests.post(agent_url, json=agent_payload, timeout=20)
        if resp.ok:
            # Invalidate cache
            with _FIREWALL_CACHE_LOCK:
                _FIREWALL_RULES_CACHE.pop(peer_id, None)
            return jsonify({"success": True, "rule_id": 999}), 201
        else:
            try:
                err_data = resp.json()
                error_msg = err_data.get("message") or err_data.get("detail") or resp.text
            except Exception:
                error_msg = resp.text
            raise Exception(error_msg)
    except Exception as e:
        current_app.logger.error(f"Failed to add firewall rule on agent: {e}")
        return jsonify({"error": f"Failed to apply rule on : {str(e)}"}), 502


@client_bp.route('/api/peers/<peer_id>/firewall/rules/<int:rule_id>/toggle', methods=['POST'])
@login_required
def toggle_peer_firewall_rule(peer_id, rule_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    # Resolve peer IP
    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": " IP not found"}), 404
    peer_ip = peer.get("ip")

    # Fetch live rules
    try:
        live_resp = requests.get(f"http://{peer_ip}:8765/firewall/rules", timeout=10)
        if not live_resp.ok:
            raise Exception("Failed to fetch live rules")
        live_rules = live_resp.json().get("rules", [])
    except Exception as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503

    if rule_id < 1 or rule_id > len(live_rules):
        return jsonify({"error": "Rule not found"}), 404

    lr = live_rules[rule_id - 1]
    rule_slug = lr.get("id")
    new_enabled = not lr.get("enabled", True)

    try:
        if new_enabled:
            url = f"http://{peer_ip}:8765/firewall/rules/enable"
        else:
            url = f"http://{peer_ip}:8765/firewall/rules/disable"
            
        payload = {"ids": [rule_slug]}
        resp = requests.post(url, json=payload, timeout=10)
        if resp.ok and resp.json().get("ok"):
            with _FIREWALL_CACHE_LOCK:
                _FIREWALL_RULES_CACHE.pop(peer_id, None)
            return jsonify({"success": True, "enabled": new_enabled}), 200
        else:
            raise Exception("Agent toggle returned failure")
    except Exception as e:
        return jsonify({"error": f"Failed to toggle rule on : {e}"}), 502


@client_bp.route('/api/peers/<peer_id>/firewall/rules/<int:rule_id>', methods=['PUT'])
@login_required
def edit_peer_firewall_rule(peer_id, rule_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    req_data = request.get_json() or {}
    rule_name = req_data.get('rule_name')
    rule_name = rule_name.strip() if rule_name else ''
    
    action = req_data.get('action')
    action = action.lower() if action else 'drop'
    if action == 'accept':
        action = 'allow'
    
    protocol = req_data.get('protocol')
    protocol = protocol.lower() if protocol else 'any'
    
    src_ip = req_data.get('src_ip')
    src_ip = src_ip.strip() if (src_ip and isinstance(src_ip, str)) else None
    
    dst_ip = req_data.get('dst_ip')
    dst_ip = dst_ip.strip() if (dst_ip and isinstance(dst_ip, str)) else None
    
    src_port = req_data.get('src_port')
    src_port = src_port.strip() if (src_port and isinstance(src_port, str)) else None
    
    dst_port = req_data.get('dst_port')
    dst_port = dst_port.strip() if (dst_port and isinstance(dst_port, str)) else None

    order = req_data.get('order')

    # Resolve peer IP
    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": " IP not found"}), 404
    peer_ip = peer.get("ip")

    # Fetch live rules
    try:
        live_resp = requests.get(f"http://{peer_ip}:8765/firewall/rules", timeout=10)
        if not live_resp.ok:
            raise Exception("Failed to fetch live rules")
        live_rules = live_resp.json().get("rules", [])
    except Exception as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503

    if rule_id < 1 or rule_id > len(live_rules):
        return jsonify({"error": "Rule not found"}), 404

    lr = live_rules[rule_id - 1]
    old_slug = lr.get("id")
    rule_order = lr.get("order") if order is None else order

    if not rule_name:
        rule_name = lr.get("comment", "")
        if not rule_name:
            import random
            rule_name = f"rule_{random.randint(100000, 999999)}"

    # Name uniqueness check removed to allow duplicate comments (Standard Netbird behavior)

    if action not in ('allow', 'drop'):
        return jsonify({"error": "Action must be 'allow' or 'drop'"}), 400

    if protocol not in ('tcp', 'udp', 'tcp+udp', 'icmp', 'any'):
        return jsonify({"error": "Protocol must be 'tcp', 'udp', 'tcp+udp', 'icmp', or 'any'"}), 400

    try:
        src_parts = _validate_address_spec(src_ip)
    except ValueError as e:
        return jsonify({"error": f"Source Address Error: {str(e)}"}), 400

    try:
        dst_parts = _validate_address_spec(dst_ip)
    except ValueError as e:
        return jsonify({"error": f"Destination Address Error: {str(e)}"}), 400

    try:
        src_port_parts = _validate_port_spec(src_port)
    except ValueError as e:
        return jsonify({"error": f"Source Port Error: {str(e)}"}), 400

    try:
        dst_port_parts = _validate_port_spec(dst_port)
    except ValueError as e:
        return jsonify({"error": f"Destination Port Error: {str(e)}"}), 400

    if protocol in ('icmp', 'any') and (src_port_parts or dst_port_parts):
        return jsonify({"error": "Ports are not allowed with protocol ICMP or ANY"}), 400

    if order is not None:
        try:
            order = int(order)
            if order < 0:
                raise ValueError()
        except ValueError:
            return jsonify({"error": "Order must be a non-negative integer"}), 400

    # Update rule on agent using PUT
    agent_url = f"http://{peer_ip}:8765/firewall/rules/{old_slug}"
    agent_payload = {
        "comment": rule_name,
        "action": action,
        "protocol": protocol,
        "src": src_parts,
        "src_port": src_port_parts,
        "dst": dst_parts,
        "dst_port": dst_port_parts,
        "enabled": lr.get("enabled", True)
    }
    if rule_order is not None:
        agent_payload["order"] = rule_order

    try:
        resp = requests.put(agent_url, json=agent_payload, timeout=20)
        if resp.ok:
            with _FIREWALL_CACHE_LOCK:
                _FIREWALL_RULES_CACHE.pop(peer_id, None)
            return jsonify({"success": True}), 200
        else:
            try:
                err_data = resp.json()
                error_msg = err_data.get("message") or err_data.get("detail") or resp.text
            except Exception:
                error_msg = resp.text
            raise Exception(error_msg)
    except Exception as e:
        current_app.logger.error(f"Failed to edit firewall rule on agent: {e}")
        return jsonify({"error": f"Failed to edit rule on : {str(e)}"}), 502


@client_bp.route('/api/peers/<peer_id>/firewall/rules/<int:rule_id>', methods=['DELETE'])
@login_required
def delete_peer_firewall_rule(peer_id, rule_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    # Resolve peer IP
    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": " IP not found"}), 404
    peer_ip = peer.get("ip")

    # Fetch live rules
    try:
        live_resp = requests.get(f"http://{peer_ip}:8765/firewall/rules", timeout=10)
        if not live_resp.ok:
            raise Exception("Failed to fetch live rules")
        live_rules = live_resp.json().get("rules", [])
    except Exception as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503

    if rule_id < 1 or rule_id > len(live_rules):
        return jsonify({"error": "Rule not found"}), 404

    lr = live_rules[rule_id - 1]
    slug = lr.get("id")

    try:
        url = f"http://{peer_ip}:8765/firewall/rules/remove"
        resp = requests.post(url, json={"ids": [slug]}, timeout=15)
        if resp.ok:
            with _FIREWALL_CACHE_LOCK:
                _FIREWALL_RULES_CACHE.pop(peer_id, None)
            return jsonify({"success": True}), 200
        else:
            raise Exception("Agent remove rule returned failure")
    except Exception as e:
        return jsonify({"error": f"Failed to delete rule on : {e}"}), 502


@client_bp.route('/api/peers/<peer_id>/firewall/rules/bulk', methods=['POST'])
@login_required
def bulk_peer_firewall_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    req_data = request.get_json() or {}
    action = req_data.get('action') # 'enable', 'disable', 'delete'
    rule_ids = req_data.get('rule_ids') # list of 1-based indices, e.g. [1, 2, 3]

    if not action or not rule_ids:
        return jsonify({"error": "Invalid payload"}), 400

    # Resolve peer IP
    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": " IP not found"}), 404
    peer_ip = peer.get("ip")

    # Fetch live rules
    try:
        live_resp = requests.get(f"http://{peer_ip}:8765/firewall/rules", timeout=10)
        if not live_resp.ok:
            raise Exception("Failed to fetch live rules")
        live_rules = live_resp.json().get("rules", [])
    except Exception as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503

    # Map the 1-based indices to rule slugs (ids in NetBird agent)
    slugs_to_act = []
    for r_id in rule_ids:
        try:
            r_idx = int(r_id) - 1
            if 0 <= r_idx < len(live_rules):
                lr = live_rules[r_idx]
                slug = lr.get("id")
                if slug:
                    slugs_to_act.append(slug)
        except Exception:
            pass

    if not slugs_to_act:
        return jsonify({"error": "No valid rules found to apply action"}), 404

    try:
        if action == 'enable':
            url = f"http://{peer_ip}:8765/firewall/rules/enable"
        elif action == 'disable':
            url = f"http://{peer_ip}:8765/firewall/rules/disable"
        elif action == 'delete':
            url = f"http://{peer_ip}:8765/firewall/rules/remove"
        else:
            return jsonify({"error": "Unsupported action"}), 400

        resp = requests.post(url, json={"ids": slugs_to_act}, timeout=20)
        if resp.ok:
            # Clear file-backed firewall rules cache
            path = f"/tmp/nbcache_firewall_rules_{peer_id}.json"
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
            
            # Also trigger memory clear if there is any local dict
            with _FIREWALL_CACHE_LOCK:
                _FIREWALL_RULES_CACHE.pop(peer_id, None)
                
            return jsonify({"success": True}), 200
        else:
            raise Exception(f"Agent bulk {action} returned failure")
    except Exception as e:
        return jsonify({"error": f"Failed to perform bulk {action}: {e}"}), 502


@client_bp.route('/api/peers/<peer_id>/firewall/rules/reorder', methods=['POST'])
@login_required
def reorder_peer_firewall_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    req_data = request.get_json() or {}
    items = req_data.get("items", [])
    if not items:
        return jsonify({"error": "No items provided"}), 400

    # Resolve peer IP
    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": " IP not found"}), 404
    peer_ip = peer.get("ip")

    # Fetch live rules
    try:
        live_resp = requests.get(f"http://{peer_ip}:8765/firewall/rules", timeout=10)
        if not live_resp.ok:
            raise Exception("Failed to fetch live rules")
        live_rules = live_resp.json().get("rules", [])
    except Exception as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503

    agent_items = []
    for item in items:
        synthetic_id = item.get("id")
        order = item.get("order")
        if 1 <= synthetic_id <= len(live_rules):
            lr = live_rules[synthetic_id - 1]
            agent_items.append({
                "id": lr.get("id"),
                "order": int(order)
            })

    # Sort agent_items by their requested order, and re-assign contiguous 1..N orders
    agent_items.sort(key=lambda x: x["order"])
    for idx, item in enumerate(agent_items):
        item["order"] = idx + 1

    agent_url = f"http://{peer_ip}:8765/firewall/rules/reorder"
    try:
        resp = requests.post(agent_url, json={"items": agent_items}, timeout=15)
        if resp.ok:
            with _FIREWALL_CACHE_LOCK:
                _FIREWALL_RULES_CACHE.pop(peer_id, None)
            return jsonify(resp.json()), resp.status_code
        return jsonify(resp.json() if resp.headers.get('Content-Type') == 'application/json' else {"error": resp.text}), resp.status_code
    except requests.RequestException as e:
        return jsonify({"error": "Device agent is unreachable"}), 503


@client_bp.route('/api/peers/<peer_id>/firewall/rules/sync', methods=['POST'])
@login_required
def sync_peer_firewall_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    # Resolve peer IP
    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": " IP not found"}), 404
        
    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/firewall/rules/sync"

    try:
        resp = requests.post(agent_url, timeout=20)
        if resp.ok:
            with _FIREWALL_CACHE_LOCK:
                _FIREWALL_RULES_CACHE.pop(peer_id, None)
            return jsonify(resp.json()), resp.status_code
        return jsonify(resp.json() if resp.headers.get('Content-Type') == 'application/json' else {"error": resp.text}), resp.status_code
    except requests.RequestException as e:
        return jsonify({"error": "Device agent is unreachable"}), 503

# --------------------------------------------------------------------------
# Address Lists (Aliases)
# --------------------------------------------------------------------------

@client_bp.route('/api/peers/<peer_id>/aliases', methods=['GET'])
@login_required
def get_peer_address_lists_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"detail": "Peer or Peer IP not found in NetBird"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/aliases"

    try:
        resp = requests.get(agent_url, timeout=10)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "Device agent is offline or unreachable"}), 503

@client_bp.route('/api/peers/<peer_id>/aliases', methods=['POST'])
@login_required
def add_peer_address_list_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"detail": "Peer or Peer IP not found in NetBird"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/aliases"

    try:
        data = request.get_json() or {}
        resp = requests.post(agent_url, json=data, timeout=10)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "Device agent is offline or unreachable"}), 503

@client_bp.route('/api/peers/<peer_id>/aliases/<slug>', methods=['PUT', 'DELETE', 'PATCH'])
@login_required
def modify_peer_address_list_proxy(peer_id, slug):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"detail": "Peer or Peer IP not found in NetBird"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/aliases/{slug}"

    try:
        if request.method == 'PUT':
            data = request.get_json() or {}
            resp = requests.put(agent_url, json=data, timeout=10)
        elif request.method == 'PATCH':
            data = request.get_json() or {}
            resp = requests.patch(agent_url, json=data, timeout=10)
        else:
            resp = requests.delete(agent_url, timeout=10)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "Device agent is offline or unreachable"}), 503

@client_bp.route('/api/peers/<peer_id>/aliases/sync', methods=['POST'])
@login_required
def sync_peer_address_lists_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"detail": "Peer or Peer IP not found in NetBird"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/aliases/sync"

    try:
        resp = requests.post(agent_url, timeout=10)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "Device agent is offline or unreachable"}), 503


# --------------------------------------------------------------------------
# Resolver Configuration
# --------------------------------------------------------------------------

@client_bp.route('/api/peers/<peer_id>/resolver-config', methods=['GET'])
@login_required
def get_peer_resolver_config_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    url = f"{_get_api_base_url()}/api/v1/peers/{peer_id}/adguard/dns_info"
    headers = _get_api_headers()

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "AdGuard service is offline or unreachable"}), 503

@client_bp.route('/api/peers/<peer_id>/resolver-config', methods=['PUT'])
@login_required
def update_peer_resolver_config_proxy(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"detail": "Unauthorized access"}), 403

    url = f"{_get_api_base_url()}/api/v1/peers/{peer_id}/adguard/dns_config"
    headers = _get_api_headers()

    try:
        data = request.get_json() or {}
        
        # 1. Update AdGuard via FastAPI
        resp = requests.post(url, json=data, headers=headers, timeout=10)
        
        # 2. Extract forwarding config and send to Peer Agent's /dns-forwarding endpoint
        upstream_dns = data.get("upstream_dns", [])
        forwarding_config = {}
        for item in upstream_dns:
            # Match standard [/domain/]ip format
            match = re.match(r"^\[/([a-zA-Z0-9._-]+)/\](.+)$", item)
            if match:
                domain = match.group(1)
                ip = match.group(2)
                if domain not in forwarding_config:
                    forwarding_config[domain] = []
                forwarding_config[domain].append(ip)

        # Resolve peer IP and dispatch PUT call to agent
        peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
        peer = next((p for p in peers_data if p.get("id") == peer_id), None)
        if peer and peer.get("ip"):
            peer_ip = peer.get("ip")
            agent_url = f"http://{peer_ip}:8765/dns-forwarding"
            try:
                # Send PUT request to the agent
                agent_resp = requests.put(agent_url, json=forwarding_config, timeout=10)
                if not agent_resp.ok:
                    current_app.logger.error(f"Failed to update dns-forwarding on agent: {agent_resp.text}")
            except Exception as e:
                current_app.logger.error(f"Error communicating with agent for dns-forwarding: {e}")

        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"detail": "AdGuard service is offline or unreachable"}), 503


@client_bp.route('/api/peers/<peer_id>/firewall/rules/<int:rule_id>/reset-counter', methods=['POST'])
@login_required
def reset_peer_firewall_rule_counter(peer_id, rule_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    # Resolve peer IP
    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": " IP not found"}), 404
        
    peer_ip = peer.get("ip")

    # Fetch live rules
    try:
        live_resp = requests.get(f"http://{peer_ip}:8765/firewall/rules", timeout=10)
        if not live_resp.ok:
            raise Exception("Failed to fetch live rules")
        live_rules = live_resp.json().get("rules", [])
    except Exception as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503

    if rule_id < 1 or rule_id > len(live_rules):
        return jsonify({"error": "Rule not found"}), 404

    lr = live_rules[rule_id - 1]
    rule_slug = lr.get("id")
    payload = {"ids": [rule_slug]}
    agent_url = f"http://{peer_ip}:8765/firewall/rules/reset-counter"

    try:
        resp = requests.post(agent_url, json=payload, timeout=15)
        if resp.ok:
            with _FIREWALL_CACHE_LOCK:
                _FIREWALL_RULES_CACHE.pop(peer_id, None)
            return jsonify(resp.json()), resp.status_code
        return jsonify(resp.json() if resp.headers.get('Content-Type') == 'application/json' else {"error": resp.text}), resp.status_code
    except requests.RequestException as e:
        return jsonify({"error": "Device agent is unreachable"}), 503


# --------------------------------------------------------------------------
# Web Filter Management & Rules
# --------------------------------------------------------------------------

@client_bp.route('/peers/<peer_id>/web-filter')
@login_required
def peer_web_filter(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    
    if not customer or not _verify_peer_access(customer, peer_id):
        flash("Unauthorized access to this device.", "error")
        return redirect(url_for('client.dashboard'))

    is_online = False
    peer_name = 'Edge Device'
    
    override_name = _get_name_override(peer_id)
    if override_name:
        peer_name = override_name

    vpn_only = False
    try:
        base_url = _get_api_base_url()
        headers = _get_api_headers()
        peers_data = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
        peer_data = next((p for p in peers_data if p.get("id") == peer_id), None)
        if peer_data:
            checked_peer = _check_single_peer_handshake(peer_data, base_url, headers)
            is_online = checked_peer.get("is_online", False)
            if not override_name and checked_peer.get('name'):
                peer_name = checked_peer.get('name')
            if peer_data.get("ip"):
                vpn_only = get_cached_peer_vpn_only(peer_id, peer_data.get("ip"))
    except Exception as e:
        current_app.logger.error(f"Error checking peer status on loading web filter page: {e}")

    return render_template(
        'web_filter.html',
        peer_id=peer_id,
        peer_name=peer_name,
        customer_name=session.get('client_customer_name'),
        is_online=is_online,
        vpn_only=vpn_only
    )


@client_bp.route('/api/peers/<peer_id>/web-filter/rules', methods=['GET'])
@login_required
def get_peer_web_filter_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"rules": [], "agent_online": False}), 200

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules"
    try:
        resp = requests.get(agent_url, timeout=10)
        if resp.ok:
            data = resp.json()
            return jsonify({
                "rules": data.get("rules", []),
                "agent_online": True
            }), 200
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"rules": [], "agent_online": False, "error": str(e)}), 200


@client_bp.route('/api/peers/<peer_id>/web-filter/rules', methods=['POST'])
@login_required
def add_peer_web_filter_rule(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules"
    payload = request.get_json() or {}
    
    try:
        resp = requests.post(agent_url, json=payload, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503


@client_bp.route('/api/peers/<peer_id>/web-filter/rules/<rule_id>', methods=['PUT'])
@login_required
def update_peer_web_filter_rule(peer_id, rule_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules/{rule_id}"
    payload = request.get_json() or {}
    
    try:
        resp = requests.put(agent_url, json=payload, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503


@client_bp.route('/api/peers/<peer_id>/web-filter/rules/<rule_id>', methods=['DELETE'])
@login_required
def delete_peer_web_filter_rule(peer_id, rule_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules/remove"
    
    try:
        resp = requests.post(agent_url, json={"ids": [rule_id]}, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503


@client_bp.route('/api/peers/<peer_id>/web-filter/rules/remove', methods=['POST'])
@login_required
def bulk_remove_peer_web_filter_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules/remove"
    payload = request.get_json() or {}
    
    try:
        resp = requests.post(agent_url, json=payload, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503


@client_bp.route('/api/peers/<peer_id>/web-filter/rules/enable', methods=['POST'])
@login_required
def enable_peer_web_filter_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules/enable"
    payload = request.get_json() or {}
    
    try:
        resp = requests.post(agent_url, json=payload, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503


@client_bp.route('/api/peers/<peer_id>/web-filter/rules/disable', methods=['POST'])
@login_required
def disable_peer_web_filter_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules/disable"
    payload = request.get_json() or {}
    
    try:
        resp = requests.post(agent_url, json=payload, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503


@client_bp.route('/api/peers/<peer_id>/web-filter/rules/reorder', methods=['POST'])
@login_required
def reorder_peer_web_filter_rules(peer_id):
    customer_id = session.get('client_customer_id')
    customer = Client.query.get(customer_id) if customer_id else None
    if not customer or not _verify_peer_access(customer, peer_id):
        return jsonify({"error": "Unauthorized"}), 403

    peers_data = get_cached_all_netbird_peers(_get_api_base_url(), _get_api_headers())
    peer = next((p for p in peers_data if p.get("id") == peer_id), None)
    if not peer or not peer.get("ip"):
        return jsonify({"error": "Peer IP not found"}), 404

    peer_ip = peer.get("ip")
    agent_url = f"http://{peer_ip}:8765/web-filter/rules/reorder"
    payload = request.get_json() or {}
    
    try:
        resp = requests.post(agent_url, json=payload, timeout=15)
        return (resp.text, resp.status_code, {'Content-Type': 'application/json'})
    except requests.RequestException as e:
        return jsonify({"error": f"Device agent is offline or unreachable: {e}"}), 503