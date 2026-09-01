# Networkat SD-WAN Core Web App

Welcome to the **Networkat SD-WAN Core Web App**! This repository houses the orchestration, management, and control gateway for the Networkat SD-WAN core infrastructure. 

This project acts as a centralized brain that binds a multi-portal frontend (Flask-based dashboards) with a high-performance, asynchronous API gateway (FastAPI) to automate private overlay meshes via **NetBird (WireGuard VPN)**, enforce DNS-level filtering via **AdGuard Home**, and dispatch real-time commands directly to edge nodes using a customized **Edge Agent CLI/daemon**.

---

## 📖 Table of Contents
1. [Project Overview & Purpose](#-project-overview--purpose)
2. [Architecture & Tech Stack](#-architecture--tech-stack)
3. [Directory Structure Explanation](#-directory-structure-explanation)
4. [Database & Data Models](#-database--data-models)
5. [External Services & Integrations](#-external-services--integrations)
6. [Authentication & Security Setup](#-authentication--security-setup)
7. [Deployment & Execution Flow](#-deployment--execution-flow)
8. [Developer Context / Instructions for AI](#-developer-context--instructions-for-ai)

---

## 🎯 Project Overview & Purpose

Networkat SD-WAN allows businesses to deploy secure, peer-to-peer virtual private networks (SD-WAN overlays) across public and private clouds, dynamic IPs, and NAT boundaries without manual routing, port-forwarding, or security configurations.

The web application automates three primary domains:
*   **SD-WAN Controller Management:** A centralized portal for administrators (Admin Portal) to register customers, allocate subnets, and monitor the network, alongside a customer-facing console (Client Portal) to check device metrics, WAN states, and configuration options.
*   **NetBird Mesh VPN Integration:** Automated registration of nodes using ephemeral or reusable setup keys, group-based isolation, route publishing for LAN subnets, and bidirectional access control policies.
*   **AdGuard DNS Integration:** Direct controls mapped to edge node IP addresses to toggle DNS protection, construct custom blocking lists, add local rewrite records, audit query logs, and disable specific web applications (blocked services).
*   **Edge Device Command Execution:** Real-time command routing to check edge telemetry, WAN link statuses, and firewall rules directly on the active nodes.

---

## 🏛️ Architecture & Tech Stack

The architecture is built on **Clean Architecture** principles to isolate the database operations from business rules and routing handlers. It runs as three primary Python processes:

```mermaid
graph TD
    subgraph Users & Admins
        A[Platform Administrator] -->|Port 5000| B(Flask Admin Portal)
        C[Client / Tenant User] -->|Port 8097| D(Flask Client Portal)
    end

    subgraph Orchestrator Core (Inside Docker)
        B -->|Shared Secret API Key| E[FastAPI Engine / Gateway]
        D -->|Shared Secret API Key| E
        
        E -->|SQLAlchemy Core / SessionLocal| F[(PostgreSQL Database)]
        B -->|Flask-SQLAlchemy| F
        D -->|Flask-SQLAlchemy| F
        
        G[Celery Scheduler / Placeholders] -.->|Monitoring Jobs| F
    end

    subgraph External Platforms
        E -->|REST API + Bearer Token| H[NetBird Management API]
    end

    subgraph Edge Mesh / WireGuard
        D -->|SSE stream| I{Peers Stream / ThreadPool}
        E -->|HTTP Port 8765| J[Edge Device Agent]
        J -->|Local DNS Proxy| K[AdGuard DNS Service]
    end
```

### 💻 Technology Components
1.  **Frontend & Portals (Flask):**
    *   **Admin Portal** ([app.py](file:///e:/networkat/sdwan/web_app/sdwan/app.py)): Bound by default to port `5000` (production port `8096`). Handles system operator login, customer workspace creation, global metrics inspection, and client user management.
    *   **Client Portal** ([client_app.py](file:///e:/networkat/sdwan/web_app/sdwan/client_app.py)): Bound to port `8097`. Allows individual clients to monitor their peer groups, customize blocking rules, toggles, and view WAN links.
    *   **Real-time Peers Stream:** Features a Server-Sent Events (SSE) router (`/api/peers/stream` in [client/routes.py](file:///e:/networkat/sdwan/web_app/sdwan/client/routes.py)) which runs an asynchronous `ThreadPoolExecutor` to perform concurrent reachability handshakes and WAN-only status pings across multiple nodes to avoid slowing down Flask's event loops.
2.  **API Gateway & Engine (FastAPI):**
    *   **FastAPI Engine** ([fastapi_app/main.py](file:///e:/networkat/sdwan/web_app/sdwan/fastapi_app/main.py)): Runs via Uvicorn on port `8098`. It exposes high-performance endpoints for internal portal traffic.
    *   **Security:** Secured universally via a custom `HTTPBearer` check dependency ([fastapi_app/dependencies.py](file:///e:/networkat/sdwan/web_app/sdwan/fastapi_app/dependencies.py)) matching the internal configuration key.
3.  **Background Schedulers & Live Sockets:**
    *   Predefined skeleton directories ([scheduler/](file:///e:/networkat/sdwan/web_app/sdwan/scheduler) and [websocket/](file:///e:/networkat/sdwan/web_app/sdwan/websocket)) are reserved for scheduled cleanup tasks, offline daemon monitoring, and bidirectional browser socket channels.
4.  **Edge Agents (Port 8765):**
    *   Each edge router device runs a custom light daemon listening on TCP port `8765` within the NetBird VPN overlay address space. Commands are dispatched securely inside the WireGuard trust boundary.

---

## 📂 Directory Structure Explanation

```
sdwan/
├── admin/                  # Flask Admin Blueprint, handles admin views & controller logic
│   └── routes.py           # Admin portal endpoints (Customers, users, proxy peers)
├── client/                 # Flask Client Blueprint, handles client/tenant dashboard
│   ├── routes.py           # Client web views, SSE peer streaming, DNS & VPN-only proxy routes
│   └── static/             # Client-specific styling and assets (styles.css, logo.png)
├── app.py                  # Orchestrator Entrypoint for Admin Portal & seeding functions
├── client_app.py           # Entrypoint for Client Portal
├── extensions.py           # Shareable Flask extension objects (db, migrate, login_manager)
├── entrypoint.sh           # Shell wrapper that launches services inside Docker
├── supervisord.conf        # Config file for supervising Flask portals & FastAPI
├── config/                 # Application Configuration Module
│   ├── database.py         # Flask-SQLAlchemy DB setup
│   ├── settings.py         # Configurations loader class (Postgres URI, pool setup)
│   └── security.py         # Cryptographic settings and keys placeholders
├── database/               # Database raw schemas and setup commands
│   ├── schema.sql          # Empty baseline placeholder (DB structure managed by Alembic)
│   └── seed.py             # System seeding parameters
├── migrations/             # Alembic database migration scripts directory
│   ├── env.py              # Alembic environment hook mapping SQLAlchemy classes
│   └── versions/           # Ordered incremental migrations files
├── models/                 # SQLAlchemy database entities (shared by portals & API engine)
│   ├── base.py             # Declarative SQLAlchemy base config
│   ├── client.py           # Client Model class (Primary tenants tables, linking NetBird groups)
│   ├── system_user.py      # System Operator Model (Orchestrator Admin credentials)
│   ├── edge.py             # Edge router status parameters and location mapping
│   ├── policy.py           # Local policy rule entries mapping to NetBird
│   ├── token.py            # Key provisioning mapping to NetBird setup keys
│   ├── command_log.py      # Historical audit trails of execution commands
│   ├── firewall.py         # Static configurations of Edge firewall parameters
│   └── dns.py              # DNS block records mappings
├── repositories/           # Repositories module encapsulating clean DB operations
│   ├── client_repository.py# Client tenant data abstraction layer
│   ├── customer_repository.py # Customer specific operations wrapper
│   ├── edge_repository.py  # Edge device state update queries
│   └── token_repository.py # Provisioning key status and state check
├── services/               # Flask Application business use-cases
│   ├── auth_service.py     # Portal operator credentials checker and seeding
│   ├── customer_service.py # NetBird automated tenant registration workflows
│   └── edge_service.py     # Edge state processing and API mapping updates
├── fastapi_app/            # High-Performance API Gateway Engine
│   ├── main.py             # FastAPI App definition and Router registers
│   ├── database.py         # Independent scoped FastAPI SQLAlchemy session engine
│   ├── dependencies.py     # Scoped API credentials authentication validation
│   ├── routes/             # FastAPI Route Controllers (Adguard, Netbird, Controller commands)
│   ├── schemas/            # Pydantic schema wrappers validating API schemas
│   └── services/           # Backend Command execution mechanisms
├── scheduler/              # Placeholder for offline daemons checks and cleanup routines
├── websocket/              # Placeholder for live message events socket channels
└── utils/                  # Reusable utilities (IP parsing, validators, crypt keys)
```

---

## 🗄️ Database & Data Models

The system runs on **PostgreSQL**. The database structure is mapped via SQLAlchemy ORM models on both the Flask side (using `Flask-SQLAlchemy`) and the FastAPI side (using standard `SQLAlchemy` scoped sessions mapping to the same tables). 

### 📊 Database Relationships (ERD)

```mermaid
erDiagram
    SYSTEM-USERS {
        int id PK
        string username
        string email
        string full_name
        string password_hash
        string role
        boolean is_active
        timestamp last_login
        timestamp created_at
    }

    CLIENTS {
        uuid user_id PK
        string username UNIQUE
        string password_hashed
        string client_name
        string client_company_name
        string netbird_group_id UNIQUE
        string client_email UNIQUE
        string client_phone_number UNIQUE
        string client_country
        string subscription
        boolean active
        timestamp last_login
        timestamp created_at
    }

    EDGES {
        int id PK
        uuid client_id FK
        string edge_name
        string pubkey UNIQUE
        string assigned_ip
        timestamp last_seen
        text location
        text public_ip
        string status
        int uptime
        int wg_handshake_sec
        boolean apply_requested
        boolean private_only
        text lan_subnet
    }

    TOKENS {
        string token PK
        uuid client_id FK
        boolean is_active
    }

    POLICIES {
        int id PK
        uuid client_id FK
        string name
        string match_type
        string match_value
        string action
        int priority
        boolean enabled
        timestamp updated_at
    }

    FIREWALL-RULES {
        int id PK
        uuid client_id FK
        int edge_id FK
        text rule_name
        string direction
        text src_ip
        text dst_ip
        text dst_port
        string protocol
        string action
        boolean enabled
    }

    DNS-RULES {
        int id PK
        uuid client_id FK
        int edge_id FK
        text domain
        string action
        boolean enabled
        text src_ip
    }

    COMMAND-LOGS {
        uuid id PK
        string peer_id INDEX
        string command_type
        jsonb parameters
        string status
        string reject_reason
        jsonb output
        string requested_by
        timestamp requested_at
        timestamp executed_at
    }

    CLIENTS ||--o{ TOKENS : "owns"
    CLIENTS ||--o{ EDGES : "deploys"
    CLIENTS ||--o{ POLICIES : "defines"
    CLIENTS ||--o{ FIREWALL-RULES : "enforces"
    CLIENTS ||--o{ DNS-RULES : "restricts"
    EDGES ||--o{ FIREWALL-RULES : "applies-to"
    EDGES ||--o{ DNS-RULES : "applies-to"
```

### 📝 Key Model Explanations
*   `Client` ([models/client.py](file:///e:/networkat/sdwan/web_app/sdwan/models/client.py)): Repesents the tenant customers. Primary key `user_id` is a UUID. Contains the `netbird_group_id` that isolatates this client's peers within NetBird.
*   `Edge` ([models/edge.py](file:///e:/networkat/sdwan/web_app/sdwan/models/edge.py)): Holds static and dynamically reported parameters for edge routers. Unique constraint ensures that `edge_name` and `assigned_ip` are unique per client workspace.
*   `CommandLog` ([models/command_log.py](file:///e:/networkat/sdwan/web_app/sdwan/models/command_log.py)): Audit trails for remote command runs on agents. Uses JSONB to hold variable input parameters and command execution returns.

---

## 🔌 External Services & Integrations

The orchestrator operates as a middleware layers translating local database operations into remote calls:

### 🐦 1. NetBird API Orchestration
NetBird acts as the peer-to-peer WireGuard mesh overlay manager.

*   **Automation Flow during Customer Onboarding:**
    When an operator creates a customer (`create_customer` inside [services/customer_service.py](file:///e:/networkat/sdwan/web_app/sdwan/services/customer_service.py)):
    1.  **Group Creation:** Requests NetBird API (`POST /groups`) to create a group named after the client's username. The returned `id` is saved as the client's `netbird_group_id`.
    2.  **Setup Key Provisioning:** Requests NetBird (`POST /setup-keys`) to generate a reusable provisioning key assigned automatically to both the default `all-peers` group and the customer's specific group. The plain text key is stored in the local `tokens` table.
    3.  **Policy Isolation:** Requests NetBird (`POST /policies`) to create a default bidirectional security rule allowing communications strictly among peers inside the customer's group.
*   **Peer Mapping (No local peers table):**
    There is no database peer inventory table. The orchestrator maps peer states in real time:
    1.  Retrieves current peers list from NetBird `/peers` endpoint.
    2.  For a given customer, filters the peer payload by matching the customer's `netbird_group_id` against the list of group IDs assigned to each peer.

### 🛡️ 2. AdGuard DNS Orchestration
AdGuard Home operates as the DNS server resolving peer queries inside the VPN.

*   **FastAPI Routing Gateway:**
    The backend router ([fastapi_app/routes/adguard/dns.py](file:///e:/networkat/sdwan/web_app/sdwan/fastapi_app/routes/adguard/dns.py)) acts as a wrapper proxy, redirecting DNS settings changes directly to the AdGuard management API using the peer's assigned mesh IP address:
    *   `/status`: Gets current DNS server metrics and rule states on the node.
    *   `/protection` (POST): Toggles global DNS-blocking filter.
    *   `/rewrites` (GET/POST/DELETE): Configures custom DNS rewrites mapping hostnames to local overlay IPs.
    *   `/filtering/rules` (POST): Updates raw user blocking lists.
    *   `/blocked_services`: Restricts access to specific sites/apps (e.g. TikTok, YouTube, Reddit).

### 🕹️ 3. Controller Commands Lifecycle
The backend command service ([fastapi_app/services/controller/command_service.py](file:///e:/networkat/sdwan/web_app/sdwan/fastapi_app/services/controller/command_service.py)) routes commands to the remote edge agent.

*   **Check Sequence:**
    ```
    Flask Dashboard 
         │ 
         │ 1. POST /peers/{id}/commands (Bearer Token)
         ▼
    FastAPI Gateway 
         │ 
         │ 2. GET NetBird API /peers/{id}
         ├─────────────────────────────────────────┐
         ▼ (If offline)                            ▼ (If online)
    Log Command Rejected                      GET Peer mesh IP address
    [status = "rejected",                     & POST Command to Agent
    reason = "peer_offline"]                  http://{mesh_ip}:8765/execute
                                                   │
                                                   ├───────────────────────────┐
                                                   ▼ (Success)                 ▼ (Failure/Timeout)
                                              Log Execution Done          Log Agent Error
                                              [status = "success"]        [status = "error"]
    ```

---

## 🔒 Authentication & Security Setup

The security configuration isolates traffic planes into public-facing and internal-only paths.

### 🔑 Endpoint Protection
*   **FastAPI Gateway Engine (`8098`):**
    Requires a Bearer Token security dependency (`verify_api_key`) configured on the main FastAPI application class. If the request doesn't include the matching `INTERNAL_API_KEY` ("57e443f0625abfa313425a020626b078899d4db7ff8d09d59c5f7ae4d0c6d874"), it returns an HTTP `401 Unauthorized` response.
*   **Flask Portals (`5000` / `8097`):**
    Utilize sessions to track logged-in states (`admin_logged_in` and `client_logged_in` keys). Critical views are protected by the `@login_required` decorators checking these keys.

### 🛡️ Mesh Trust Boundary
*   **Edge Agents (Port `8765`):**
    Agents run without local access control tokens. They establish security by binding strictly to the NetBird WireGuard network interface. Because the gateway communicates with edge agents using the internal VPN IP space, the command traffic is protected by WireGuard encryption.

---

## 🐳 Deployment & Execution Flow

The project is structured to run as a single Docker container, supervising multiple services simultaneously.

### ⚙️ Multi-Process Supervision
Supervisor manages and runs the services inside the container ([supervisord.conf](file:///e:/networkat/sdwan/web_app/sdwan/supervisord.conf)):
*   `program:admin`: Flask app running via Gunicorn on `0.0.0.0:5000`.
*   `program:client`: Flask app running via Gunicorn on `0.0.0.0:8097`.
*   `program:api`: FastAPI gateway running via Uvicorn on `0.0.0.0:8098`.

### 🛡️ Non-Root Execution Permissions
To avoid permission conflicts on volume-mounted directories on the host, the [Dockerfile](file:///e:/networkat/sdwan/web_app/sdwan/Dockerfile) does the following:
*   Creates a non-root group `devteam` (GID `1002` matching host) and user `appuser` (UID `1001`).
*   Runs the Supervisor process as `appuser` (rather than root).
*   Enforces a `umask=002` in `supervisord.conf` to ensure files created by Gunicorn or Uvicorn (such as database migrations or log files) remain group-writable by `devteam`.

### 🚀 Container Launch Sequence
When the container starts, it executes [entrypoint.sh](file:///e:/networkat/sdwan/web_app/sdwan/entrypoint.sh):
1.  Loads environmental config files.
2.  Applies database schema updates via Alembic migration files (`flask db upgrade`).
3.  Launches Supervisor to start the processes.

---

## 🤖 Developer Context / Instructions for AI

When writing code or refactoring this repository, follow these rules:

### ✏️ Coding & Naming Conventions
*   **Flask Portals:** Define blueprints with clear names (e.g., `admin_bp`, `client_bp`). Keep controllers slim; delegate data retrieval to the service layer.
*   **FastAPI Gateway:** Name files within `routes/` matching their API tag (e.g., [fastapi_app/routes/netbird/peers.py](file:///e:/networkat/sdwan/web_app/sdwan/fastapi_app/routes/netbird/peers.py)). Use Pydantic schemas in `schemas/` to validate request payloads.
*   **Repositories:** Use the repository pattern. Write database query logic inside `repositories/` (e.g., [repositories/edge_repository.py](file:///e:/networkat/sdwan/web_app/sdwan/repositories/edge_repository.py)) and instantiate them in the service layer rather than running raw DB sessions in controller routes.

### 🔄 Scoped DB Transactions
*   Always invoke `db.commit()` or `db.rollback()` within services/repositories to keep database states consistent.
*   Avoid importing Flask's SQLAlchemy extensions inside FastAPI gateway files. FastAPI uses a scoped session (`SessionLocal` inside [fastapi_app/database.py](file:///e:/networkat/sdwan/web_app/sdwan/fastapi_app/database.py)) to run database operations.

### ⚡ Async Handling in FastAPI
*   Use `async def` for FastAPI endpoints.
*   Because libraries like `requests` and raw database sessions are synchronous/blocking, wrap these calls in `run_in_threadpool` (e.g., `await run_in_threadpool(requests.get, ...)`) to avoid blocking the main ASGI loop.

### 🔑 Security & Configuration
*   **Do not hardcode secrets:** Read tokens and passwords using `os.getenv` or `config.settings`.
*   Ensure that any endpoint dispatching shell commands validates user input to prevent command injection vulnerabilities.