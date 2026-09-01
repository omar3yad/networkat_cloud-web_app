# Controller Module (Phase 2)

Lives inside the existing `fastapi_app/` (per your setup — no local peers
table, ownership is derived from NetBird groups via `clients.netbird_group_id`).

## Files

```
fastapi_app/
├── schemas/controller/commands.py     Pydantic request/response models
├── services/controller/command_service.py   Business logic
└── routes/controller/commands.py      API endpoints
```

Add the router in `fastapi_app/main.py` — see `WIRING.md`.

## How ownership is resolved (per your setup)

- No local `peers` table. A peer's tenant is derived purely from NetBird
  groups.
- `clients.netbird_group_id` (already in your schema) is compared against
  the `id` of every group in the NetBird peer response's `groups` array.
- A request is only allowed through if the peer belongs to the requesting
  client's NetBird group.

## Auth model

**This module does not authenticate the caller.** It trusts `client_id` in
the URL path as-is. The Flask dashboard backend (`client/routes.py`) is
responsible for:

1. Validating the session (`session['client_logged_in']`).
2. Reading `session['client_user_id']` (maps to `clients.user_id`).
3. Calling this API internally with that id, e.g.:

```python
# in client/routes.py, some new command-sending view
resp = requests.post(
    f"http://localhost:<fastapi_port>/api/v1/clients/{session['client_user_id']}/peers/{peer_id}/commands",
    json={"command_type": "system_info", "parameters": {}, "requested_by": session['client_username']},
    timeout=35,
)
```

**Do not expose this router's port/path on the public internet as-is** —
it has no independent auth. If FastAPI and Flask are reachable on the same
public interface, put the controller routes behind a reverse-proxy rule
that only allows internal traffic, or add a shared-secret header check
between the two processes.

## Endpoints

| Method | Path | Description |
|--------|------|--------------|
| POST | `/api/v1/clients/{client_id}/peers/{peer_id}/commands` | Send a command, get the result |
| GET | `/api/v1/clients/{client_id}/peers/{peer_id}/status` | Connectivity + agent health for one peer |
| GET | `/api/v1/clients/{client_id}/peers` | List all peers owned by this client |

`POST .../commands` always returns HTTP 200. Check the `status` field:
- `"success"` / `"error"` — the agent ran the command; `error` explains an
  execution failure.
- `"rejected"` — never reached the agent. Check `reject_reason`:
  `client_not_found`, `peer_not_found`, `unauthorized`, `peer_offline`,
  `peer_no_ip`, `agent_timeout`, `agent_unreachable`.

`GET .../status` and `GET .../peers` return proper HTTP error codes
(403/404/502) since they're read-only lookups, not logged commands.

## DB access

Raw SQL via the existing `get_db` session (see `command_service.py`
docstring for why — avoids mixing Flask-SQLAlchemy's `db.Model` with
whatever declarative base `fastapi_app/database.py` uses). Two tables
touched: `clients` (read-only, `netbird_group_id` lookup) and
`command_logs` (insert one row per attempt, including rejections before
the agent is ever called).

## Known gaps / next steps

- **Concurrency (spec Open Decision #4):** the agent already denies
  concurrent commands per-peer (in-process flag). This Controller does
  not add its own additional locking — if you need to prevent two
  Dashboard tabs from racing to the same peer, add a check here too.
- **No caching of NetBird peer list/groups** — every request hits the
  NetBird API directly (same pattern as `netbird/peers.py` already does).
  If this becomes a bottleneck, add a short-TTL cache.
- Not yet tested against your real Postgres/clients table — the raw SQL
  column names (`user_id`, `netbird_group_id`) match what you shared, but
  run it against a staging DB before production traffic.
