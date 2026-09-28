# /opt/networkat_sdwan/core/web_app/utils/whatsapp.py
import os
import re
import logging
import requests
from flask import current_app

logger = logging.getLogger(__name__)


def _get_whatsapp_config():
    """Retrieve WhatsApp API URL and token from config or environment."""
    try:
        api_url = current_app.config.get("WHATSAPP_API_URL")
        api_token = current_app.config.get("WHATSAPP_API_TOKEN")
    except Exception:
        api_url = None
        api_token = None

    if not api_url:
        api_url = os.getenv("WHATSAPP_API_URL", "").strip()
    if not api_token:
        api_token = os.getenv("WHATSAPP_API_TOKEN", "").strip()

    return api_url, api_token


def is_whatsapp_configured() -> bool:
    """Return True if both WhatsApp API URL and token are configured."""
    api_url, api_token = _get_whatsapp_config()
    return bool(api_url and api_token)


def normalize_phone_number(phone: str) -> str:
    """Normalize phone number to international format (E.164 without spaces/dashes)."""
    if not phone:
        return ""
    clean = re.sub(r"[^\d+]", "", phone.strip())
    if clean and not clean.startswith("+"):
        clean = "+" + clean
    return clean


def send_whatsapp_otp(phone_number: str, code: str) -> tuple[bool, str | None]:
    """
    Sends a 6-digit OTP verification code via WhatsApp.
    Operates in Mock Mode if WHATSAPP_API_URL or WHATSAPP_API_TOKEN is not configured.
    
    Returns:
        (True, None) on success
        (False, error_message) on failure
    """
    normalized_phone = normalize_phone_number(phone_number)
    if not normalized_phone or len(normalized_phone) < 8:
        return False, "Invalid phone number format."

    api_url, api_token = _get_whatsapp_config()

    # Mock mode in development or when credentials are not configured yet
    if not api_url or not api_token:
        msg = f"[WhatsApp Mock Mode] Sent OTP code {code} to {normalized_phone}"
        try:
            current_app.logger.info(msg)
        except Exception:
            logger.info(msg)
        print(f"\n=========================================\n{msg}\n=========================================\n")
        return True, None

    # Real WhatsApp gateway request
    message_text = f"Your Networkat verification code is: {code}\nThis code is valid for 10 minutes."
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "phone": normalized_phone.lstrip("+"),
        "phone_number": normalized_phone,
        "message": message_text,
        "code": code
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=10)
        if resp.status_code in (200, 201):
            return True, None
        else:
            err_detail = f"WhatsApp API error: HTTP {resp.status_code} - {resp.text[:150]}"
            try:
                current_app.logger.warning(err_detail)
            except Exception:
                logger.warning(err_detail)
            return False, "Failed to send WhatsApp verification message. Please try again."
    except requests.RequestException as exc:
        err_msg = f"WhatsApp gateway connection failed: {exc}"
        try:
            current_app.logger.error(err_msg)
        except Exception:
            logger.error(err_msg)
        return False, "WhatsApp service temporarily unreachable. Please try again later."
