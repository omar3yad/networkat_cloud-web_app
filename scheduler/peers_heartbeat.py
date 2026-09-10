"""
Controller -> peer heartbeat job.

Runs as its own supervisord process (`[program:heartbeat]`), NOT inside admin /
client / api. Every HEARTBEAT_INTERVAL seconds it:

  1. lists every peer from the internal NetBird API,
  2. keeps the ones that are `connected` and have a mesh IP,
  3. POSTs http://<mesh-ip>:8765/heartbeat (no body, no auth header - the
     trust boundary is the mesh, same as every other Controller->agent call),
  4. logs one summary line.

Why this exists
---------------
The peer's failsafe / dead-man-switch (failsafe_engine.py on the peer) trips to
"basic internet router" mode when Controller contact is lost past
`failsafe_timeout_seconds`. "Contact" is the mtime of
/run/networkat-agent/last-contact on the peer, refreshed by POST /heartbeat and
by any successful agent command. Without this job the only thing refreshing it
is incidental /status + reachability traffic from the client dashboard - which
only happens while a customer has the dashboard open. This job makes the
liveness signal reliable and independent of dashboard activity.

The peer side is the source of truth for the timeout and the state machine;
this job is a dumb pinger. It never reads the response body beyond the status
code, keeps no state, and a peer being unreachable is normal (offline, mid
reboot) - logged at debug, never fatal. The loop must never die.
"""
import logging
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv

# The compose env_file isn't propagated into the process environment on this
# host - every app relies on python-dotenv reading /app/.env at import time
# (see config/settings.py). Do the same here.
load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Internal NetBird API - same env vars fastapi_app/services/netbird/peers.py
# reads. Kept as a direct call here rather than importing that service so this
# job has no dependency on the fastapi_app package.
NETBIRD_API_URL = os.getenv("NETBIRD_API_URL", "http://netbird-server/api")
NETBIRD_TOKEN = os.getenv("NETBIRD_TOKEN", "")
NETBIRD_LIST_TIMEOUT = float(os.getenv("HEARTBEAT_NETBIRD_TIMEOUT", "10"))

# Only peers in this NetBird group are SD-WAN peers running the agent. Every
# customer onboarding scopes its setup key to the customer group + "all-peers"
# (see peer_installer CLAUDE.md / services/customer_service.py), so "all-peers"
# is exactly the set of managed gateways. Controllers, browser clients and
# admin laptops sit in other groups and have no agent on :8765 - pinging them
# is just wasted sockets and noise in the failure count.
PEER_GROUP = os.getenv("HEARTBEAT_PEER_GROUP", "all-peers")

# Target ~60s between rounds. The peer default timeout is a week
# (installer failsafe_engine.py DEFAULT_TIMEOUT_SECONDS = 604800), so a missed
# round or two is harmless - this does not need to be tight.
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "60"))

# Per-peer POST timeout. Short: the agent handler just writes a file and
# returns. A slow peer should not hold up the round.
HEARTBEAT_TIMEOUT = float(os.getenv("HEARTBEAT_REQUEST_TIMEOUT", "5"))

# Parallel fan-out width, matching services/netbird_service.py's executor.
HEARTBEAT_WORKERS = int(os.getenv("HEARTBEAT_WORKERS", "20"))

AGENT_PORT = 8765

# Overall cap on one round's fan-out, so a batch of hung sockets can't make a
# round outlast its interval. Generous vs. HEARTBEAT_TIMEOUT * (peers/workers).
_ROUND_DEADLINE = max(HEARTBEAT_INTERVAL - 5, 15)

logging.basicConfig(
    level=os.getenv("HEARTBEAT_LOG_LEVEL", "INFO"),
    format="%(asctime)s [heartbeat] %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("heartbeat")

# Flipped by SIGTERM/SIGINT (supervisord stop, docker stop). The sleep between
# rounds waits on this so shutdown is near-instant instead of up to a full
# interval.
_stop = threading.Event()


def _handle_signal(signum, _frame):
    logger.info("signal %s received - stopping after current round", signum)
    _stop.set()


def _list_target_peers() -> list[dict]:
    """SD-WAN peers (group PEER_GROUP) that are connected and have a mesh IP.
    Anything else can't be (or doesn't need to be) pinged this round. Returns
    [] on any API error - a bad round, not a fatal one."""
    try:
        resp = requests.get(
            f"{NETBIRD_API_URL}/peers",
            headers={"Accept": "application/json", "Authorization": f"Bearer {NETBIRD_TOKEN}"},
            timeout=NETBIRD_LIST_TIMEOUT,
        )
        resp.raise_for_status()
        peers = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("NetBird peer list failed: %s", exc)
        return []

    if isinstance(peers, dict):  # NetBird returning one object instead of a list
        peers = [peers]

    def _in_group(peer: dict) -> bool:
        return any(g.get("name") == PEER_GROUP for g in peer.get("groups") or [])

    return [
        p for p in peers
        if p.get("connected") and p.get("ip") and _in_group(p)
    ]


def _ping_one(peer: dict) -> bool:
    """POST /heartbeat to a single peer. True on 2xx, False on anything else.
    Never raises."""
    ip = peer.get("ip")
    try:
        resp = requests.post(
            f"http://{ip}:{AGENT_PORT}/heartbeat", timeout=(1, HEARTBEAT_TIMEOUT)
        )
        if resp.ok:
            return True
        logger.debug(
            "peer %s (%s) heartbeat HTTP %s", peer.get("name"), ip, resp.status_code
        )
        return False
    except requests.RequestException as exc:
        logger.debug("peer %s (%s) heartbeat unreachable: %s", peer.get("name"), ip, exc)
        return False


def _run_round(pool: ThreadPoolExecutor) -> None:
    peers = _list_target_peers()
    if not peers:
        logger.info("round: 0 reachable peers")
        return

    ok = 0
    failed = 0
    futures = {pool.submit(_ping_one, p): p for p in peers}
    try:
        for fut in as_completed(futures, timeout=_ROUND_DEADLINE):
            if fut.result():
                ok += 1
            else:
                failed += 1
    except TimeoutError:
        # Some pings didn't finish inside the round deadline. Count them as
        # failed for this round's log; the futures are abandoned (their
        # sockets time out on their own via HEARTBEAT_TIMEOUT).
        pending = sum(1 for f in futures if not f.done())
        failed += pending
        logger.warning("round: %s peer(s) did not answer within %ss", pending, _ROUND_DEADLINE)

    logger.info("round: %s peers, %s ok, %s failed", len(peers), ok, failed)


def run_forever() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info(
        "starting: interval=%ss timeout=%ss workers=%s",
        HEARTBEAT_INTERVAL,
        HEARTBEAT_TIMEOUT,
        HEARTBEAT_WORKERS,
    )

    with ThreadPoolExecutor(max_workers=HEARTBEAT_WORKERS) as pool:
        while not _stop.is_set():
            started = time.monotonic()
            try:
                _run_round(pool)
            except Exception:  # noqa: BLE001 - the loop must outlive any bug
                logger.exception("round failed")

            # Sleep the remainder of the interval, interruptible by a signal.
            elapsed = time.monotonic() - started
            _stop.wait(max(HEARTBEAT_INTERVAL - elapsed, 1))

    logger.info("stopped")


if __name__ == "__main__":
    run_forever()
