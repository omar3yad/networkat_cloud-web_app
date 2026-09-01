# /opt/networkat_sdwan/core/web_app/models/base.py
from datetime import datetime
from config.database import db

class BaseModel(db.Model):
    __abstract__ = True
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )