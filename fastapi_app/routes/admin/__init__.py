# /opt/networkat_sdwan/core/web_app/fastapi_app/routes/admin/__init__.py
from fastapi_app.routes.admin import peers as admin_peers
from fastapi_app.routes.admin import plans as admin_plans
from fastapi_app.routes.admin import customers as admin_customers
from fastapi_app.routes.admin import staff as admin_staff

__all__ = [
    "admin_peers",
    "admin_plans",
    "admin_customers",
    "admin_staff",
]
