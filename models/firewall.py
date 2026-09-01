from config.database import db
from models.base import BaseModel
from sqlalchemy.dialects.postgresql import UUID  # لاستخدام نوع UUID الخاص بـ PostgreSQL


class FirewallRule(BaseModel):
    __tablename__ = "firewall_rules"

    id = db.Column(db.Integer, primary_key=True)

    # تم تغيير نوع client_id إلى UUID ليتطابق مع clients.user_id
    client_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("clients.user_id", ondelete="CASCADE"),
        nullable=False
    )

    edge_id = db.Column(
        db.Integer,
        db.ForeignKey("edges.id")
    )

    rule_name = db.Column(db.Text)

    direction = db.Column(
        db.String(30),
        default="outbound"
    )

    src_ip = db.Column(db.Text)
    dst_ip = db.Column(db.Text)
    dst_port = db.Column(db.Text)

    protocol = db.Column(
        db.String(20),
        default="tcp"
    )

    action = db.Column(
        db.String(20),
        default="DROP"
    )

    enabled = db.Column(
        db.Boolean,
        default=True
    )

    # --- Relationships ---
    client = db.relationship(
        "Client",
        back_populates="firewall_rules"
    )

    edge = db.relationship(
        "Edge",
        back_populates="firewall_rules"
    )