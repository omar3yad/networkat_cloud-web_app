"""
/opt/networkat_sdwan/core/web_app/fastapi_app/services/controller/command_service.py
Controller service: owns the full lifecycle of a command execution request
(spec Section 7.2):
  1. Check NetBird: is the peer connected? If not -> reject peer_offline.
  2. Get the peer's NetBird IP.
  3. POST to http://{ip}:8765/execute (no auth header — see agent/README.md
     "Security model": trust boundary is the NetBird mesh + ACL).
  4. Log result to command_logs.
  5. Return result to the caller (Flask dashboard backend).
"""
import json
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
import requests

from fastapi_app.schemas.controller.commands import CommandType
from fastapi_app.services.netbird.peers import NetBirdPeerService

AGENT_PORT = 8765
AGENT_CONNECT_TIMEOUT = 1
AGENT_TIMEOUT_SECONDS = 30  # spec Open Decision #3 default
AGENT_TIMEOUT = (AGENT_CONNECT_TIMEOUT, AGENT_TIMEOUT_SECONDS)


class CommandError(Exception):
    """
    Raised for any rejection or failure — carries everything the route
    needs to build the response, and the id/timestamp of the log row
    already written for this attempt.
    """
    def __init__(self, reason: str, message: str, log_id: uuid.UUID, requested_at: datetime):
        self.reason = reason
        self.log_id = log_id
        self.requested_at = requested_at
        super().__init__(message)


# --------------------------------------------------------------------------
# DB helpers (raw SQL — see module docstring)
# --------------------------------------------------------------------------

def _log_command(
    db: Session,
    *,
    peer_id: str,
    command_type: str,
    parameters: dict[str, Any],
    status: str,
    reject_reason: Optional[str],
    output: Optional[dict[str, Any]],
    requested_by: Optional[str],
    executed_at: Optional[datetime],
) -> tuple[uuid.UUID, datetime]:
    log_id = uuid.uuid4()
    requested_at = datetime.utcnow()  # naive UTC — command_logs columns have no timezone
    db.execute(
        text(
            """
            INSERT INTO command_logs
                (id, peer_id, command_type, parameters, status, reject_reason,
                 output, requested_by, requested_at, executed_at, created_at)
            VALUES
                (:id, :peer_id, :command_type, CAST(:parameters AS JSONB), :status,
                 :reject_reason, CAST(:output AS JSONB), :requested_by,
                 :requested_at, :executed_at, :created_at)
            """
        ),
        {
            "id": str(log_id),
            "peer_id": peer_id,
            "command_type": command_type,
            "parameters": json.dumps(parameters),
            "status": status,
            "reject_reason": reject_reason,
            "output": json.dumps(output) if output is not None else None,
            "requested_by": requested_by or "system",
            "requested_at": requested_at,
            "created_at": requested_at,
            "executed_at": executed_at,
        },
    )
    db.commit()
    return log_id, requested_at


# --------------------------------------------------------------------------
# NetBird helpers
# --------------------------------------------------------------------------

def _fetch_peer_or_none(peer_id: str) -> Optional[dict]:
    result = NetBirdPeerService.get_peer(peer_id)
    if isinstance(result, dict) and result.get("error"):
        return None
    return result


# --------------------------------------------------------------------------
# Agent call
# --------------------------------------------------------------------------

def _call_agent_sync(peer_ip: str, request_id: uuid.UUID, command_type: str, parameters: dict[str, Any]) -> dict:
    url_base = f"http://{peer_ip}:{AGENT_PORT}"
    
    if command_type == "vpn_only":
        operation = parameters.get("operation") or parameters.get("action")
        if operation in ("on", "off"):
            response = requests.post(f"{url_base}/vpn-only", json={"operation": operation}, timeout=AGENT_TIMEOUT)
        elif operation == "status":
            response = requests.get(f"{url_base}/vpn-only", timeout=AGENT_TIMEOUT)
        else:
            response = requests.get(f"{url_base}/vpn-only", timeout=AGENT_TIMEOUT)
            
    elif command_type == "system_info":
        response = requests.get(f"{url_base}/status", timeout=AGENT_TIMEOUT)
        
    elif command_type == "wan_links":
        response = requests.get(f"{url_base}/wan-links/status", timeout=(AGENT_CONNECT_TIMEOUT, 5))
        
    elif command_type == "firewall_rules":
        action = parameters.get("action", "list")
        if action == "add":
            rule_data = parameters.get("rule", {})
            response = requests.post(f"{url_base}/firewall/rules", json=rule_data, timeout=AGENT_TIMEOUT)
        elif action == "remove":
            rule_id = parameters.get("rule_id")
            if not rule_id:
                raise ValueError("rule_id is required to remove a firewall rule")
            response = requests.delete(f"{url_base}/firewall/rules/{rule_id}", timeout=AGENT_TIMEOUT)
        else:
            response = requests.get(f"{url_base}/firewall/rules", timeout=AGENT_TIMEOUT)

    elif command_type == "service_control":
        name = parameters.get("name")
        services = parameters.get("services")
        source = parameters.get("source", "manual")
        if services:
            response = requests.put(
                f"{url_base}/services", json={"services": services, "source": source}, timeout=AGENT_TIMEOUT
            )
        elif name:
            state = parameters.get("state")
            if state not in ("enabled", "disabled"):
                raise ValueError("state must be 'enabled' or 'disabled'")
            response = requests.put(
                f"{url_base}/services/{name}", json={"state": state, "source": source}, timeout=AGENT_TIMEOUT
            )
        else:
            response = requests.get(f"{url_base}/services", timeout=AGENT_TIMEOUT)

    else:
        raise ValueError(f"Command type '{command_type}' is not supported by the new agent.")
        
    response.raise_for_status()
    return response.json()


def _get_agent_health_sync(peer_ip: str) -> Optional[dict]:
    try:
        response = requests.get(f"http://{peer_ip}:{AGENT_PORT}/health", timeout=(AGENT_CONNECT_TIMEOUT, 5))
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------

async def execute_command(
    db: Session,
    *,
    peer_id: str,
    command_type: CommandType,
    parameters: dict[str, Any],
    requested_by: Optional[str],
) -> dict[str, Any]:
    def reject(reason: str, message: str) -> "CommandError":
        log_id, requested_at = _log_command(
            db,
            peer_id=peer_id,
            command_type=command_type.value,
            parameters=parameters,
            status="rejected",
            reject_reason=reason,
            output=None,
            requested_by=requested_by,
            executed_at=None,
        )
        return CommandError(reason, message, log_id, requested_at)

    peer = await run_in_threadpool(_fetch_peer_or_none, peer_id)
    if peer is None:
        raise reject("peer_not_found", "Peer not found in NetBird")

    if not peer.get("connected"):
        raise reject("peer_offline", "Peer is not currently connected")

    peer_ip = peer.get("ip")
    if not peer_ip:
        raise reject("peer_no_ip", "Peer has no mesh IP assigned")

    request_id = uuid.uuid4()
    status = "error"
    output = None
    error = None
    executed_at = None

    try:
        agent_result = await run_in_threadpool(
            _call_agent_sync, peer_ip, request_id, command_type.value, parameters
        )
        status = "success" if agent_result.get("ok", True) else "error"
        output = agent_result
        if not agent_result.get("ok", True):
            error = agent_result.get("message", "Agent operation failed")
        executed_at = datetime.utcnow()
    except requests.Timeout:
        raise reject("agent_timeout", f"Agent did not respond within {AGENT_TIMEOUT_SECONDS}s")
    except requests.HTTPError as exc:
        try:
            err_json = exc.response.json()
            detail = err_json.get("detail", str(exc))
            if isinstance(detail, list):
                detail = ", ".join([f"{e.get('loc', '')}: {e.get('msg', '')}" for e in detail])
        except Exception:
            detail = str(exc)
        status = "error"
        output = None
        error = detail
        executed_at = datetime.utcnow()
    except requests.RequestException as exc:
        raise reject("agent_unreachable", str(exc))
    except Exception as exc:
        status = "error"
        output = None
        error = str(exc)
        executed_at = datetime.utcnow()

    log_id, requested_at = _log_command(
        db,
        peer_id=peer_id,
        command_type=command_type.value,
        parameters=parameters,
        status=status,
        reject_reason=None,
        output=output,
        requested_by=requested_by,
        executed_at=executed_at,
    )

    return {
        "id": log_id,
        "peer_id": peer_id,
        "command_type": command_type.value,
        "status": status,
        "reject_reason": None,
        "output": output,
        "error": error,
        "requested_at": requested_at,
        "executed_at": executed_at,
    }


async def get_peer_status(peer_id: str) -> dict[str, Any]:
    peer = await run_in_threadpool(_fetch_peer_or_none, peer_id)
    if peer is None:
        raise CommandError("peer_not_found", "Peer not found in NetBird", uuid.uuid4(), datetime.utcnow())

    connected = bool(peer.get("connected"))
    peer_ip = peer.get("ip")
    health = None
    if connected and peer_ip:
        health = await run_in_threadpool(_get_agent_health_sync, peer_ip)

    agent_healthy = health is not None
    return {
        "peer_id": peer_id,
        "connected": connected,
        "ip": peer_ip,
        "agent_healthy": agent_healthy,
        "agent_version": health.get("version") if health else None,
        "is_reachable": connected and agent_healthy,
    }


async def list_peers() -> list[dict[str, Any]]:
    all_peers = await run_in_threadpool(NetBirdPeerService.list_peers)
    if isinstance(all_peers, dict) and all_peers.get("error"):
        raise CommandError("netbird_unreachable", all_peers.get("detail", "NetBird API error"), uuid.uuid4(), datetime.utcnow())

    return [
        {
            "peer_id": p["id"],
            "name": p["name"],
            "connected": p["connected"],
            "ip": p.get("ip"),
        }
        for p in all_peers
    ]


async def handshake(peer_id: str) -> dict[str, Any]:
    """
    Lightweight reachability check — no ownership check.
    Returns only {peer_id, is_reachable}.
    """
    peer = await run_in_threadpool(_fetch_peer_or_none, peer_id)
    if peer is None:
        return {"peer_id": peer_id, "is_reachable": False}

    connected = bool(peer.get("connected"))
    peer_ip = peer.get("ip")
    agent_healthy = False
    if connected and peer_ip:
        health = await run_in_threadpool(_get_agent_health_sync, peer_ip)
        agent_healthy = health is not None

    return {"peer_id": peer_id, "is_reachable": connected and agent_healthy}