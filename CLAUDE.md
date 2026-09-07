# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## This repo is one piece of a larger project

The git repo root is here (`core/web_app/`), but this directory is **not the whole project**. It lives inside an infra + app tree at `/opt/networkat_sdwan/`, alongside `core/` (Postgres, pgAdmin, Nginx, Certbot) and `netbird/` (self-hosted NetBird WireGuard mesh + dashboard). For the wider picture — how the stack is composed with Docker, the shared external networks, how `netbird/` is run as infra config — see **`/opt/networkat_sdwan/CLAUDE.md`** (one level above this repo, not tracked by it).

Everything below is specific to the application code in this directory.

## What this codebase is

A single Python codebase that runs as **four separate processes** — two Flask apps + one FastAPI app + one background job loop — sharing one Postgres database and one set of SQLAlchemy models. Supervisor runs all four inside one container.

## Running

Designed to run inside Docker via Supervisor — there is no documented local venv workflow. From `/opt/networkat_sdwan/core/`:

```bash
docker compose up -d --build   # picks up compose.yaml + compose.override.yaml automatically
```

`compose.override.yaml` bind-mounts this directory into the container and runs Gunicorn/Uvicorn with `--reload`, so edits are picked up live without rebuilding — just save.

Inside the container, `entrypoint.sh` waits for Postgres, runs `flask db upgrade` (Alembic), then execs `supervisord`, which runs `program:admin`, `program:client`, `program:api`, and `program:heartbeat` (see `supervisord.conf`). Ports: admin `5000`, client `8097`, FastAPI gateway `8098` (docs at `/docs`); `heartbeat` has no port.

`.env` is not propagated into the process environment on the deploy host — every process (including the scheduler) relies on `python-dotenv` reading `/app/.env` at import time via `config/settings.py`. Follow that pattern in any new entrypoint; don't assume `os.getenv` works without `load_dotenv()`.

The container runs as non-root `appuser:devteam` (UID 1001 / GID 1002, matching a host `devteam` group) with `umask=002` in `supervisord.conf`, so files created by migrations or logs stay group-writable on the bind-mounted volume. A new file-writing code path (new log file, generated migration, etc.) should inherit this — don't `chmod`/`chown` around it.

## Database migrations

Alembic via Flask-Migrate, run from this directory (or inside the container where `FLASK_APP=app.py` is set):

```bash
flask db migrate -m "description"   # generate a new migration in migrations/versions/
flask db upgrade                     # apply migrations (also runs automatically on container start)
flask db downgrade -1
```

Models live in `models/` and are shared by both Flask apps (via `Flask-SQLAlchemy`, `extensions.py: db`) and the FastAPI gateway (via a separate scoped `SessionLocal` in `fastapi_app/database.py`). When adding/changing a model, only the Flask-SQLAlchemy side needs a migration — the FastAPI side reads the same tables through raw SQLAlchemy Core/sessions, not its own model layer.

## Tests

```bash
pytest                          # run everything
pytest tests/test_dns.py        # single file
pytest tests/test_dns.py::test_get_adguard_password_from_db   # single test
```

Only `tests/test_dns.py` is a real pytest suite — it exercises `fastapi_app/services/adguard/adguard_service.py` with `unittest.mock.patch` and `@pytest.mark.anyio` for the async methods. `test_auth.py`, `test_edge.py`, and `test_firewall.py` are currently empty placeholder files, not passing-but-trivial suites — don't assume coverage exists there.

`tests/test_clean_arch_suite.py` is not a pytest file — it's a standalone script (`python tests/test_clean_arch_suite.py`, must run inside the container where `/app` is importable) that builds the client Flask app, renders every client template with sample context, and pokes routes, printing a pass/fail report. It uses `print`, not asserts, so `pytest` won't meaningfully report on it. It exists to police the thin-routes layering and template health.

## Route auditing

`check_routes.py` (run from this directory) greps `admin/routes.py` for every `@admin_bp.route(...)` and cross-references it against templates/JS/other route files to flag admin routes that appear unused. Useful before deleting or refactoring admin endpoints; it only covers the admin blueprint, not client or FastAPI routes.

## Reference docs in the repo

- `PROJECT_ARCHITECTURE.md` — a long-form master reference for client routes, services, templates, and static assets. Consult it before large client-portal changes; keep it roughly in sync when you add client routes/services.
- `README.md` — setup/onboarding narrative.
- `scheduler/HEARTBEAT_JOB.ar.md` / `HEARTBEAT_CHANGES.ar.md` — rationale for the heartbeat job (Arabic).

## Project rule: message copy

`.agents/rules/messages_and_validation.md` is a hard rule: **all** user-facing strings — templates, JS toasts/alerts/modals, form validation, flash messages, backend route/API error bodies — must be terse and punchy. `"Saved successfully"`, `"Required"`, `"Invalid subnet"`, `"Name already in use"`, `"Delete this rule?"` — never full sentences, never stack-trace leakage to the UI. Match this when adding or editing any message.

## Architecture

Three request-serving processes + one background loop, one database, one set of models:

1. **Admin Portal** (`app.py`, blueprint in `admin/routes.py`, port 5000) — operator-facing: customer/tenant creation, global metrics, user management. Auto-seeds a default admin user on startup via `services/auth_service.py: AuthService.seed_default_admin()`.
2. **Client Portal** (`client_app.py`, blueprint in `client/routes.py`, port 8097) — tenant-facing dashboard: peer/device status, DNS filtering, firewall rules. Its own templates/static live under `client/`. Includes an SSE endpoint (`/api/peers/stream`) that fans out concurrent peer-reachability checks via a `ThreadPoolExecutor` to avoid blocking Flask's worker.
3. **FastAPI Gateway** (`fastapi_app/main.py`, port 8098) — the only thing that talks to NetBird, AdGuard, and edge agents. Every route is guarded app-wide by a single `Depends(verify_api_key)` (`fastapi_app/dependencies.py`) checking a bearer token against `INTERNAL_API_KEY`. Both Flask apps call into this gateway as an internal HTTP client, not directly.
4. **Heartbeat job** (`scheduler/heartbeat.py`, `program:heartbeat`, no port) — a dumb pinger loop, independent of the FastAPI package. Every `HEARTBEAT_INTERVAL` seconds it lists peers straight from the internal NetBird API, and POSTs `http://<mesh-ip>:8765/heartbeat` (no auth — mesh is the trust boundary) to every connected peer with a mesh IP. This refreshes the peer-side dead-man-switch (`failsafe_engine.py` on the edge) so it doesn't trip to "basic router" mode; without it, the only liveness signal is incidental dashboard traffic. The peer owns the timeout/state machine; the loop keeps no state and must never die. Other scheduler modules: `cleanup.py`, `monitor.py`, `jobs.py`.

Layering inside this repo: routes/blueprints stay thin and delegate to `services/` (business logic / orchestration of NetBird calls), which use `repositories/` for DB access. Follow this pattern for new admin/client features — don't put SQLAlchemy queries directly in route handlers. `test_clean_arch_suite.py` exists to police this and template health. The FastAPI side mirrors this with `fastapi_app/routes/` → `fastapi_app/services/` → raw `SessionLocal` queries, plus `fastapi_app/schemas/` for Pydantic request/response validation, organized by external system (`adguard/`, `netbird/`, `controller/`).

### Key data model

No local "peers" table — peer/device state is fetched live from the NetBird API per-request and filtered by matching `Client.netbird_group_id`. Persisted models (`models/`): `Client` (tenant, PK is UUID `user_id`), `Edge` (router/device static+reported state), `Token` (NetBird setup keys), `Policy`, `FirewallRule`, `DnsRule`, `CommandLog` (audit trail of commands dispatched to edge agents, JSONB params/output).

### External integrations (all proxied through the FastAPI gateway)

- **NetBird** — customer onboarding creates a NetBird group, a setup key (scoped to that group + `all-peers`), and a default isolation policy, in that order (`services/customer_service.py`). Peer membership for a client is computed by filtering NetBird's `/peers` response against `netbird_group_id`.
- **AdGuard Home** — DNS filtering per edge node, proxied via `fastapi_app/routes/adguard/dns.py` straight to each peer's mesh IP.
- **Edge Agent** — a lightweight daemon on each edge device, listening on port `8765` *inside* the WireGuard overlay only (no separate auth token — trust boundary is the VPN itself). Commands go: Flask → FastAPI gateway → check peer online via NetBird `/peers/{id}` → if online, POST to `http://{mesh_ip}:8765/execute`, else log a rejected `CommandLog` with `reason = "peer_offline"`.

### Auth model

Flask portals use session flags (`admin_logged_in`, `client_logged_in`) checked by `@login_required`-style decorators — not Flask-Login's actual user session (the `user_loader` in both `app.py` and `client_app.py` is a stub returning `None`). The FastAPI gateway uses a single shared bearer token (`INTERNAL_API_KEY`), not per-user auth — it's an internal service-to-service boundary, not a public API.

## Known rough edges

- `app.py` has a standalone `/api/setup-keys` route that references an undefined `internal_key` variable and a hardcoded external URL (`api.networkat.cloud`) — calling it will raise `NameError`, not a request bug.
- `fastapi_app/main.py` currently embeds the literal `INTERNAL_API_KEY` value in the FastAPI `license_info` metadata (visible at `/docs`). Treat this as leaked and flag it if you're touching auth/security in this file — don't propagate the pattern elsewhere.
