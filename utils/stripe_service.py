# /opt/networkat_sdwan/core/web_app/utils/stripe_service.py
import os
import hashlib
import logging
from flask import current_app

logger = logging.getLogger(__name__)


def get_stripe_keys() -> tuple[str, str]:
    """Retrieve Stripe publishable and secret keys from app config or environment."""
    try:
        pub_key = current_app.config.get("STRIPE_PUBLISHABLE_KEY")
        sec_key = current_app.config.get("STRIPE_SECRET_KEY")
    except Exception:
        pub_key = None
        sec_key = None

    if not pub_key:
        pub_key = os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()
    if not sec_key:
        sec_key = os.getenv("STRIPE_SECRET_KEY", "").strip()

    return pub_key, sec_key


def is_stripe_mock_mode() -> bool:
    """Return True if running in Stripe mock mode (development or test keys not set)."""
    pub_key, sec_key = get_stripe_keys()
    if not pub_key or not sec_key:
        return True
    if "placeholder" in pub_key.lower() or "placeholder" in sec_key.lower():
        return True
    return False


def create_setup_intent(customer_name: str | None = None, customer_email: str | None = None) -> tuple[str | None, str | None, str | None]:
    """
    Creates a Stripe SetupIntent for saving a card without charging.
    
    Returns:
        (client_secret, customer_id, error_message)
    """
    pub_key, sec_key = get_stripe_keys()

    if is_stripe_mock_mode():
        mock_id = hashlib.sha256(f"{customer_email}_{customer_name}".encode()).hexdigest()[:12]
        return f"seti_mock_secret_{mock_id}", f"cus_mock_{mock_id}", None

    try:
        import stripe
        stripe.api_key = sec_key
        customer = stripe.Customer.create(
            name=customer_name or "",
            email=customer_email or "",
            description="Networkat SD-WAN Trial Customer"
        )
        setup_intent = stripe.SetupIntent.create(
            customer=customer.id,
            payment_method_types=["card"],
            usage="off_session"
        )
        return setup_intent.client_secret, customer.id, None
    except Exception as e:
        logger.error("Failed to create Stripe SetupIntent: %s", e)
        # In non-production or if stripe credentials error out, fall back safely
        if not sec_key.startswith("sk_live_"):
            mock_id = hashlib.sha256(f"{customer_email}".encode()).hexdigest()[:12]
            return f"seti_mock_secret_{mock_id}", f"cus_mock_{mock_id}", None
        return None, None, "Unable to initialize payment verification. Please try again."


def verify_and_extract_card(payment_method_id: str) -> tuple[dict | None, str | None]:
    """
    Retrieves the PaymentMethod from Stripe and extracts card details including fingerprint.
    
    Returns:
        (card_data_dict, error_message)
        where card_data_dict contains: {"fingerprint": str, "brand": str, "last4": str, "payment_method_id": str}
    """
    if not payment_method_id:
        return None, "Payment method ID is missing."

    pub_key, sec_key = get_stripe_keys()

    # Handle Mock Mode or mock payment methods
    if is_stripe_mock_mode() or payment_method_id.startswith(("pm_mock_", "mock_", "pm_card_")):
        # Generate a consistent fingerprint from the mock payment method or token
        h = hashlib.sha256(payment_method_id.strip().encode()).hexdigest()[:24]
        mock_fingerprint = f"fp_mock_{h}"
        return {
            "fingerprint": mock_fingerprint,
            "brand": "visa",
            "last4": "4242",
            "payment_method_id": payment_method_id
        }, None

    try:
        import stripe
        stripe.api_key = sec_key
        pm = stripe.PaymentMethod.retrieve(payment_method_id)
        if not pm or not getattr(pm, "card", None):
            return None, "Invalid card details received."

        fingerprint = pm.card.fingerprint
        if not fingerprint:
            return None, "Card fingerprint could not be determined."

        return {
            "fingerprint": fingerprint,
            "brand": getattr(pm.card, "brand", "card"),
            "last4": getattr(pm.card, "last4", "****"),
            "payment_method_id": pm.id
        }, None
    except Exception as e:
        logger.error("Stripe card retrieval error: %s", e)
        if not sec_key.startswith("sk_live_"):
            h = hashlib.sha256(payment_method_id.strip().encode()).hexdigest()[:24]
            return {
                "fingerprint": f"fp_mock_{h}",
                "brand": "visa",
                "last4": "4242",
                "payment_method_id": payment_method_id
            }, None
        return None, "Failed to verify payment card. Please check your card information."


def is_card_fingerprint_used(fingerprint: str) -> bool:
    """Check if the card fingerprint has already been used for another account."""
    if not fingerprint:
        return False
    from models.client import Client
    existing = Client.query.filter_by(card_fingerprint=fingerprint).first()
    return existing is not None
