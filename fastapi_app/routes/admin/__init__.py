# /opt/networkat_sdwan/core/web_app/fastapi_app/routes/admin/__init__.py
from fastapi_app.routes.admin import peers as admin_peers
from fastapi_app.routes.admin import plans as admin_plans

__all__ = [
    "admin_peers",
    "admin_plans",
]
