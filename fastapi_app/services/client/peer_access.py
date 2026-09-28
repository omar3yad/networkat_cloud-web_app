"""
Which peers a client may reach, and whether it may change things.

Same rules as the client Flask app (client/decorators.py):
  - a peer belongs to a client when it is in the client's NetBird group
    (`clients.netbird_group_id`), cached 60 s per client;
  - writes are allowed only while `subscription_status` is active or grace_period.
Raw SQL against the shared tables, like the rest of the FastAPI side.
"""
import time
import uuid
from threading import Lock
from typing import Optional

import requests
from sqlalchemy import text

from fastapi_app.database import SessionLocal
from fastapi_app.services.netbird.groups import NetBirdService
from fastapi_app.services.netbird.peers import NetBirdPeerService

_GROUP_TTL = 60
_WRITE_STATUSES = ("active", "grace_period")

_group_cache: dict[str, tuple[frozenset, float]] = {}
_group_lock = Lock()


def _client_row(customer_id: str) -> Optional[dict]:
    try:
        uuid.UUID(customer_id)  # clients.user_id is a uuid column; anything else would be a DB error
    except ValueError:
        return None
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT netbird_group_id, subscription_status, is_trial, subscription FROM clients WHERE user_id = :id"),
            {"id": customer_id},
        ).mappings().first()
    return dict(row) if row else None


def is_paid_client(customer_id: str) -> bool:
    """Returns True if customer has paid/active subscription (not a trial)."""
    row = _client_row(customer_id)
    if not row:
        return False
    if row.get("is_trial"):
        return False
    return row.get("subscription_status") in _WRITE_STATUSES


def _group_peer_ids(group_id: str) -> frozenset:
    group = NetBirdService.get_group_by_id(group_id)
    if not isinstance(group, dict) or group.get("error"):
        return frozenset()
    return frozenset(p["id"] for p in (group.get("peers") or []) if p.get("id"))


def customer_peer_ids(customer_id: str) -> frozenset:
    now = time.time()
    with _group_lock:
        cached = _group_cache.get(customer_id)
        if cached and now - cached[1] < _GROUP_TTL:
            return cached[0]

    row = _client_row(customer_id)
    peer_ids = _group_peer_ids(row["netbird_group_id"]) if row and row.get("netbird_group_id") else frozenset()

    with _group_lock:
        _group_cache[customer_id] = (peer_ids, now)
    return peer_ids


def can_write(customer_id: str) -> bool:
    row = _client_row(customer_id)
    return bool(row) and row.get("subscription_status") in _WRITE_STATUSES


def get_owned_peer(customer_id: str, peer_id: str) -> Optional[dict]:
    """The NetBird peer if this client owns it, else None. Carries `ip` and `connected`."""
    if peer_id not in customer_peer_ids(customer_id):
        return None
    try:
        peer = NetBirdPeerService.get_peer(peer_id)
    except requests.RequestException:
        return None
    if not isinstance(peer, dict) or peer.get("error"):
        return None
    return peer
