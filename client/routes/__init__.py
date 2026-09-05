from client.blueprint import client_bp
from client.routes import auth, dashboard, peer_api, firewall, aliases, web_filter

__all__ = ['client_bp']
