# /opt/networkat_sdwan/core/web_app/services/customer_service.py
import secrets
import requests
from repositories.edge_repository import EdgeRepository
from repositories.user_repository import UserRepository
from repositories.token_repository import TokenRepository
from repositories.client_repository import ClientRepository
from werkzeug.security import generate_password_hash, check_password_hash


class CustomerService:

    def __init__(self):
        self.client_repo = ClientRepository()
        self.edge_repo = EdgeRepository()
        self.token_repo = TokenRepository()
        self.user_repo = UserRepository()

    def get_dashboard_data(self, online_window=300):
        total_customers = self.client_repo.count()
        total_edges = self.edge_repo.count()
        online_edges = self.edge_repo.count_online(online_window)
        active_tokens = self.token_repo.count_active()
        recent_edges = self.edge_repo.get_recent_edges(limit=10)

        return {
            'total_customers': total_customers,
            'total_edges': total_edges,
            'online_edges': online_edges,
            'offline_edges': total_edges - online_edges,
            'active_tokens': active_tokens,
            'recent_edges': recent_edges,
            'online_window': online_window
        }

    def get_customers_list(self, online_window=300):
        clients = self.client_repo.get_all_desc()
        customers_data = []
        for c in clients:
            # استخدام الميثودز الجديدة المربوطة بـ client_id / user_id
            tokens_count = self.token_repo.count_by_client(c.user_id)
            edges_count = self.edge_repo.count_by_customer(c.user_id)
            online_count = self.edge_repo.count_online_by_customer(c.user_id, online_window)

            customers_data.append({
                'id': c.user_id,
                'name': c.client_name,
                'username': c.username,
                'created_at': c.created_at.strftime('%Y-%m-%d %H:%M:%S') if c.created_at else None,
                'tokens_count': tokens_count,
                'edges_count': edges_count,
                'online_count': online_count
            })
        return customers_data
    
    def get_customer_details(self, customer_id):
        client = self.client_repo.get_by_id(customer_id)
        if not client:
            return None, "Customer not found"

        edges = self.edge_repo.get_by_customer_id(customer_id)
        tokens = self.token_repo.get_by_client(customer_id)
        
        netbird_peers = []
        if hasattr(client, 'netbird_group_id') and client.netbird_group_id:
            FASTAPI_BASE_URL = "https://api.networkat.cloud/api/v2/netbird"
            
            # 🔥 التعديل هنا: إضافة التوكن في الـ Headers
            token = "57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874"
            headers = {
                "accept": "application/json",
                "Authorization": f"Bearer {token}"
            }
            try:
                response = requests.get(f"{FASTAPI_BASE_URL}/groups/{client.netbird_group_id}", headers=headers, timeout=5)
                if response.status_code == 200:
                    group_data = response.json()
                    netbird_peers = group_data.get("peers") if group_data.get("peers") else []
            except Exception as e:
                print(f"Error fetching NetBird peers: {str(e)}")

        if netbird_peers:
            peer_ids = [p.get("id") for p in netbird_peers if isinstance(p, dict) and p.get("id")]
            if peer_ids:
                try:
                    from models.group_peer import GroupPeer
                    records = GroupPeer.query.filter(GroupPeer.peer_id.in_(peer_ids)).all()
                    pwd_map = {r.peer_id: r.adguard_password for r in records if r.adguard_password}
                    for p in netbird_peers:
                        if isinstance(p, dict):
                            p_id = p.get("id")
                            p_ip = p.get("ip")
                            stored_pwd = pwd_map.get(p_id)
                            if (not stored_pwd or stored_pwd in ("default_password", "adguard-api")) and p_ip:
                                try:
                                    cred_resp = requests.get(f"http://{p_ip}:8765/adguard-credential", timeout=1.5)
                                    if cred_resp.ok:
                                        cred_data = cred_resp.json() if cred_resp.headers.get("Content-Type", "").startswith("application/json") else cred_resp.text.strip()
                                        fetched_pwd = cred_data.get("password") if isinstance(cred_data, dict) else str(cred_data).strip()
                                        if fetched_pwd:
                                            stored_pwd = fetched_pwd
                                            target_rec = next((r for r in records if r.peer_id == p_id), None)
                                            if target_rec:
                                                target_rec.adguard_password = fetched_pwd
                                                self.client_repo.flush()
                                except Exception:
                                    pass
                            p["adguard_password"] = stored_pwd or "adguard-api"
                except Exception as e:
                    print(f"Error fetching AdGuard passwords: {str(e)}")
                    for p in netbird_peers:
                        if isinstance(p, dict) and "adguard_password" not in p:
                            p["adguard_password"] = "adguard-api"
        return {
            'customer': client,
            'edges': edges,
            'tokens': tokens,
            'netbird_peers': netbird_peers
        }, None

    def create_customer(self, data):
        """
        data: dict يحتوي على جميع الحقول القادمة من الـ Request
        """
        FASTAPI_BASE_URL = "https://api.networkat.cloud/api/v2/netbird"
        ALL_PEERS_GROUP_ID = "d9gc0fsm4sls73cgjl6g"  # ID Group all-peers
        CONTROLLERS_GROUP_ID = "d9gc4c4m4sls73cgjmfg"   # networkat_controllers
        PKGS_SERVERS_GROUP_ID = "dafif2pttloc73fghbi0"  # networkat_pkgs_servers

        # 1. إضافة Bearer Token في الـ Headers
        token = "57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874"
        headers = {
            "Content-Type": "application/json",
            "accept": "application/json",
            "Authorization": f"Bearer {token}"
        }

        username = data.get('username')
        password = data.get('password')
        client_name = data.get('client_name')

        created_group_id = None
        created_setup_key_id = None
        created_policy_ids = []

        try:
            # 2. إنشاء العميل في جدول public.clients
            client = self.client_repo.create(
                username=username,
                raw_password=password,
                client_name=client_name,
                client_company_name=data.get('client_company_name'),
                client_email=data.get('client_email', f"{username}@networkat.local"),
                client_phone_number=data.get('client_phone_number'),
                client_country=data.get('client_country'),
                subscription=data.get('subscription', 'starter'),
                active=True
            )

            # Link subscription plan and cycle
            from models.subscription_plan import SubscriptionPlan
            from datetime import datetime, timedelta

            plan_id = data.get('plan_id')
            if not plan_id:
                sub_name = (data.get('subscription') or 'starter').lower()
                if sub_name == 'basic':
                    sub_name = 'starter'
                plan_rec = SubscriptionPlan.query.filter_by(name=sub_name).first()
                if not plan_rec:
                    plan_rec = SubscriptionPlan.query.filter_by(name='starter').first()
                if plan_rec:
                    plan_id = plan_rec.id

            billing_cycle = data.get('billing_cycle', 'monthly')
            renewal_date_val = data.get('renewal_date')
            if renewal_date_val:
                try:
                    if isinstance(renewal_date_val, str):
                        renewal_date = datetime.fromisoformat(renewal_date_val.split('T')[0])
                    else:
                        renewal_date = renewal_date_val
                except Exception:
                    renewal_date = datetime.utcnow() + timedelta(days=365 if billing_cycle == 'yearly' else 30)
            else:
                renewal_date = datetime.utcnow() + timedelta(days=365 if billing_cycle == 'yearly' else 30)

            client.plan_id = plan_id
            client.billing_cycle = billing_cycle
            client.renewal_date = renewal_date
            client.subscription_status = 'active'

            self.client_repo.flush()
            
            # 3. أتمتة NetBird عبر الـ API (إنشاء الـ Group)
            group_payload = {"name": f"{username}"}
            group_res = requests.post(f"{FASTAPI_BASE_URL}/groups", json=group_payload, headers=headers)
            
            if group_res.status_code not in [200, 201]:
                raise Exception(f"Failed to create NetBird group: {group_res.text}")
            
            group_data = group_res.json()
            group_id = group_data.get("id")

            if not group_id:
                raise Exception("NetBird group creation returned no id")

            client.netbird_group_id = group_id
            created_group_id = group_id

            # 4. إنشاء Setup Key (تصحيح قاموس الحقول)
            auto_groups_list = [ALL_PEERS_GROUP_ID, group_id]

            setup_key_payload = {
                "name": f"{username}",
                "type": "reusable",
                "auto_groups": auto_groups_list,
                "allow_extra_dns_labels": False,
                "expires_in": 0,  # Never expires
                "ephemeral": False,
                "usage_limit": 0
            }

            sk_res = requests.post(f"{FASTAPI_BASE_URL}/setup-keys", json=setup_key_payload, headers=headers)
            if sk_res.status_code not in [200, 201]:
                raise Exception(f"Failed to create NetBird setup-key: {sk_res.text}")
            
            setup_key_data = sk_res.json()
            netbird_plain_key = setup_key_data.get("key")
            created_setup_key_id = setup_key_data.get("id")

            if netbird_plain_key:
                self.token_repo.create(
                    token_value=netbird_plain_key, 
                    client_id=client.user_id, 
                    is_active=True
                )

            # 5. إنشاء الـ Policies (3 ACLs منفصلة، بادئة {username}-)
            policy_defs = [
                {
                    "suffix": "allow_mesh",
                    "description": "Allow peers to reach each other",
                    "destinations": [group_id],
                },
                {
                    "suffix": "allow_controllers",
                    "description": "Allow peers to reach the controllers",
                    "destinations": [CONTROLLERS_GROUP_ID],
                },
                {
                    "suffix": "allow_pkgs_servers",
                    "description": "Allow peers to fetch updates from package servers",
                    "destinations": [PKGS_SERVERS_GROUP_ID],
                },
            ]

            for pdef in policy_defs:
                pname = f"{username}-{pdef['suffix']}"
                policy_payload = {
                    "name": pname,
                    "description": pdef["description"],
                    "enabled": True,
                    "rules": [
                        {
                            "name": pname,
                            "description": pdef["description"],
                            "action": "accept",
                            "enabled": True,
                            "bidirectional": True,
                            "protocol": "all",
                            "sources": [group_id],
                            "destinations": pdef["destinations"],
                        }
                    ]
                }
                policy_res = requests.post(f"{FASTAPI_BASE_URL}/policies", json=policy_payload, headers=headers)

                if policy_res.status_code not in [200, 201]:
                    raise Exception(f"Failed to create NetBird policy {pname}: {policy_res.text}")

                pid = policy_res.json().get("id")
                if pid:
                    created_policy_ids.append(pid)

            self.client_repo.commit()
            return True, {'id': client.user_id, 'token': netbird_plain_key, 'netbird_group_id': client.netbird_group_id}

        except Exception as e:
            self.client_repo.rollback()
            self._rollback_netbird(
                FASTAPI_BASE_URL, headers,
                policy_ids=created_policy_ids,
                setup_key_id=created_setup_key_id,
                group_id=created_group_id,
            )
            return False, str(e)

    def _rollback_netbird(self, base_url, headers, *, policy_ids=None, setup_key_id=None, group_id=None):
        """تنظيف ما تم إنشاؤه في NetBird عند فشل create_customer."""
        for pid in (policy_ids or []):
            try:
                requests.delete(f"{base_url}/policies/{pid}", headers=headers, timeout=5)
            except Exception:
                pass
        if setup_key_id:
            try:
                requests.delete(f"{base_url}/setup-keys/{setup_key_id}", headers=headers, timeout=5)
            except Exception:
                pass
        if group_id:
            try:
                requests.delete(f"{base_url}/groups/{group_id}", headers=headers, timeout=5)
            except Exception:
                pass

    def generate_token(self, customer_id):
        token_value = secrets.token_urlsafe(32)
        try:
            self.token_repo.create(token_value=token_value, client_id=customer_id, is_active=True)
            self.client_repo.commit()
            return True, token_value
        except Exception as e:
            self.client_repo.rollback()
            return False, str(e)

    def delete_customer(self, customer_id):
        client = self.client_repo.get_by_id(customer_id)
        if not client:
            return False, "Customer not found"
        try:
            self.client_repo.delete(client)
            return True, "Customer deleted"
        except Exception as e:
            return False, str(e)

    def toggle_token(self, customer_id, token_value):
        t = self.token_repo.get_by_token_and_client(token_value, customer_id)
        if not t:
            return False, "Token not found"
        try:
            t.is_active = not t.is_active
            self.client_repo.commit()
            return True, int(t.is_active)
        except Exception as e:
            self.client_repo.rollback()
            return False, str(e)

    # ========== Portal User Operations ==========
    def authenticate_client_user(self, username, password):
        username = username.strip() if username else ""
        password = password.strip() if password else ""

        client = self.client_repo.get_by_username(username)
        if not client:
            return False, "Invalid username or password"

        if not client.active:
            return False, "Account is disabled"

        if not check_password_hash(client.password_hashed, password):
            return False, "Invalid username or password"

        self.client_repo.update_last_login(client.user_id)

        return True, {
            'id': client.user_id,
            'username': client.username,
            'customer_id': client.user_id,
            'customer_name': client.client_name
        }

# أضف هذه الدالة داخل كلاس CustomerService
    def get_portal_users(self, customer_id):
        """
        جلب بيانات مستخدمي البوابة للعميل المحدد.
        في السكيما الجديدة، بيانات العميل نفسه مخزنة كـ Client/User.
        """
        client = self.client_repo.get_by_id(customer_id)
        if not client:
            return []

        return [{
            'id': client.user_id,
            'username': client.username,
            'client_name': client.client_name,
            'client_email': client.client_email,
            'active': client.active,
            'created_at': client.created_at.strftime('%Y-%m-%d %H:%M:%S') if client.created_at else None,
            'last_login': client.last_login.strftime('%Y-%m-%d %H:%M:%S') if client.last_login else None
        }]

    def delete_customer(self, customer_id):
        """
        حذف العميل من قاعدة البيانات ومن NetBird (Policy, Setup Key, Group)
        """
        FASTAPI_BASE_URL = "https://api.networkat.cloud/api/v2/netbird"
        
        # 1. إضافة Bearer Token لجميع الطلبات
        token = "57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874"
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        client = self.client_repo.get_by_id(customer_id)
        if not client:
            return False, "Customer not found"

        username = client.username
        group_id = getattr(client, 'netbird_group_id', None)

        try:
            # 1. مسح Policies المتعلقة بالعميل
            try:
                policies_res = requests.get(f"{FASTAPI_BASE_URL}/policies", headers=headers, timeout=5)
                if policies_res.status_code == 200:
                    for policy in policies_res.json():
                        pname = policy.get("name", "")
                        if pname == username or pname.startswith(f"{username}-"):
                            requests.delete(f"{FASTAPI_BASE_URL}/policies/{policy.get('id')}", headers=headers, timeout=5)
            except Exception as e:
                print(f"Warning: Failed to delete NetBird policy for {username}: {str(e)}")

            # 2. مسح Setup Keys المتعلقة بالعميل
            try:
                keys_res = requests.get(f"{FASTAPI_BASE_URL}/setup-keys", headers=headers, timeout=5)
                if keys_res.status_code == 200:
                    for key in keys_res.json():
                        if key.get("name") == username:
                            requests.delete(f"{FASTAPI_BASE_URL}/setup-keys/{key.get('id')}", headers=headers, timeout=5)
            except Exception as e:
                print(f"Warning: Failed to delete NetBird setup key for {username}: {str(e)}")

            # 3. مسح Group الخاص بالعميل
            if group_id:
                try:
                    requests.delete(f"{FASTAPI_BASE_URL}/groups/{group_id}", headers=headers, timeout=5)
                except Exception as e:
                    print(f"Warning: Failed to delete NetBird group {group_id}: {str(e)}")
            else:
                try:
                    groups_res = requests.get(f"{FASTAPI_BASE_URL}/groups", headers=headers, timeout=5)
                    if groups_res.status_code == 200:
                        for g in groups_res.json():
                            if g.get("name") == username:
                                requests.delete(f"{FASTAPI_BASE_URL}/groups/{g.get('id')}", headers=headers, timeout=5)
                except Exception as e:
                    print(f"Warning: Failed to delete NetBird group for {username}: {str(e)}")

            # 4. مسح العميل من قاعدة البيانات المحلية
            self.client_repo.delete(client)
            self.client_repo.commit()

            return True, "Customer deleted successfully"

        except Exception as e:
            self.client_repo.rollback()
            return False, str(e)
