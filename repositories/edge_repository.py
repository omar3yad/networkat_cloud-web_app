# /opt/networkat_sdwan/core/web_app/repositories/edge_repository.py
"""
EdgeRepository: Maintained as a compatibility interface.
All peer and edge data is now fetched live from NetBird API.
"""

class EdgeRepository:

    @staticmethod
    def count():
        return 0

    @staticmethod
    def count_online(online_window=300):
        return 0

    @staticmethod
    def get_recent_edges(limit=10):
        return []

    @staticmethod
    def get_by_client_id(client_id):
        return []

    @staticmethod
    def get_by_customer_id(customer_id):
        return []

    @staticmethod
    def count_by_client(client_id):
        return 0

    @staticmethod
    def count_by_customer(customer_id):
        return 0

    @staticmethod
    def count_online_by_client(client_id, online_window=300):
        return 0

    @staticmethod
    def count_online_by_customer(customer_id, online_window=300):
        return 0

    @staticmethod
    def get_filtered_edges(client_id=None, status=None, online_window=300, limit=500):
        return []

    @staticmethod
    def get_by_name_and_client(edge_name, client_id):
        return None

    @staticmethod
    def get_by_name_and_customer(edge_name, customer_id):
        return None

    @staticmethod
    def get_by_name(edge_name, db=None):
        return None

    @staticmethod
    def set_private_only(edge_id, client_id, enabled):
        return False

    @staticmethod
    def set_apply_requested(edge_id, client_id, enabled):
        return False

    @staticmethod
    def set_apply_requested_by_client(client_id, enabled):
        return

    @staticmethod
    def set_apply_requested_by_customer(customer_id, enabled):
        return

    @staticmethod
    def update_lan_subnet(edge_name, client_id, lan_subnet):
        return False

    @staticmethod
    def get_lan_routes_for_others(client_id, edge_name):
        return []