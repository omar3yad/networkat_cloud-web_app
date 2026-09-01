from repositories.edge_repository import EdgeRepository
from repositories.customer_repository import CustomerRepository
import requests
import time
from threading import Lock

# Global cache variables for NetBird live peers
_NETBIRD_PEERS_CACHE = {}  # { customer_id: (peers_list, timestamp) }
_NETBIRD_CACHE_LOCK = Lock()
_NETBIRD_CACHE_TTL = 15    # cache TTL in seconds


class EdgeService:

    def __init__(self):
        self.edge_repo = EdgeRepository()
        self.customer_repo = CustomerRepository()

    def get_edges_page_data(self, customer_id, status, online_window=300):
        # Fetch customer dropdown list ordered by id desc
        customers_list = self.customer_repo.get_all_desc()

        # Cast customer_id if present
        filter_customer_id = None
        if customer_id:
            try:
                filter_customer_id = int(customer_id)
            except ValueError:
                pass

        edges_list = self.edge_repo.get_filtered_edges(
            customer_id=filter_customer_id,
            status=status,
            online_window=online_window,
            limit=500
        )

        return {
            'edges': edges_list,
            'customers': customers_list,
            'selected_customer': customer_id,
            'selected_status': status,
            'online_window': online_window
        }

    def get_client_dashboard_data(self, customer_id, customer_name, online_window=300):
        customer = self.customer_repo.get_by_id(customer_id)
        if not customer:
            return None

        db_edges = self.edge_repo.get_by_customer_id(customer_id)
        edges = []
        for row in db_edges:
            edge = {
                'id': row.id,
                'edge_name': row.edge_name,
                'assigned_ip': row.assigned_ip,
                'public_ip': row.public_ip,
                'location': row.location,
                'wg_handshake_sec': row.wg_handshake_sec,
                'last_seen': row.last_seen.strftime('%Y-%m-%d %H:%M:%S') if row.last_seen else None,
                'status': row.status,
                'private_only': row.private_only
            }
            # Calculate status color
            if row.wg_handshake_sec is not None and row.wg_handshake_sec >= 0:
                if row.wg_handshake_sec < online_window:
                    edge['status_display'] = 'online'
                    edge['status_color'] = 'success'
                else:
                    edge['status_display'] = 'stale'
                    edge['status_color'] = 'warning'
            else:
                edge['status_display'] = 'offline'
                edge['status_color'] = 'secondary'
            edges.append(edge)

        total_edges = len(edges)
        online_edges = sum(1 for e in edges if e['status_display'] == 'online')

        # ==================== جلب بيانات NetBird Live Peers ====================
        netbird_peers = []
        
        if hasattr(customer, 'netbird_group_id') and customer.netbird_group_id:
            now = time.time()
            # 1. التحقق من الكاش أولاً لتفادي الطلبات المتكررة
            with _NETBIRD_CACHE_LOCK:
                if customer_id in _NETBIRD_PEERS_CACHE:
                    cached_data, timestamp = _NETBIRD_PEERS_CACHE[customer_id]
                    if now - timestamp < _NETBIRD_CACHE_TTL:
                        netbird_peers = cached_data

            if not netbird_peers:
                FASTAPI_BASE_URL = "https://api.networkat.cloud/api/v2/netbird"
                token = "57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874"
                
                headers = {
                    "accept": "application/json",
                    "Authorization": f"Bearer {token}"
                }
                try:
                    # 1. طلب بيانات الجروب لجلب قائمة الـ Peers المربوطة به
                    group_res = requests.get(f"{FASTAPI_BASE_URL}/groups/{customer.netbird_group_id}", headers=headers, timeout=5)
                    
                    if group_res.status_code == 200:
                        group_data = group_res.json()
                        raw_peers = group_data.get("peers", [])

                        # إذا كانت الاستجابة قائمة أجهزة تفصيلية تم مريرها مباشرة
                        if raw_peers and isinstance(raw_peers[0], dict) and "name" in raw_peers[0]:
                            netbird_peers = raw_peers
                        elif raw_peers:
                            # إذا كان NetBird يعيد قائمة من IDs أو أجهزة مختزرة، نجلب التفاصيل الكاملة للـ Peers
                            all_peers_res = requests.get(f"{FASTAPI_BASE_URL}/peers", headers=headers, timeout=5)
                            if all_peers_res.status_code == 200:
                                all_peers = all_peers_res.json()
                                # استخلاص الـ IDs الخاصة بالمجموعة
                                peer_ids = [p.get("id") if isinstance(p, dict) else p for p in raw_peers]
                                netbird_peers = [p for p in all_peers if p.get("id") in peer_ids]

                        # 2. تحديث الكاش بالبيانات الجديدة
                        with _NETBIRD_CACHE_LOCK:
                            _NETBIRD_PEERS_CACHE[customer_id] = (netbird_peers, now)

                except Exception as e:
                    print(f"Error fetching NetBird live peers for customer {customer_id}: {str(e)}")
                    # في حالة الخطأ أو الـ Timeout، نحاول استخدام آخر نسخة كاش مخزنة حتى لو انتهت صلاحيتها
                    with _NETBIRD_CACHE_LOCK:
                        if customer_id in _NETBIRD_PEERS_CACHE:
                            netbird_peers = _NETBIRD_PEERS_CACHE[customer_id][0]
        # =======================================================================

        return {
            'customer_name': customer_name,
            'customer': {
                'created_at': customer.created_at.strftime('%Y-%m-%d %H:%M:%S') if customer.created_at else None,
            },
            'edges': edges,
            'netbird_peers': netbird_peers,
            'total_edges': total_edges,
            'online_edges': online_edges,
            'offline_edges': total_edges - online_edges,
            'online_window': online_window
        }
    def get_client_edge_details(self, edge_name, customer_id, online_window=300):
        edge = self.edge_repo.get_by_name_and_customer(edge_name, customer_id)
        if not edge:
            return None

        edge_data = {
            'id': edge.id,
            'edge_name': edge.edge_name,
            'assigned_ip': edge.assigned_ip,
            'public_ip': edge.public_ip,
            'location': edge.location,
            'wg_handshake_sec': edge.wg_handshake_sec,
            'last_seen': edge.last_seen.strftime('%Y-%m-%d %H:%M:%S') if edge.last_seen else None,
            'status': edge.status,
            'private_only': edge.private_only,
            'pubkey': edge.pubkey,
            'uptime': edge.uptime,
            'apply_requested': edge.apply_requested,
            'lan_subnet': edge.lan_subnet,
            'customer_name': edge.customer.name if edge.customer else None,
        }

        # Calculate status
        if edge.wg_handshake_sec is not None and edge.wg_handshake_sec >= 0:
            if edge.wg_handshake_sec < online_window:
                edge_data['status_display'] = 'online'
                edge_data['status_color'] = 'success'
            else:
                edge_data['status_display'] = 'stale'
                edge_data['status_color'] = 'warning'
        else:
            edge_data['status_display'] = 'offline'
            edge_data['status_color'] = 'secondary'

        return edge_data

    def get_client_api_edges(self, customer_id, customer_name, online_window=300):
        db_edges = self.edge_repo.get_by_customer_id(customer_id)
        edges = []
        for row in db_edges:
            edge = {
                'id': row.id,
                'edge_name': row.edge_name,
                'assigned_ip': row.assigned_ip,
                'public_ip': row.public_ip,
                'location': row.location,
                'wg_handshake_sec': row.wg_handshake_sec,
                'last_seen': row.last_seen.strftime('%Y-%m-%d %H:%M:%S') if row.last_seen else None,
                'status': row.status,
                'private_only': row.private_only
            }
            if row.wg_handshake_sec is not None and row.wg_handshake_sec >= 0:
                edge['online'] = row.wg_handshake_sec < online_window
            else:
                edge['online'] = False
            edges.append(edge)

        return {
            'customer': customer_name,
            'edges': edges,
            'total': len(edges),
            'online': sum(1 for e in edges if e['online'])
        }

    def get_private_only(self, edge_id, customer_id):
        edge = self.edge_repo.get_by_name_and_customer(Edge.query.get(edge_id).edge_name if Edge.query.get(edge_id) else "", customer_id)
        # Or simple check:
        from models.edge import Edge
        edge = Edge.query.filter_by(id=edge_id, customer_id=customer_id).first()
        if not edge:
            return None
        return bool(edge.private_only)

    def set_private_only(self, edge_id, customer_id, enabled):
        return self.edge_repo.set_private_only(edge_id, customer_id, enabled)

    def poll_private_only(self, token_value, edge_name):
        from repositories.token_repository import TokenRepository
        tok = TokenRepository.get_active_by_token(token_value)
        if not tok:
            return False

        edge = self.edge_repo.get_by_name_and_customer(edge_name, tok.customer_id)
        if not edge:
            return False

        return bool(edge.private_only)

    def register_lan(self, token_value, edge_name, lan_subnet):
        from repositories.token_repository import TokenRepository
        tok = TokenRepository.get_active_by_token(token_value)
        if not tok:
            return False, "invalid token"

        success = self.edge_repo.update_lan_subnet(edge_name, tok.customer_id, lan_subnet)
        if success:
            return True, None
        return False, "edge not found"

    def get_lan_routes(self, token_value, edge_name):
        from repositories.token_repository import TokenRepository
        tok = TokenRepository.get_active_by_token(token_value)
        if not tok:
            return None, "invalid token"

        db_routes = self.edge_repo.get_lan_routes_for_others(tok.customer_id, edge_name)
        routes = [
            {
                'edge_name': r.edge_name,
                'assigned_ip': r.assigned_ip,
                'lan_subnet': r.lan_subnet
            }
            for r in db_routes
        ]
        return routes, None
 
    def update_peer_name(self, peer_id, new_name):
        FASTAPI_BASE_URL = "https://api.networkat.cloud/api/v2/netbird"
        
        # 1. إضافة الـ Bearer Token
        token = "57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874"
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        try:
            # 2. جلب بيانات الـ Peer الحالية لتجنب إرسال قيم تعارض إعدادات الـ SSO أو النظام
            get_res = requests.get(f"{FASTAPI_BASE_URL}/peers/{peer_id}", headers=headers, timeout=5)
            
            if get_res.status_code == 200:
                current_peer = get_res.json()
                # نأخذ الـ Payload الحالي ونعدل فقط الـ name والـ ssh_enabled
                payload = {
                    "name": new_name,
                    "ssh_enabled": current_peer.get("ssh_enabled", True),
                    "login_expiration_enabled": current_peer.get("login_expiration_enabled", False),
                    "inactivity_expiration_enabled": current_peer.get("inactivity_expiration_enabled", False),
                    "approval_required": current_peer.get("approval_required", False)
                }
            else:
                # Payload افتراضي في حال تعذر جلب الـ Peer
                payload = {
                    "name": new_name,
                    "ssh_enabled": True,
                    "login_expiration_enabled": False,
                    "inactivity_expiration_enabled": False,
                    "approval_required": False
                }

            # 3. إرسال طلب التحديث
            response = requests.put(f"{FASTAPI_BASE_URL}/peers/{peer_id}", json=payload, headers=headers, timeout=5)
            
            if response.status_code in [200, 201, 204]:
                with _NETBIRD_CACHE_LOCK:
                    _NETBIRD_PEERS_CACHE.clear()
                return True, "Peer name updated successfully"
            else:
                try:
                    error_data = response.json()
                    msg = error_data.get("message") or error_data.get("detail") or response.text
                except ValueError:
                    msg = response.text if response.text else f"Status Code: {response.status_code}"
                
                return False, f"NetBird Error: {msg}"
                
        except Exception as e:
            return False, f"Connection error: {str(e)}"