# /opt/networkat_sdwan/core/web_app/models/system_setting.py
"""
Global key-value configuration store for admin-controlled system settings.
Each setting has a key, a typed value (string in DB), metadata for the UI,
and an optional description. Settings are loaded once and cached in-process.
"""
from datetime import datetime
from config.database import db


class SystemSetting(db.Model):
    __tablename__ = "system_settings"

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=False)
    value_type = db.Column(
        db.String(20),
        nullable=False,
        default="string"
        # 'string' | 'integer' | 'boolean' | 'float'
    )
    label = db.Column(db.String(200), nullable=False, default="")
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(100), nullable=False, default="General")
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    updated_by = db.Column(db.String(100), nullable=True)

    def typed_value(self):
        """Return value cast to the declared Python type."""
        if self.value_type == "integer":
            return int(self.value)
        if self.value_type == "float":
            return float(self.value)
        if self.value_type == "boolean":
            return self.value.lower() in ("true", "1", "yes")
        return self.value

    def to_dict(self):
        return {
            "key": self.key,
            "value": self.value,
            "value_type": self.value_type,
            "label": self.label,
            "description": self.description,
            "category": self.category,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": self.updated_by,
        }

    def __repr__(self):
        return f"<SystemSetting {self.key}={self.value}>"
