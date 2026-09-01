# /opt/networkat_sdwan/core/web_app/models/group_peer.py
from config.database import db

class GroupPeer(db.Model):
    __tablename__ = "group_peers"

    group_id = db.Column(db.String(100), primary_key=True)
    peer_id = db.Column(db.String(100), primary_key=True)
    account_id = db.Column(db.Text, nullable=True)
    adguard_password = db.Column(db.String(255), nullable=False, default="default_password")
