# /opt/networkat_sdwan/core/web_app/services/subscription_service.py
import os
import time
import requests
from datetime import datetime, timedelta
from flask import current_app
from config.database import db
from repositories.client_repository import ClientRepository
from repositories.subscription_plan_repository import SubscriptionPlanRepository


class SubscriptionService:
    """
    خدمة إدارة الاشتراكات:
    - التحقق من حالة الاشتراك وحصة الأجهزة (Peer Quota)
    - توليد مفاتيح التثبيت أحادية الاستخدام (One-Off Setup Keys)
    - تطبيق سياسات العزل والتحكم عبر NetBird API
    """

    NETBIRD_API_URL = os.getenv("FASTAPI_BASE_URL", "https://api.networkat.cloud/api/v2/netbird")
    ALL_PEERS_GROUP_ID = os.getenv("NETBIRD_ALL_PEERS_GROUP_ID")  # ID Group 'all-peers'

    def __init__(self):
        self.client_repo = ClientRepository()
        self.plan_repo = SubscriptionPlanRepository()
        self.api_key = os.getenv("INTERNAL_API_KEY", "57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874")
        self.base_url = self.NETBIRD_API_URL.rstrip("/")

    def _get_headers(self) -> dict:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    # ----------------------------------------------------------------------
    # 1. Peer Counting & Quota Management
    # ----------------------------------------------------------------------

    def get_client_peer_count(self, client) -> int:
        """
        جلب عدد الأجهزة (Peers) المسجلة حالياً للعميل من خلال مجموعته في NetBird.
        """
        if not client or not getattr(client, "netbird_group_id", None):
            return 0

        url = f"{self.base_url}/groups/{client.netbird_group_id}"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=5)
            if resp.status_code == 200:
                group_data = resp.json()
                if "peers_count" in group_data and group_data["peers_count"] is not None:
                    return int(group_data["peers_count"])
                peers = group_data.get("peers") or []
                return len(peers)
            else:
                current_app.logger.warning(
                    f"[SubscriptionService] Failed to fetch group {client.netbird_group_id}: HTTP {resp.status_code}"
                )
        except Exception as exc:
            current_app.logger.error(
                f"[SubscriptionService] Error fetching NetBird group {client.netbird_group_id}: {exc}"
            )

        # Fallback to local edges count if NetBird call fails
        if hasattr(client, "edges"):
            return len(client.edges)
        return 0

    def get_remaining_peers(self, client) -> int:
        """
        حساب عدد الأجهزة المتبقية المسموح للعميل بإضافتها:
        remaining = allowed_peers_count - installed_peers_count
        لا يُسمح بإضافة أجهزة إلا إذا كانت حالة الاشتراك نشطة (active) فقط.
        """
        if not client or getattr(client, "subscription_status", None) != "active":
            return 0

        allowed_peers_count = getattr(client, "allowed_peers_count", None)
        if not isinstance(allowed_peers_count, int):
            plan = getattr(client, "plan", None)
            if plan and isinstance(getattr(plan, "allowed_peers_count", None), int):
                allowed_peers_count = plan.allowed_peers_count
            else:
                starter = self.plan_repo.get_by_name("starter") if hasattr(self, 'plan_repo') and self.plan_repo else None
                allowed_peers_count = starter.allowed_peers_count if starter else 5

        current_count = self.get_client_peer_count(client)
        if not isinstance(current_count, int):
            current_count = 0

        return max(0, allowed_peers_count - current_count)

    def can_install_peer(self, client) -> tuple[bool, str, dict]:
        """
        فحص شامل: هل يُسمح للعميل بتنصيب جهاز جديد؟
        الشروط:
        1. الحساب مفعّل (active=True)
        2. حالة الاشتراك نشطة ('active') فقط (لا يُسمح بإضافة أجهزة في فترة السماح grace_period أو limit_control أو inactive)
        3. عدد الأجهزة الحالية أقل من الحد الأقصى للخطة (current_peers < peer_limit)
        """
        if not client:
            return False, "Client record not found", {}

        if not client.active:
            return False, "Account is disabled. Please contact administrator.", {
                "subscription_status": client.subscription_status
            }

        # التحقق من حالة الاشتراك: لا يُسمح بإضافة peer في فترة السماح أو وضع القراءة فقط أو غير النشط
        if client.subscription_status != "active":
            status_desc = {
                "grace_period": "Adding new peers is not allowed during the grace period. Please renew your subscription.",
                "limit_control": "Subscription is currently restricted. Renew your plan to enroll new peers.",
                "inactive": "Subscription inactive. Renew your plan."
            }.get(client.subscription_status, f"Subscription status '{client.subscription_status}' does not allow adding new peers.")

            return False, status_desc, {
                "subscription_status": client.subscription_status,
                "installed_peers_count": self.get_client_peer_count(client),
                "allowed_peers_count": client.allowed_peers_count or 0,
                "remaining_peers_count": 0
            }

        # تحديد حد الخطة
        plan = client.plan
        if not plan:
            # إسناد خطة افتراضية إذا لم تكن مسندة
            starter = self.plan_repo.get_by_name("starter")
            if starter:
                client.plan_id = starter.id
                db.session.commit()
                plan = starter

        # تحديد حد الأجهزة: المرجع هو client.allowed_peers_count
        allowed_peers_count = getattr(client, 'allowed_peers_count', None)
        if not isinstance(allowed_peers_count, int):
            allowed_peers_count = plan.allowed_peers_count if plan else 5

        installed_peers_count = self.get_client_peer_count(client)

        if installed_peers_count >= allowed_peers_count:
            return False, f"Peer limit reached ({installed_peers_count}/{allowed_peers_count}). Upgrade plan to add more.", {
                "subscription_status": client.subscription_status,
                "installed_peers_count": installed_peers_count,
                "allowed_peers_count": allowed_peers_count,
                "remaining_peers_count": 0
            }

        remaining_peers_count = max(0, allowed_peers_count - installed_peers_count)
        return True, "Allowed", {
            "subscription_status": client.subscription_status,
            "installed_peers_count": installed_peers_count,
            "allowed_peers_count": allowed_peers_count,
            "remaining_peers_count": remaining_peers_count
        }

    # ----------------------------------------------------------------------
    # 2. Dynamic One-Off Setup Key Generation
    # ----------------------------------------------------------------------

    def create_installation_setup_key(self, client) -> tuple[bool, dict]:
        """
        توليد مفتاح تثبيت أحادي الاستخدام (one-off) للعميل بعد التحقق من حصته:
        - صلاحية المفتاح 24 ساعة (أو استخدام لمرة واحدة)
        - يُربط تلقائياً بـ netbird_group_id للعميل وبـ all-peers
        """
        allowed, msg, quota_info = self.can_install_peer(client)
        if not allowed:
            return False, {
                "error": "Forbidden",
                "message": msg,
                **quota_info
            }

        # بناء auto_groups
        auto_groups = []
        if getattr(client, "netbird_group_id", None):
            auto_groups.append(client.netbird_group_id)
        if self.ALL_PEERS_GROUP_ID and self.ALL_PEERS_GROUP_ID not in auto_groups:
            auto_groups.append(self.ALL_PEERS_GROUP_ID)

        payload = {
            "name": f"install-{client.username}-{int(time.time())}",
            "type": "one-off",
            "usage_limit": 1,
            "expires_in": 1200,  # 20 minutes
            "auto_groups": auto_groups,
            "ephemeral": False,
            "allow_extra_dns_labels": False
        }

        url = f"{self.base_url}/setup-keys"
        try:
            resp = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if resp.status_code in (200, 201):
                key_data = resp.json()
                plain_key = key_data.get("key")
                remaining_after = max(0, quota_info["remaining_peers_count"] - 1)

                return True, {
                    "setup_key": plain_key,
                    "username": client.username,
                    "plan": client.plan.name if client.plan else "starter",
                    "allowed_peers_count": quota_info["allowed_peers_count"],
                    "installed_peers_count": quota_info["installed_peers_count"],
                    "remaining_peers_count": remaining_after,
                    "expires_in": 1200,
                    "subscription_status": client.subscription_status
                }
            else:
                current_app.logger.error(
                    f"[SubscriptionService] NetBird setup-key generation failed: HTTP {resp.status_code} - {resp.text}"
                )
                return False, {
                    "error": "External Gateway Error",
                    "message": f"NetBird API rejected key creation: {resp.text}",
                    "status_code": resp.status_code
                }
        except Exception as exc:
            current_app.logger.error(
                f"[SubscriptionService] Exception generating setup-key for {client.username}: {exc}"
            )
            return False, {
                "error": "Internal Server Error",
                "message": "Failed to communicate with setup key provider."
            }

    # ----------------------------------------------------------------------
    # 3. NetBird ACL & Policy Enforcement
    # ----------------------------------------------------------------------

    def _get_client_peer_ids(self, client) -> list[str]:
        """
        استخراج قائمة معرّفات الـ peers التابعة للعميل (من NetBird group ومن قاعدة البيانات).
        """
        peer_ids = set()

        if getattr(client, "netbird_group_id", None):
            url = f"{self.base_url}/groups/{client.netbird_group_id}"
            try:
                resp = requests.get(url, headers=self._get_headers(), timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    for p in (data.get("peers") or []):
                        pid = p.get("id") if isinstance(p, dict) else p
                        if pid:
                            peer_ids.add(pid)
            except Exception as e:
                current_app.logger.warning(f"[SubscriptionService] Error fetching client group peers: {e}")

        # إضافة المعرفات المسجلة في جدول Edges المحلي
        if hasattr(client, "edges"):
            for edge in client.edges:
                if getattr(edge, "netbird_peer_id", None):
                    peer_ids.add(edge.netbird_peer_id)

        return list(peer_ids)

    def _find_client_policies(self, username: str, category_filter: str | None = None) -> dict[str, list[dict]]:
        """
        جلب وتصنيف كافة سياسات NetBird الخاصة بعميل معين:
        - mesh: السياسات المسؤولة عن تواصل الأجهزة بينياً ({username}-allow_mesh أو {username})
        - pkgs: السياسات المسؤولة عن خوادم الحزم ({username}-allow_pkgs_servers أو {username}-pkgs)
        - controllers: السياسات المسؤولة عن الاتصال بالـ Controllers ({username}-controllers أو {username}-allow_controllers)
        - all: كافة سياسات العميل
        """
        result = {
            "mesh": [],
            "pkgs": [],
            "controllers": [],
            "all": []
        }
        seen_ids = set()

        def _add_pol(p, category):
            if p and p.get("id") and p["id"] not in seen_ids:
                seen_ids.add(p["id"])
                result["all"].append(p)
                result[category].append(p)

        # 1. فحص أسماء السياسات القياسية والمستخدمة في NetBird
        if category_filter in (None, "mesh"):
            _add_pol(self._find_policy_by_name(f"{username}-allow_mesh"), "mesh")
            _add_pol(self._find_policy_by_name(username), "mesh")

        if category_filter in (None, "controllers"):
            _add_pol(self._find_policy_by_name(f"{username}-allow_controllers"), "controllers")
            _add_pol(self._find_policy_by_name(f"{username}-controllers"), "controllers")

        if category_filter in (None, "pkgs"):
            _add_pol(self._find_policy_by_name(f"{username}-allow_pkgs_servers"), "pkgs")
            _add_pol(self._find_policy_by_name(f"{username}-pkgs"), "pkgs")

        # 2. فحص شامل لأي سياسات إضافية تبدأ باسم العميل
        url = f"{self.base_url}/policies"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=10)
            if resp.status_code == 200:
                for p in resp.json():
                    name = p.get("name", "").strip()
                    if name == username or name.startswith(f"{username}-"):
                        lower_name = name.lower()
                        if "mesh" in lower_name or name == username:
                            if category_filter in (None, "mesh"):
                                _add_pol(p, "mesh")
                        elif "pkg" in lower_name:
                            if category_filter in (None, "pkgs"):
                                _add_pol(p, "pkgs")
                        elif "controller" in lower_name:
                            if category_filter in (None, "controllers"):
                                _add_pol(p, "controllers")
                        else:
                            if category_filter in (None, "mesh"):
                                _add_pol(p, "mesh")
        except Exception as e:
            current_app.logger.error(f"[SubscriptionService] Error searching policies for '{username}': {e}")

        return result

    def _find_policy_by_name(self, name: str) -> dict | None:
        """
        البحث في سياسات NetBird عن سياسة معينة بالاسم.
        """
        url = f"{self.base_url}/policies"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=10)
            if resp.status_code == 200:
                for p in resp.json():
                    if p.get("name") == name:
                        return p
        except Exception as e:
            current_app.logger.error(f"[SubscriptionService] Error searching policy '{name}': {e}")
        return None

    def _set_policy_enabled(self, policy_id: str, enabled: bool) -> bool:
        """
        تفعيل أو تعطيل سياسة وقواعدها في NetBird عبر PUT /policies/{id}.
        """
        url = f"{self.base_url}/policies/{policy_id}"
        try:
            get_resp = requests.get(url, headers=self._get_headers(), timeout=5)
            if get_resp.status_code != 200:
                current_app.logger.warning(f"[SubscriptionService] Policy {policy_id} not found: HTTP {get_resp.status_code}")
                return False

            payload = get_resp.json()
            rules = []
            for r in payload.get("rules", []):
                rule = {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "description": r.get("description"),
                    "enabled": enabled,
                    "action": r.get("action", "accept"),
                    "bidirectional": r.get("bidirectional", True),
                    "protocol": r.get("protocol", "all"),
                    "sources": [s["id"] if isinstance(s, dict) else s for s in (r.get("sources") or [])],
                    "destinations": [d["id"] if isinstance(d, dict) else d for d in (r.get("destinations") or [])]
                }
                rules.append(rule)

            update_payload = {
                "name": payload.get("name"),
                "description": payload.get("description"),
                "enabled": enabled,
                "rules": rules
            }

            put_resp = requests.put(url, json=update_payload, headers=self._get_headers(), timeout=10)
            if put_resp.status_code in (200, 201):
                current_app.logger.info(f"[SubscriptionService] Policy '{payload.get('name')}' enabled={enabled} updated.")
                return True
            else:
                current_app.logger.error(
                    f"[SubscriptionService] Failed updating policy {policy_id}: HTTP {put_resp.status_code} - {put_resp.text}"
                )
                return False
        except Exception as e:
            current_app.logger.error(f"[SubscriptionService] Exception setting policy {policy_id} enabled={enabled}: {e}")
            return False

    def _remove_peers_from_all_peers_group(self, client) -> bool:
        """
        إزالة أجهزة العميل من مجموعة 'all-peers' لقطع الاتصال بالـ Controllers عند الحالة inactive.
        """
        client_peer_ids = set(self._get_client_peer_ids(client))
        if not client_peer_ids:
            return True

        url = f"{self.base_url}/groups/{self.ALL_PEERS_GROUP_ID}"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=5)
            if resp.status_code != 200:
                current_app.logger.error(f"[SubscriptionService] Failed to get all-peers group: HTTP {resp.status_code}")
                return False

            group_data = resp.json()
            current_peers = [p["id"] if isinstance(p, dict) else p for p in (group_data.get("peers") or [])]
            updated_peers = [pid for pid in current_peers if pid not in client_peer_ids]

            update_payload = {
                "name": group_data.get("name", "all-peers"),
                "peers": updated_peers
            }

            put_resp = requests.put(url, json=update_payload, headers=self._get_headers(), timeout=10)
            if put_resp.status_code in (200, 201):
                current_app.logger.info(
                    f"[SubscriptionService] Removed {len(client_peer_ids)} peers of '{client.username}' from all-peers group."
                )
                return True
            else:
                current_app.logger.error(
                    f"[SubscriptionService] Failed to remove peers from all-peers group: HTTP {put_resp.status_code} - {put_resp.text}"
                )
                return False
        except Exception as e:
            current_app.logger.error(f"[SubscriptionService] Exception removing peers from all-peers: {e}")
            return False

    def _add_peers_to_all_peers_group(self, client) -> bool:
        """
        إعادة إضافة أجهزة العميل إلى مجموعة 'all-peers' عند إعادة التفعيل.
        """
        client_peer_ids = set(self._get_client_peer_ids(client))
        if not client_peer_ids:
            return True

        url = f"{self.base_url}/groups/{self.ALL_PEERS_GROUP_ID}"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=5)
            if resp.status_code != 200:
                current_app.logger.error(f"[SubscriptionService] Failed to get all-peers group: HTTP {resp.status_code}")
                return False

            group_data = resp.json()
            current_peers = set(p["id"] if isinstance(p, dict) else p for p in (group_data.get("peers") or []))
            all_peers_union = list(current_peers | client_peer_ids)

            update_payload = {
                "name": group_data.get("name", "all-peers"),
                "peers": all_peers_union
            }

            put_resp = requests.put(url, json=update_payload, headers=self._get_headers(), timeout=10)
            if put_resp.status_code in (200, 201):
                current_app.logger.info(
                    f"[SubscriptionService] Added {len(client_peer_ids)} peers of '{client.username}' back to all-peers group."
                )
                return True
            else:
                current_app.logger.error(
                    f"[SubscriptionService] Failed to add peers to all-peers group: HTTP {put_resp.status_code} - {put_resp.text}"
                )
                return False
        except Exception as e:
            current_app.logger.error(f"[SubscriptionService] Exception adding peers to all-peers: {e}")
            return False

    # ----------------------------------------------------------------------
    # 4. State Machine Transitions
    # ----------------------------------------------------------------------

    def transition_to_grace_period(self, client, days: int = 3) -> bool:
        """
        الانتقال إلى فترة السماح (grace_period):
        - الحالة: 'grace_period'
        - انتهاء السماح: الآن + days
        - التحكم: كامل بدون تغيير على سياسات NetBird
        """
        if not client:
            return False

        client.subscription_status = "grace_period"
        client.grace_expires_at = datetime.utcnow() + timedelta(days=days)
        db.session.commit()

        current_app.logger.info(
            f"[SubscriptionService] Client '{client.username}' transitioned to 'grace_period' (expires: {client.grace_expires_at})."
        )
        return True

    def transition_to_limit_control(self, client) -> bool:
        """
        الانتقال إلى تقييد التحكم (limit_control) — وضع القراءة فقط:
        - الحالة: 'limit_control'
        - تعطيل سياسة حزم التحديثات ({username}-pkgs) إن وُجدت
        - إبقاء سياسة الـ Mesh ({username}) مفعلة لاستمرار التواصل بين الأجهزة
        - إبقاء عضوية all-peers لاستمرار التواصل مع الـ Controllers
        """
        if not client:
            return False

        client.subscription_status = "limit_control"
        db.session.commit()

        # تعطيل سياسات packages التابعة للعميل في NetBird
        client_policies = self._find_client_policies(client.username, category_filter="pkgs")
        for p in client_policies.get("pkgs", []):
            self._set_policy_enabled(p["id"], False)

        current_app.logger.info(
            f"[SubscriptionService] Client '{client.username}' transitioned to 'limit_control' (read-only mode)."
        )
        return True

    def transition_to_inactive(self, client) -> bool:
        """
        الانتقال إلى غير مفعّل (inactive):
        - الحالة: 'inactive'
        - تعطيل سياسة الـ Mesh ({username}-allow_mesh) وسياسة حزم التحديثات ({username}-allow_pkgs_servers)
        - إبقاء سياسة الـ Controllers ({username}-controllers) مفعلة كما هي للتواصل مع السيرفر
        - إبقاء عضوية all-peers لاستمرار الاتصال بالـ Controllers
        """
        if not client:
            return False

        client.subscription_status = "inactive"
        db.session.commit()

        # تعطيل سياسات mesh و pkgs فقط (إبقاء controllers تعمل بدون تغيير)
        client_policies = self._find_client_policies(client.username)
        target_policies = client_policies.get("mesh", []) + client_policies.get("pkgs", [])
        for p in target_policies:
            self._set_policy_enabled(p["id"], False)

        current_app.logger.info(
            f"[SubscriptionService] Client '{client.username}' transitioned to 'inactive' ({len(target_policies)} policies disabled: mesh & pkgs; controllers kept intact)."
        )
        return True

    def restore_active(
        self,
        client,
        new_renewal_date: datetime | None = None,
        plan_id: int | None = None,
        billing_cycle: str | None = None
    ) -> bool:
        """
        استعادة التفعيل الكامل (active):
        - الحالة: 'active'
        - إعادة تفعيل كافة سياسات العميل في NetBird (mesh, controllers, pkgs)
        - إعادة أجهزة العميل إلى مجموعة all-peers
        - تصفير فترة السماح وتحديث تاريخ التجديد والخطة إن طُلِب
        """
        if not client:
            return False

        client.subscription_status = "active"
        client.grace_expires_at = None

        if new_renewal_date:
            client.renewal_date = new_renewal_date
        if plan_id:
            client.plan_id = plan_id
            plan = self.plan_repo.get_by_id(plan_id)
            if plan and plan.allowed_peers_count is not None:
                client.allowed_peers_count = plan.allowed_peers_count
        if billing_cycle:
            client.billing_cycle = billing_cycle

        db.session.commit()

        # 1. إعادة تفعيل كافة سياسات العميل في NetBird (mesh, controllers, pkgs)
        client_policies = self._find_client_policies(client.username)
        for p in client_policies.get("all", []):
            self._set_policy_enabled(p["id"], True)

        # 2. إعادة الأجهزة إلى all-peers
        self._add_peers_to_all_peers_group(client)

        current_app.logger.info(
            f"[SubscriptionService] Client '{client.username}' restored to 'active' state ({len(client_policies.get('all', []))} policies enabled)."
        )
        return True

    # ----------------------------------------------------------------------
    # 5. Summary Info Helper
    # ----------------------------------------------------------------------

    def get_subscription_info(self, client) -> dict:
        """
        توفير ملخص متكامل لبيانات اشتراك العميل لعرضه في الواجهات والـ APIs.
        """
        if not client:
            return {}

        plan = client.plan
        # Source of truth: client.allowed_peers_count (with plan fallback)
        allowed_peers_count = getattr(client, 'allowed_peers_count', None)
        if not isinstance(allowed_peers_count, int):
            allowed_peers_count = plan.allowed_peers_count if plan else 5

        installed_peers_count = self.get_client_peer_count(client)
        remaining_peers_count = self.get_remaining_peers(client)

        return {
            "username": client.username,
            "status": client.subscription_status,
            "is_active": client.is_subscription_active,
            "is_readonly": client.is_subscription_readonly,
            "is_inactive": client.is_subscription_inactive,
            "can_add_peers": (client.subscription_status == "active" and remaining_peers_count > 0),
            "plan_name": plan.name if plan else "starter",
            "plan_display": plan.display_name if plan else "Starter",
            "plan_id": plan.id if plan else None,
            "allowed_peers_count": allowed_peers_count,
            "installed_peers_count": installed_peers_count,
            "remaining_peers_count": remaining_peers_count,
            "billing_cycle": client.billing_cycle or "monthly",
            "renewal_date": client.renewal_date.isoformat() if client.renewal_date else None,
            "grace_expires_at": client.grace_expires_at.isoformat() if client.grace_expires_at else None,
        }

