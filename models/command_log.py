# /opt/networkat_sdwan/core/web_app/models/command_log.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from models.base import BaseModel  # <--- تأكد إنها BaseModel زي بقية الموديلز عندك
class CommandLog(BaseModel):
    __tablename__ = "command_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    peer_id = Column(String(255), nullable=False, index=True)
    command_type = Column(String(100), nullable=False)
    parameters = Column(JSONB, nullable=True)
    status = Column(String(50), nullable=False, default="pending")  # success | error | rejected
    reject_reason = Column(String(255), nullable=True)
    output = Column(JSONB, nullable=True)
    requested_by = Column(String(255), nullable=True)
    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    executed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "peer_id": self.peer_id,
            "command_type": self.command_type,
            "parameters": self.parameters,
            "status": self.status,
            "reject_reason": self.reject_reason,
            "output": self.output,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        }