# /opt/networkat_sdwan/core/web_app/fastapi_app/main.py

import os
from sqlalchemy.orm import Session
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi_app.routes.adguard import dns as adguard_dns
from fastapi_app.dependencies import get_db, verify_api_key
from fastapi_app.routes.controller import commands as controller_commands
from fastapi_app.routes import auth as client_auth
from fastapi_app.routes.netbird import (
    setup_keys as netbird_setup_keys,
    routes as netbird_routes,
    policies as netbird_policies,
    groups as netbird_groups,
    tokens as netbird_tokens,
    users as netbird_users,
    peers as netbird_peers
)

# التبعية الأمنية — تُطبَّق على كل router بشكل صريح (عدا الـ public endpoint)
_auth = [Depends(verify_api_key)]

app = FastAPI(
    title="Networkat SD-WAN API ",
    description="High-performance API engine powered by FastAPI",
    version="2.0.0",
    docs_url="/docs",      
    redoc_url="/redoc",
    contact={
        "name": "Ayad",
        "url": "https://github.com/omar3yad", 
    },
    license_info={
        "name": "57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874",
        "url": "https://opensource.org/licenses/MIT",
    }
)

# ── Public endpoint — no Bearer token required ────────────────────────────────
app.include_router(client_auth.router)

# ── Public static scripts — served at /scripts/<filename> ─────────────────────
# uvicorn runs with directory=/app, so relative paths resolve from /app
_SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
app.mount("/scripts", StaticFiles(directory=_SCRIPTS_DIR), name="scripts")

# ── Protected routers — require Bearer token ──────────────────────────────────
app.include_router(adguard_dns.router,          dependencies=_auth)
app.include_router(netbird_peers.router,        dependencies=_auth)
app.include_router(netbird_users.router,        dependencies=_auth)
app.include_router(netbird_tokens.router,       dependencies=_auth)
app.include_router(netbird_routes.router,       dependencies=_auth)
app.include_router(netbird_groups.router,       dependencies=_auth)
app.include_router(netbird_policies.router,     dependencies=_auth)
app.include_router(netbird_setup_keys.router,   dependencies=_auth)
app.include_router(controller_commands.router,  dependencies=_auth)