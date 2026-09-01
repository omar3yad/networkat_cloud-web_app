from datetime import datetime
from config.database import db
from models.base import BaseModel
from sqlalchemy.dialects.postgresql import UUID


class Policy(BaseModel):
    __tablename__ = "policies"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("clients.user_id", ondelete="CASCADE"),
        nullable=False
    )

    name = db.Column(
        db.String(255),
        nullable=False
    )

    match_type = db.Column(db.String(50))
    match_value = db.Column(db.String(255))

    action = db.Column(
        db.String(50),
        nullable=False
    )

    priority = db.Column(
        db.Integer,
        default=5
    )

    enabled = db.Column(
        db.Boolean,
        default=True
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    client = db.relationship(
        "Client",
        back_populates="policies"
    )