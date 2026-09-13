# Networkat SD-WAN Core Web App

Welcome to the **Networkat SD-WAN Core Web App**! This repository is the brain and centralized management portal for the Networkat SD-WAN infrastructure.

This guide is written to help any developer completely understand what this project is, how it works, how its components interact, and how to safely modify it.

---

## 📖 Table of Contents
1. [What is this Project?](#-what-is-this-project)
2. [How the System Works (Architecture)](#-how-the-system-works-architecture)
3. [Directory Structure Explanation](#-directory-structure-explanation)
4. [How to Modify the Code (Developer Guide)](#-how-to-modify-the-code-developer-guide)
5. [Database & Data Models](#-database--data-models)
6. [External Integrations](#-external-integrations)
7. [Running & Deployment](#-running--deployment)

---

## 🎯 What is this Project?

**Networkat SD-WAN** is a platform that allows businesses to create secure, peer-to-peer virtual private networks (SD-WAN overlays) across public and private clouds, dynamic IPs, and NAT boundaries without manual routing or port-forwarding.

This web application acts as the control panel for the entire system. It provides:
- **Client Portal (Dashboard):** A customer-facing portal where tenants can monitor their edge devices (peers), configure stateful L4/L7 firewall rules, manage DNS filtering (AdGuard), and configure network routing.
- **Admin Portal:** A high-level platform for operators to manage customer accounts, subscriptions, and platform-wide settings.
- **API Gateway:** An internal communication hub that talks to external services like NetBird (WireGuard VPN manager) and AdGuard Home, as well as sending direct commands to edge devices.

---

## 🏛️ How the System Works (Architecture)

The system is designed using **Clean Architecture** to separate database operations from business logic and routing handlers. It runs as **four separate processes** sharing one PostgreSQL database and one set of SQLAlchemy models. Supervisor manages all four inside a single Docker container.

### The 4 Main Processes:

1. **Admin Portal (Flask) - Port `5000`**
   - **Role:** Platform operator portal (`app.py`, blueprint in `admin/`).
   - **Purpose:** Handles customer workspace creation, global metrics inspection, and client user management.

2. **Client Portal (Flask) - Port `8097`**
   - **Role:** Tenant-facing dashboard (`client_app.py`, blueprint in `client/`).
   - **Purpose:** Allows clients to monitor peer groups, configure stateful firewall rules, DNS filtering, and aliases. Uses Vanilla JS and Jinja2 templates for the frontend.

3. **API Gateway & Engine (FastAPI) - Port `8098`**
   - **Role:** The internal backend microservice (`fastapi_app/main.py`).
   - **Purpose:** The only component that talks to external APIs (NetBird, AdGuard, Edge Agents). The Flask portals call this gateway as internal HTTP clients to perform complex or external actions.

4. **Heartbeat Scheduler (Background Job)**
   - **Role:** A continuous loop (`scheduler/peers_heartbeat.py`).
   - **Purpose:** Runs every ~60 seconds to POST a heartbeat to all active edge peers via the mesh. This prevents edge routers from dropping into a "basic router" failsafe mode.

---

## 📂 Directory Structure Explanation

The codebase is organized modularly to keep everything predictable. Here is where everything lives:

```text
/opt/networkat_sdwan/core/web_app/
├── admin/                       # Flask Admin Blueprint (Controllers, templates, and static files for the Admin portal)
├── client/                      # Flask Client Blueprint (Tenant dashboard - Clean Architecture)
│   ├── routes/                  # Modular domain route controllers (auth.py, dashboard.py, peer_api.py, firewall.py, etc.)
│   ├── static/                  # Dedicated CSS & JS assets (e.g., network_math.js, firewall.js, base.css)
│   └── templates/               # Streamlined Jinja2 HTML templates extending client_base.html
├── config/                      # Flask & Database Configuration (e.g., settings.py, Postgres URI)
├── database/                    # Database raw schemas, session setup, and seed scripts
├── fastapi_app/                 # High-Performance FastAPI Internal Gateway
│   ├── routes/                  # FastAPI controllers (Adguard, Netbird, Controller commands)
│   ├── schemas/                 # Pydantic validation schema wrappers
│   └── services/                # Backend command execution mechanisms
├── middleware/                  # Request middleware & telemetry interceptors
├── migrations/                  # Alembic database migration scripts directory (flask db migrate/upgrade)
├── models/                      # Shared SQLAlchemy ORM models (Client, Edge, Token, Policy, FirewallRule, etc.)
├── repositories/                # Clean Architecture Data Access Objects (DAO) - Handles raw DB queries
├── scheduler/                   # Background loops and jobs (e.g., peers_heartbeat.py)
├── services/                    # Flask Application business logic (e.g., netbird_service.py, firewall_service.py)
├── tests/                       # Automated test suites for continuous integration
├── utils/                       # Shared utilities (IP parsing, validators, email logic, file-based caching)
├── app.py                       # Orchestrator Entrypoint for Admin Portal
├── client_app.py                # Orchestrator Entrypoint for Client Portal
├── supervisord.conf             # Supervisor config for managing the 4 processes
└── entrypoint.sh                # Shell wrapper that waits for the DB, runs migrations, and launches supervisor
```

---

## 🛠️ How to Modify the Code (Developer Guide)

If you need to edit the site, add features, or fix bugs, **you must strictly follow these rules** to maintain the stability and visual consistency of the project.

### 1. Clean Architecture (Separation of Concerns)
- **Do not write raw database queries inside route controllers (like `client/routes/`).**
- **Flow of Logic:** Routes should extract request data, call a `service/` function for business logic, and the service calls a `repository/` for database interactions.

### 2. Zero Breaking Changes
- Do not arbitrarily change existing endpoint URLs or Jinja2 `url_for('client.xxx')` variable names. Doing so will break the frontend or external agent scripts (like `install.sh`).

### 3. Strict UI / UX & CSS Rules
- **Strictly NO UPPERCASE:** Never use `text-transform: uppercase` in any CSS file. Never write UI labels, buttons, headers, or badges in ALL CAPS. Always use standard **Sentence case** or **Title case**.
- **Ultra-Concise Messages:** Keep user-facing toasts, flash messages, and validation errors extremely short and punchy (e.g., `"Saved"`, `"Invalid subnet"`, `"Updated successfully"`). Never leak stack traces, backend errors, or verbose explanations to the UI.
- **No Native Alerts:** Never use native browser `alert()`, `prompt()`, or `confirm()`. Always use the project's built-in custom toast and modal system (`client/static/js/toast.js`).
- **Inline Editing over Bulk Saves:** Prefer saving data inline per field (e.g., using `✓` and `✗` buttons) rather than full page bulk "Apply changes" bars where applicable.

### 4. Code Principles
- **Mathematical Subnet Normalization:** Never throw errors if a user inputs a host address instead of a network address (e.g., `192.168.10.2/24`). The frontend (`network_math.js`) and backend (`network_validators.py`) must automatically convert it to a valid network address (`192.168.10.0/24`) using unsigned 32-bit bitwise math.
- **Environment Variables:** Use `config.settings` rather than raw `os.getenv` to ensure variables are parsed safely via `python-dotenv`.
- **FastAPI Asynchronous Integrity:** When calling synchronous libraries (like SQLAlchemy or `requests`) inside FastAPI `async def` endpoints, wrap them in `run_in_threadpool` so you don't block the ASGI event loop.

---

## 🗄️ Database & Data Models

The system runs on **PostgreSQL**. Models live in the `models/` directory. They are shared by both the Flask apps and the FastAPI gateway.

**Key Concepts:**
- `Client`: Represents tenant customers. Contains `netbird_group_id` for isolation.
- There is **no local `peers` table** saving edge statuses. Peer presence and states are fetched **live** from the NetBird API to ensure absolute truth.
- `Token`: Short-lived Setup keys (`usage_limit: 1`, 20-min validity) for new peer installation.

---

## 🔌 External Integrations

1. **NetBird API:** Manages the WireGuard mesh. Creates groups, issues setup keys (`/api/v1/auth/install-peer`), and provides telemetry.
2. **AdGuard DNS:** FastAPI redirects DNS configs, category filtering, and blocked services directly to the AdGuard API via the peer's mesh IP.
3. **Edge Agents (Port 8765):** Edge routers run a local daemon. The Web App sends real-time configurations (Firewall rules, aliases) by doing a direct `POST http://<peer_mesh_ip>:8765/<command>` entirely inside the secure VPN tunnel.

---

## 🐳 Running & Deployment

The system is deployed via **Docker Compose**. It handles Nginx, Postgres, pgAdmin, NetBird, and this Web App in an orchestrated network.

```bash
# To run the entire stack (from the /opt/networkat_sdwan/core directory):
docker compose up -d --build
```
`compose.override.yaml` bind-mounts this directory. The Flask and FastAPI servers use `--reload`, so edits to Python files are picked up live upon saving without needing a restart.

**Applying Database Migrations:**
```bash
# Access the web app container shell and run:
flask db migrate -m "Description of changes"
flask db upgrade
```

---
*For a deeper dive into the exact API flows, caching mechanisms, and complete component list, see `PROJECT_ARCHITECTURE.md`.*