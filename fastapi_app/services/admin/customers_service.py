# /opt/networkat_sdwan/core/web_app/fastapi_app/services/admin/customers_service.py
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from fastapi import HTTPException, status
from werkzeug.security import generate_password_hash

from models.client import Client
from models.subscription_plan import SubscriptionPlan
from models.group_peer import GroupPeer
from services.subscription_service import SubscriptionService
from services.netbird_service import (
    get_cached_all_netbird_peers,
    check_single_peer_handshake,
    get_api_base_url,
    get_api_headers,
)

logger = logging.getLogger(__name__)


class AdminCustomersService:
    """Service layer for Admin Customers and Subscriptions management."""

    @classmethod
    def list_customers(
        cls,
        db: Session,
        search: Optional[str] = None,
        status_filter: Optional[str] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> Dict[str, Any]:
        """
        Lists customers with optional search and status filtering,
        including live peer device statistics.
        """
        query = db.query(Client)

        if search:
            s = f"%{search.strip().lower()}%"
            query = query.filter(
                or_(
                    func.lower(Client.client_name).like(s),
                    func.lower(Client.username).like(s),
                    func.lower(Client.client_email).like(s),
                    func.lower(Client.client_company_name).like(s),
                )
            )

        if status_filter:
            query = query.filter(Client.subscription_status == status_filter.strip().lower())

        total = query.count()
        offset = (page - 1) * per_page
        clients: List[Client] = (
            query.order_by(Client.created_at.desc())
            .offset(offset)
            .limit(per_page)
            .all()
        )

        # Map NetBird peers to clients
        client_group_ids = {c.netbird_group_id for c in clients if c.netbird_group_id}
        group_to_peer_ids: Dict[str, set] = {}
        if client_group_ids:
            all_gps = (
                db.query(GroupPeer)
                .filter(GroupPeer.group_id.in_(client_group_ids))
                .all()
            )
            for gp in all_gps:
                if gp.group_id and gp.peer_id:
                    group_to_peer_ids.setdefault(gp.group_id, set()).add(gp.peer_id)

        # Get online peers from cached NetBird list
        base_url = get_api_base_url()
        headers = get_api_headers()
        all_nb_peers = get_cached_all_netbird_peers(base_url, headers, cache_ttl=15)
        peers_by_id = {p.get("id"): p for p in all_nb_peers if p.get("id")}

        customer_list = []
        for c in clients:
            c_peer_ids = group_to_peer_ids.get(c.netbird_group_id, set())
            peers_count = len(c_peer_ids)

            # Check online count
            online_count = 0
            for pid in c_peer_ids:
                p_raw = peers_by_id.get(pid)
                if p_raw and (p_raw.get("connected") or p_raw.get("is_online")):
                    online_count += 1

            plan_name = (
                c.plan.display_name
                if (c.plan and c.plan.display_name)
                else (c.subscription or "Standard")
            )
            sub_status = c.subscription_status or ("active" if c.active else "inactive")

            customer_list.append({
                "id": str(c.user_id),
                "username": c.username,
                "name": c.client_name,
                "company": c.client_company_name or "",
                "email": c.client_email or "",
                "phone": c.client_phone_number or "",
                "country": c.client_country or "",
                "plan_id": c.plan_id,
                "plan_name": plan_name,
                "status": sub_status,
                "is_active": bool(c.active),
                "peers_count": peers_count,
                "online_count": online_count,
                "allowed_peers_count": c.allowed_peers_count,
                "renewal_date": c.renewal_date.strftime("%Y-%m-%d") if c.renewal_date else None,
                "billing_cycle": c.billing_cycle,
                "is_trial": bool(c.is_trial),
                "created_at": c.created_at.isoformat() if c.created_at else None,
            })

        return {
            "success": True,
            "total": total,
            "page": page,
            "per_page": per_page,
            "customers": customer_list,
        }

    @classmethod
    def get_customer_detail(cls, db: Session, customer_id: str) -> Dict[str, Any]:
        """
        Retrieves full customer metadata, subscription metrics, and associated peers.
        """
        client = db.query(Client).filter(Client.user_id == customer_id).first()
        if not client:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

        sub_svc = SubscriptionService()
        sub_info = sub_svc.get_subscription_info(client)

        # Get customer peers
        base_url = get_api_base_url()
        headers = get_api_headers()
        all_nb_peers = get_cached_all_netbird_peers(base_url, headers, cache_ttl=10)
        peers_by_id = {p.get("id"): p for p in all_nb_peers if p.get("id")}

        c_peer_ids = set()
        if client.netbird_group_id:
            gps = db.query(GroupPeer).filter(GroupPeer.group_id == client.netbird_group_id).all()
            c_peer_ids = {gp.peer_id for gp in gps if gp.peer_id}

        customer_peers = []
        online_count = 0
        for pid in c_peer_ids:
            raw = peers_by_id.get(pid, {})
            hs = check_single_peer_handshake(raw, base_url, headers) if raw else {}
            is_online = bool(hs.get("is_online"))
            if is_online:
                online_count += 1
            customer_peers.append({
                "id": pid,
                "name": hs.get("name") or raw.get("name") or "Unnamed peer",
                "ip": hs.get("ip") or raw.get("ip") or "—",
                "is_online": is_online,
                "last_seen": raw.get("last_seen") or "",
                "os": raw.get("os") or "",
                "version": raw.get("version") or "",
            })

        plan_name = (
            client.plan.display_name
            if (client.plan and client.plan.display_name)
            else (client.subscription or "Standard")
        )
        sub_status = client.subscription_status or ("active" if client.active else "inactive")

        customer_data = {
            "id": str(client.user_id),
            "username": client.username,
            "name": client.client_name,
            "company": client.client_company_name or "",
            "email": client.client_email or "",
            "phone": client.client_phone_number or "",
            "country": client.client_country or "",
            "plan_id": client.plan_id,
            "plan_name": plan_name,
            "status": sub_status,
            "is_active": bool(client.active),
            "peers_count": len(customer_peers),
            "online_count": online_count,
            "allowed_peers_count": client.allowed_peers_count,
            "renewal_date": client.renewal_date.strftime("%Y-%m-%d") if client.renewal_date else None,
            "billing_cycle": client.billing_cycle,
            "is_trial": bool(client.is_trial),
            "created_at": client.created_at.isoformat() if client.created_at else None,
        }

        return {
            "success": True,
            "customer": customer_data,
            "subscription": sub_info,
            "peers": customer_peers,
        }

    _flask_app = None

    @classmethod
    def _ensure_app_context(cls):
        from flask import has_app_context
        if has_app_context():
            from contextlib import nullcontext
            return nullcontext()
        if cls._flask_app is None:
            from app import create_app
            cls._flask_app = create_app()
        return cls._flask_app.app_context()

    @classmethod
    def update_customer_status(cls, db: Session, customer_id: str, new_status: str) -> Dict[str, Any]:
        """
        Transitions customer subscription status (active, grace_period, limit_control, inactive).
        """
        client = db.query(Client).filter(Client.user_id == customer_id).first()
        if not client:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

        sub_svc = SubscriptionService()
        old_status = client.subscription_status

        with cls._ensure_app_context():
            if new_status == "active":
                sub_svc.restore_active(client, new_renewal_date=client.renewal_date)
                client.active = True
            elif new_status == "grace_period":
                sub_svc.transition_to_grace_period(client)
            elif new_status == "limit_control":
                sub_svc.transition_to_limit_control(client)
            elif new_status == "inactive":
                sub_svc.transition_to_inactive(client)
                client.active = False

        client.subscription_status = new_status
        try:
            db.commit()
            db.refresh(client)
        except Exception as e:
            db.rollback()
            logger.error("Error committing customer status change: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update customer status"
            )

        sub_info = sub_svc.get_subscription_info(client)
        return {
            "success": True,
            "message": "Status updated",
            "subscription": sub_info,
        }

    @classmethod
    def update_customer_plan(
        cls,
        db: Session,
        customer_id: str,
        plan_id: int,
        billing_cycle: Optional[str] = None,
        allowed_peers_count: Optional[int] = None,
        renewal_date: Optional[str] = None,
        is_trial: Optional[bool] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upgrades or updates customer plan, quotas, billing cycle, renewal dates, and status.
        """
        client = db.query(Client).filter(Client.user_id == customer_id).first()
        if not client:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
        if not plan:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

        old_plan_id = client.plan_id
        client.plan_id = plan.id
        client.subscription = plan.name

        # Peer device limit override or plan default
        if allowed_peers_count is not None and allowed_peers_count > 0:
            client.allowed_peers_count = allowed_peers_count
        elif plan.id != old_plan_id:
            client.allowed_peers_count = plan.allowed_peers_count

        if billing_cycle in ("monthly", "yearly"):
            client.billing_cycle = billing_cycle

        if renewal_date:
            try:
                clean_date = renewal_date.split("T")[0]
                client.renewal_date = datetime.strptime(clean_date, "%Y-%m-%d")
                client.renewal_notified_at = None
            except Exception as e:
                logger.warning("Error parsing renewal date for client %s: %s", customer_id, e)

        if is_trial is not None:
            client.is_trial = is_trial

        try:
            db.commit()
            db.refresh(client)
        except Exception as e:
            db.rollback()
            logger.error("Error updating customer plan: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update customer plan"
            )

        if status:
            cls.update_customer_status(db=db, customer_id=customer_id, new_status=status)

        sub_svc = SubscriptionService()
        sub_info = sub_svc.get_subscription_info(client)
        return {
            "success": True,
            "message": "Plan updated",
            "subscription": sub_info,
        }

    @classmethod
    def reset_password(
        cls,
        db: Session,
        customer_id: str,
        password: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Resets password for customer account or portal user with secure hashing.
        """
        if len(password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters"
            )

        target_id = user_id if user_id else customer_id
        client = db.query(Client).filter(Client.user_id == target_id).first()
        if not client and user_id:
            client = db.query(Client).filter(Client.user_id == customer_id).first()

        if not client:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

        client.password_hashed = generate_password_hash(password)

        try:
            db.commit()
            return {
                "success": True,
                "message": "Password reset successfully"
            }
        except Exception as e:
            db.rollback()
            logger.error("Error resetting client password: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to reset password"
            )
