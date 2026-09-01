from config.database import db
from models.base import BaseModel
from sqlalchemy.dialects.postgresql import UUID

class Edge(BaseModel):
    __tablename__ = "edges"

    __table_args__ = (
        db.UniqueConstraint(
            "client_id",
            "assigned_ip",
            name="uq_client_ip"
        ),
        db.UniqueConstraint(
            "client_id",
            "edge_name",
            name="uq_client_edge_name"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    # تعديل النوع إلى UUID ليطابق clients.user_id
    client_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("clients.user_id", ondelete="CASCADE"),
        nullable=False
    )

    edge_name = db.Column(
        db.String(255),
        nullable=False
    )

    pubkey = db.Column(
        db.Text,
        nullable=False,
        unique=True
    )

    assigned_ip = db.Column(
        db.String(50),
        nullable=False
    )

    last_seen = db.Column(db.DateTime)
    location = db.Column(db.Text)
    public_ip = db.Column(db.Text)
    status = db.Column(db.String(50))
    uptime = db.Column(db.Integer)
    wg_handshake_sec = db.Column(db.Integer)

    apply_requested = db.Column(
        db.Boolean,
        default=False
    )

    private_only = db.Column(
        db.Boolean,
        default=False
    )

    lan_subnet = db.Column(
        db.Text,
        default=""
    )

    client = db.relationship(
        "Client",
        back_populates="edges"
    )

    @property
    def client_name(self):
        return self.client.client_name if self.client else ""

    firewall_rules = db.relationship(
        "FirewallRule",
        back_populates="edge"
    )

    dns_rules = db.relationship(
        "DNSRule",
        back_populates="edge"
    )