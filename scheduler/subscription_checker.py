# /opt/networkat_sdwan/core/web_app/scheduler/subscription_checker.py
"""
Background Subscription Checker Job.

Periodically evaluates client subscription lifecycles:
1. Sends email reminders 3 days before renewal date (one reminder per cycle).
2. Transitions expired 'active' clients to 'grace_period' (3-day grace).
3. Transitions expired 'grace_period' clients to 'limit_control' (read-only mode).
4. Transitions expired 'limit_control' clients (7 days after grace period) to 'inactive' (isolation).
"""
import os
import sys
import time
import signal
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Add application root to python path if not present
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.database import db
from models.client import Client
from services.subscription_service import SubscriptionService
from utils.email import send_renewal_reminder_email

logger = logging.getLogger("subscription_checker")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [subscription_checker] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def check_client_subscription(client, sub_service: SubscriptionService, now: datetime = None) -> dict:
    """
    Evaluates a single client's subscription status and applies necessary transitions/notifications.
    Returns a dict with actions taken.
    """
    if now is None:
        now = datetime.utcnow()

    actions = []

    # ------------------------------------------------------------------
    # 1. Check Renewal Reminder (3 Days Before Renewal)
    # ------------------------------------------------------------------
    if client.renewal_date and client.subscription_status == "active":
        # Make comparison timezone-naive UTC for consistency
        ren_date = client.renewal_date.replace(tzinfo=None) if hasattr(client.renewal_date, "tzinfo") and client.renewal_date.tzinfo else client.renewal_date
        reminder_threshold = ren_date - timedelta(days=3)

        if reminder_threshold <= now < ren_date and client.renewal_notified_at is None:
            plan_name = client.plan.name if client.plan else "starter"
            to_email = client.client_email

            if to_email:
                success, err = send_renewal_reminder_email(
                    to_email=to_email,
                    client_name=client.client_name or client.username,
                    renewal_date=ren_date,
                    plan_name=plan_name
                )
                if success:
                    client.renewal_notified_at = now
                    db.session.commit()
                    logger.info(f"Sent renewal reminder email to '{to_email}' for client '{client.username}'.")
                    actions.append("reminder_sent")
                else:
                    logger.error(f"Failed sending renewal reminder to '{to_email}': {err}")

    # ------------------------------------------------------------------
    # 2. Check Active -> Grace Period
    # ------------------------------------------------------------------
    if client.subscription_status == "active" and client.renewal_date:
        ren_date = client.renewal_date.replace(tzinfo=None) if hasattr(client.renewal_date, "tzinfo") and client.renewal_date.tzinfo else client.renewal_date
        if ren_date < now:
            sub_service.transition_to_grace_period(client, days=3)
            logger.warning(f"Client '{client.username}' subscription expired on {ren_date}. Transitioned to 'grace_period'.")
            actions.append("transition_to_grace_period")

    # ------------------------------------------------------------------
    # 3. Check Grace Period -> Limit Control (Read-Only)
    # ------------------------------------------------------------------
    elif client.subscription_status == "grace_period" and client.grace_expires_at:
        grace_exp = client.grace_expires_at.replace(tzinfo=None) if hasattr(client.grace_expires_at, "tzinfo") and client.grace_expires_at.tzinfo else client.grace_expires_at
        if grace_exp < now:
            sub_service.transition_to_limit_control(client)
            logger.warning(f"Client '{client.username}' grace period expired on {grace_exp}. Transitioned to 'limit_control'.")
            actions.append("transition_to_limit_control")

    # ------------------------------------------------------------------
    # 4. Check Limit Control -> Inactive (Total Isolation)
    # (7 days after grace period expires)
    # ------------------------------------------------------------------
    elif client.subscription_status == "limit_control" and client.grace_expires_at:
        grace_exp = client.grace_expires_at.replace(tzinfo=None) if hasattr(client.grace_expires_at, "tzinfo") and client.grace_expires_at.tzinfo else client.grace_expires_at
        inactive_threshold = grace_exp + timedelta(days=7)
        if inactive_threshold < now:
            sub_service.transition_to_inactive(client)
            logger.error(f"Client '{client.username}' limit_control period exceeded 7 days. Transitioned to 'inactive'.")
            actions.append("transition_to_inactive")

    return {
        "username": client.username,
        "status": client.subscription_status,
        "actions": actions
    }


def check_all_subscriptions(app=None, now: datetime = None) -> dict:
    """
    Iterates through all clients and checks their subscription state.
    """
    if app is None:
        from client_app import create_client_app
        app = create_client_app()

    results = {
        "total_clients": 0,
        "actions_count": 0,
        "errors": 0,
        "details": []
    }

    with app.app_context():
        sub_service = SubscriptionService()
        clients = Client.query.all()
        results["total_clients"] = len(clients)

        for c in clients:
            try:
                res = check_client_subscription(c, sub_service, now=now)
                if res["actions"]:
                    results["actions_count"] += len(res["actions"])
                    results["details"].append(res)
            except Exception as exc:
                results["errors"] += 1
                logger.error(f"Error checking subscription for client '{c.username}': {exc}", exc_info=True)

    logger.info(
        f"Subscription check cycle completed: {results['total_clients']} clients checked, "
        f"{results['actions_count']} actions taken, {results['errors']} errors."
    )
    return results


def run_scheduler_loop(interval_seconds: int = None):
    """
    Continuous background loop for running subscription checks.
    """
    if interval_seconds is None:
        interval_seconds = int(os.getenv("SUBSCRIPTION_CHECK_INTERVAL", 21600))  # Default 6 hours

    logger.info(f"Starting subscription checker daemon loop (interval: {interval_seconds}s)...")

    running = True

    def _handle_sigterm(signum, frame):
        nonlocal running
        logger.info(f"Received signal {signum}, stopping subscription checker gracefully...")
        running = False

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    from client_app import create_client_app
    app = create_client_app()

    while running:
        start_t = time.time()
        try:
            check_all_subscriptions(app=app)
        except Exception as e:
            logger.error(f"Unexpected error in subscription checker cycle: {e}", exc_info=True)

        # Sleep in small increments to be responsive to termination signals
        elapsed = time.time() - start_t
        remaining_sleep = max(1.0, interval_seconds - elapsed)

        while running and remaining_sleep > 0:
            step = min(5.0, remaining_sleep)
            time.sleep(step)
            remaining_sleep -= step

    logger.info("Subscription checker stopped.")


if __name__ == "__main__":
    interval = int(os.getenv("SUBSCRIPTION_CHECK_INTERVAL", 21600))
    # If run with --once argument, execute once and exit (for CLI / testing / cron)
    if "--once" in sys.argv:
        from client_app import create_client_app
        app = create_client_app()
        check_all_subscriptions(app=app)
    else:
        run_scheduler_loop(interval_seconds=interval)
