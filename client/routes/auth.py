import time
import random
import requests
from threading import Lock
from flask import render_template, request, redirect, url_for, session, flash, jsonify, current_app

from client.blueprint import client_bp
from services.customer_service import CustomerService
from utils.email import send_verification_email, send_password_reset_email

customer_service = CustomerService()

# --------------------------------------------------------------------------
# Public REST API — Setup Key Retrieval
# --------------------------------------------------------------------------
_SETUP_KEY_RATE_LIMIT: dict = {}
_SETUP_KEY_RATE_LOCK = Lock()
_SETUP_KEY_MAX_REQUESTS = 5    # max attempts
_SETUP_KEY_WINDOW_SEC = 60     # per 60 seconds


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
    """
    if not request.is_json:
        return jsonify({
            "error": "Unsupported Media Type",
            "message": "Content-Type must be application/json"
        }), 415

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not _check_rate_limit(client_ip):
        return jsonify({
            "error": "Too Many Requests",
            "message": f"Maximum {_SETUP_KEY_MAX_REQUESTS} attempts per {_SETUP_KEY_WINDOW_SEC} seconds exceeded. Please wait."
        }), 429

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

    try:
        success, res = customer_service.authenticate_client_user(username, password)
    except Exception as exc:
        current_app.logger.error(f"[setup-key-api] Auth exception for '{username}': {exc}")
        return jsonify({
            "error": "Internal Server Error",
            "message": "An unexpected error occurred. Please try again later."
        }), 500

    if not success:
        return jsonify({
            "error": "Unauthorized",
            "message": "Invalid credentials or account is not active."
        }), 401

    customer_id = res.get("customer_id")

    try:
        from repositories.client_repository import ClientRepository
        from services.subscription_service import SubscriptionService

        client_repo = ClientRepository()
        client = client_repo.get_by_id(customer_id)
        if not client:
            return jsonify({
                "error": "Not Found",
                "message": "Client record not found."
            }), 404

        sub_service = SubscriptionService()
        key_success, key_data = sub_service.create_installation_setup_key(client)

        if not key_success:
            status_code = 403 if key_data.get("error") == "Forbidden" else (key_data.get("status_code") or 500)
            return jsonify(key_data), status_code

        current_app.logger.info(
            f"[setup-key-api] Dynamic one-off setup key generated — user='{username}' plan='{key_data.get('plan')}' "
            f"remaining={key_data.get('remaining_peers')} ip={client_ip}"
        )

        return jsonify(key_data), 200

    except Exception as exc:
        current_app.logger.error(f"[setup-key-api] Error generating setup key for '{username}': {exc}")
        return jsonify({
            "error": "Internal Server Error",
            "message": "An error occurred while generating setup key. Please try again later."
        }), 500


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
        if recaptcha_site_key and recaptcha_secret:
            recaptcha_response = request.form.get('g-recaptcha-response')
            if not recaptcha_response:
                flash("Security verification token is missing. Please try again.", "error")
                return render_template('register.html', recaptcha_site_key=recaptcha_site_key)
            try:
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

        if time.time() > verification.get('expires_at', 0):
            flash("Verification code has expired. Please register again.", "error")
            session.pop('reg_verification', None)
            session.pop('reg_data', None)
            return redirect(url_for('client.register'))

        if entered_code != verification.get('code'):
            flash("Invalid verification code. Please try again.", "error")
            return render_template('verify_email.html', email=verification.get('email'))

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
