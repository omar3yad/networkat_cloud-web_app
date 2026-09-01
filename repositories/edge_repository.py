from extensions import db
from models.edge import Edge
from models.client import Client


class EdgeRepository:

    @staticmethod
    def count():
        return Edge.query.count()

    @staticmethod
    def count_online(online_window):
        return Edge.query.filter(
            Edge.wg_handshake_sec.isnot(None),
            Edge.wg_handshake_sec >= 0,
            Edge.wg_handshake_sec < online_window
        ).count()

    @staticmethod
    def get_recent_edges(limit=10):
        recent_edges_query = (
            db.session.query(
                Edge.edge_name,
                Edge.assigned_ip,
                Edge.public_ip,
                Edge.wg_handshake_sec,
                Edge.last_seen,
                Client.client_name.label('client_name'),
                Client.client_name.label('customer_name'),  # للتوافق مع الواجهات القائمة
                Client.user_id.label('client_id'),
                Client.user_id.label('customer_id')         # للتوافق مع الواجهات القائمة
            )
            .join(Client, Client.user_id == Edge.client_id)
            .filter(Edge.wg_handshake_sec.isnot(None), Edge.wg_handshake_sec >= 0)
            .order_by(Edge.last_seen.desc().nulls_last())
            .limit(limit)
        )
        return [dict(row._mapping) for row in recent_edges_query.all()]

    @staticmethod
    def get_by_client_id(client_id):
        return Edge.query.filter_by(client_id=client_id).order_by(Edge.last_seen.desc().nulls_last()).all()

    # Alias للتوافق
    @staticmethod
    def get_by_customer_id(customer_id):
        return EdgeRepository.get_by_client_id(customer_id)

    @staticmethod
    def count_by_client(client_id):
        return Edge.query.filter_by(client_id=client_id).count()

    # Alias للتوافق
    @staticmethod
    def count_by_customer(customer_id):
        return EdgeRepository.count_by_client(customer_id)

    @staticmethod
    def count_online_by_client(client_id, online_window):
        return Edge.query.filter(
            Edge.client_id == client_id,
            Edge.wg_handshake_sec.isnot(None),
            Edge.wg_handshake_sec >= 0,
            Edge.wg_handshake_sec < online_window
        ).count()

    # Alias للتوافق
    @staticmethod
    def count_online_by_customer(customer_id, online_window):
        return EdgeRepository.count_online_by_client(customer_id, online_window)

    @staticmethod
    def get_filtered_edges(client_id, status, online_window, limit=500):
        query = Edge.query.join(Client, Client.user_id == Edge.client_id)
        if client_id:
            query = query.filter(Edge.client_id == client_id)
        if status == 'online':
            query = query.filter(
                Edge.wg_handshake_sec.isnot(None),
                Edge.wg_handshake_sec >= 0,
                Edge.wg_handshake_sec < online_window,
            )
        elif status == 'offline':
            query = query.filter(
                (Edge.wg_handshake_sec.is_(None)) |
                (Edge.wg_handshake_sec < 0) |
                (Edge.wg_handshake_sec >= online_window)
            )
        return query.order_by(Edge.last_seen.desc().nulls_last()).limit(limit).all()

    @staticmethod
    def get_by_name_and_client(edge_name, client_id):
        return Edge.query.filter_by(edge_name=edge_name, client_id=client_id).first()

    # Alias للتوافق
    @staticmethod
    def get_by_name_and_customer(edge_name, customer_id):
        return EdgeRepository.get_by_name_and_client(edge_name, customer_id)

    @staticmethod
    def get_by_name(edge_name, db=None):
        if db:  
            return db.query(Edge).filter(Edge.edge_name == edge_name).first()
        return Edge.query.filter_by(edge_name=edge_name).first()

    @staticmethod
    def set_private_only(edge_id, client_id, enabled):
        edge = Edge.query.filter_by(id=edge_id, client_id=client_id).first()
        if edge:
            edge.private_only = enabled
            db.session.commit()
            return True
        return False

    @staticmethod
    def set_apply_requested(edge_id, client_id, enabled):
        edge = Edge.query.filter_by(id=edge_id, client_id=client_id).first()
        if edge:
            edge.apply_requested = enabled
            db.session.commit()
            return True
        return False

    @staticmethod
    def set_apply_requested_by_client(client_id, enabled):
        edges = Edge.query.filter_by(client_id=client_id).all()
        for edge in edges:
            edge.apply_requested = enabled
        db.session.commit()

    # Alias للتوافق
    @staticmethod
    def set_apply_requested_by_customer(customer_id, enabled):
        EdgeRepository.set_apply_requested_by_client(customer_id, enabled)

    @staticmethod
    def update_lan_subnet(edge_name, client_id, lan_subnet):
        edge = Edge.query.filter_by(edge_name=edge_name, client_id=client_id).first()
        if edge:
            edge.lan_subnet = lan_subnet
            db.session.commit()
            return True
        return False

    @staticmethod
    def get_lan_routes_for_others(client_id, edge_name):
        return Edge.query.filter(
            Edge.client_id == client_id,
            Edge.edge_name != edge_name,
            Edge.lan_subnet != '',
            Edge.lan_subnet.isnot(None)
        ).all()