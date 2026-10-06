# /opt/networkat_sdwan/core/web_app/fastapi_app/schemas/admin/__init__.py
from fastapi_app.schemas.admin.peers import (
    CustomerSummarySchema,
    PeerSchema,
    PeerStatsSchema,
    AdminPeersResponse,
)

__all__ = [
    "CustomerSummarySchema",
    "PeerSchema",
    "PeerStatsSchema",
    "AdminPeersResponse",
]
