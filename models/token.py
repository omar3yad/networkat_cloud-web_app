from config.database import db
from models.base import BaseModel
from sqlalchemy.dialects.postgresql import UUID


class Token(BaseModel):
    __tablename__ = "tokens"

    token = db.Column(
        db.String(255),
        primary_key=True
    )

    client_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("clients.user_id", ondelete="CASCADE"),
        nullable=False
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    client = db.relationship(
        "Client",
        back_populates="tokens"
    )