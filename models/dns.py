from config.database import db
from models.base import BaseModel
from sqlalchemy.dialects.postgresql import UUID

class DNSRule(BaseModel):
    __tablename__ = "dns_rules"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("clients.user_id", ondelete="CASCADE"),
        nullable=False
    )

    edge_id = db.Column(
        db.Integer,
        db.ForeignKey("edges.id")
    )

    domain = db.Column(
        db.Text,
        nullable=False
    )

    action = db.Column(
        db.String(20),
        default="block"
    )

    enabled = db.Column(
        db.Boolean,
        default=True
    )

    src_ip = db.Column(
        db.Text,
        default=""
    )

    client = db.relationship(
        "Client",
        back_populates="dns_rules"
    )

    edge = db.relationship(
        "Edge",
        back_populates="dns_rules"
    )