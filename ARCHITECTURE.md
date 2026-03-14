# Circuit Breaker Architecture

## Overview

Circuit Breaker is a self-hosted homelab visualization platform built as a modern, security-first full-stack application. The architecture follows a microservices-oriented design with a unified deployment model, running all services in a single container for simplicity while maintaining clear separation of concerns.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Container (Mono Image)                   │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │   nginx    │  │  PostgreSQL  │  │   NATS Server    │    │
│  │  (8080/    │  │   (5432)     │  │   (JetStream)    │    │
│  │   8443)    │  │              │  │     (4222)       │    │
│  └─────┬──────┘  └──────┬───────┘  └────────┬─────────┘    │
│        │                │                    │               │
│  ┌─────▼────────────────▼────────────────────▼─────────┐   │
│  │            FastAPI Backend (Uvicorn)                  │   │
│  │                  (Port 8000)                          │   │
│  │  ┌─────────┐  ┌──────────┐  ┌──────────────────┐    │   │
│  │  │   API   │  │ Services │  │   Integrations   │    │   │
│  │  │ Routes  │  │  Layer   │  │  (Proxmox, SNMP) │    │   │
│  │  └─────────┘  └──────────┘  └──────────────────┘    │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              Background Workers (4 processes)            │ │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────────────┐  │ │
│  │  │ Discovery  │ │  Webhook   │ │   Notification     │  │ │
│  │  │   Worker   │ │   Worker   │ │     Worker         │  │ │
│  │  └────────────┘ └────────────┘ └────────────────────┘  │ │
│  │  ┌────────────┐                                         │ │
│  │  │ Telemetry  │                                         │ │
│  │  │  Collector │                                         │ │
│  │  └────────────┘                                         │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              Redis (Port 6379)                           │ │
│  │   • Telemetry cache                                      │ │
│  │   • Pub/Sub for real-time updates                       │ │
│  │   • Memory-capped at 128MB                              │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │             pgbouncer (Port 6432)                        │ │
│  │   • Transaction-mode connection pooling                  │ │
│  │   • Backend → pgbouncer → PostgreSQL                    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │             Supervisord (Process Manager)                │ │
│  │   • Manages all services within the container            │ │
│  │   • Health monitoring and auto-restart                   │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              React SPA (Built Static Assets)             │ │
│  │   • Served by nginx from /app/frontend/dist              │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
                    /data (Volume)
              • PostgreSQL data
              • Uploads & branding
              • TLS certificates
              • Vault encryption key
              • Log files
```

---

## Tech Stack

### Frontend

| Technology | Version | Purpose |
|------------|---------|---------|
| **React** | 18.3.0 | UI framework — component-based architecture |
| **Vite** | 7.3.1 | Build tool — fast dev server and optimized production builds |
| **React Router** | 6.24.0 | Client-side routing — SPA navigation |
| **ReactFlow** | 11.11.4 | Interactive topology graph visualization |
| **Tailwind CSS** | 3.4.19 | Utility-first CSS framework for styling |
| **Axios** | 1.7.0 | HTTP client — API communication |
| **Framer Motion** | 12.34.4 | Animation library for UI transitions |
| **i18next** | 25.5.2 | Internationalization — multi-language support |
| **Plotly.js** | 2.35.2 | Data visualization for telemetry charts |
| **Recharts** | 2.15.0 | Additional charting library |
| **D3** | (via deps) | Force-directed layouts, graph algorithms |
| **Graphology** | 0.26.0 | Graph data structures for topology algorithms |
| **Sigma.js** | 3.0.2 | High-performance graph rendering |
| **DOMPurify** | 3.3.2 | XSS sanitization for user-generated HTML/Markdown |
| **Vitest** | 4.0.18 | Testing framework (Vite-native) |
| **ESLint** | 9.39.3 | Linting with security plugin |
| **TypeScript** | 5.9.3 | Type safety |

**Build Pipeline:**
- Vite compiles and bundles React components into optimized static assets
- Output: `/app/frontend/dist/` served by nginx
- Version synchronization from `VERSION` file at build time

---

### Backend

| Technology | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.12.9 | Runtime language |
| **FastAPI** | ≥0.111.0 | Modern async web framework with auto-generated OpenAPI docs |
| **Uvicorn** | ≥0.29.0 | ASGI server with HTTP/1.1, WebSocket support |
| **SQLAlchemy** | ≥2.0.0 | ORM for database abstraction |
| **Alembic** | ≥1.13.0 | Database migration tool |
| **Pydantic** | ≥2.6.0 | Data validation and settings management via models |
| **PostgreSQL** | 15 | Primary database (Debian Bookworm default) |
| **asyncpg** | ≥0.29.0 | Async PostgreSQL driver (used by SQLAlchemy) |
| **psycopg2-binary** | ≥2.9.0 | Sync PostgreSQL driver (fallback/CLI tools) |
| **PyJWT** | ≥2.8.0 | JWT token generation/validation for auth |
| **bcrypt** | ≥4.0 | Password hashing (Argon2-like strength) |
| **cryptography** | ≥42.0.8 | Fernet encryption for secrets vault |
| **APScheduler** | ≥3.10 | Background job scheduling (telemetry polls, scans) |
| **nats-py** | ≥2.9.0 | NATS JetStream client — async message bus |
| **redis[hiredis]** | ≥5.0.0 | Redis client with high-performance C parser |

**Integrations:**
| Library | Purpose |
|---------|---------|
| **proxmoxer** | Proxmox VE API client — cluster/VM discovery |
| **pysnmp** | SNMP v1/v2c/v3 polling for network devices |
| **python-nmap** | nmap wrapper for network scanning |
| **scapy** | Packet crafting for ARP/ICMP discovery |
| **pyipmi** | IPMI/BMC telemetry (iDRAC, iLO) |
| **zeroconf** | mDNS/Bonjour service discovery |
| **docker** | Docker Engine API client for container discovery |
| **requests** / **httpx** | HTTP clients for webhooks, external APIs |

**Security & Quality:**
| Tool | Purpose |
|------|---------|
| **slowapi** | Rate limiting (per-IP, token-bucket) |
| **bleach** | HTML sanitization |
| **prometheus-client** | Metrics export for observability |
| **pyotp** | TOTP two-factor authentication (RFC 6238) |
| **cachetools** | In-memory caching (rate limit profiles, config) |
| **pytest** | Testing framework |
| **ruff** | Fast Python linter/formatter (Rust-based) |
| **mypy** | Static type checker |

---

### Database Layer

**PostgreSQL 15 (Embedded):**
- Runs inside the mono container, managed by supervisord
- Data persisted to `/data/postgres/` on the host volume
- Connection pooling via **pgbouncer** (transaction mode)
  - Backend connects to `localhost:6432` (pgbouncer)
  - pgbouncer forwards to `localhost:5432` (PostgreSQL)
  - Reduces connection overhead for FastAPI's async model

**Schema Management:**
- **Alembic migrations** baked into Docker image at build time
- Auto-applied on container startup via `20-migrate.sh` script
- Migration history tracked in `alembic_version` table

**Connection Pooling:**
- SQLAlchemy pool size: `DB_POOL_SIZE` (default 10)
- Max overflow: `DB_MAX_OVERFLOW` (default 10)
- Low-memory devices (Raspberry Pi): set to 3–5 pool / 2–3 overflow

**Key Tables:**
- `entities` — hardware, services, networks (polymorphic inheritance)
- `relationships` — connections between entities (network cables, service dependencies)
- `users` — authentication + RBAC roles
- `audit_log` — tamper-evident hash chain for all actions
- `discoveries` — scan jobs and results
- `telemetry_snapshot` — time-series health metrics
- `vault_credentials` — Fernet-encrypted secrets

---

### Message Bus (NATS JetStream)

**Purpose:** Asynchronous work queue and event streaming between API and workers.

**Streams:**
- `discovery-jobs` — scan tasks dispatched from API, consumed by discovery worker
- `webhook-jobs` — webhook dispatch tasks
- `notification-jobs` — alert/notification tasks
- `telemetry-jobs` — scheduled telemetry collection

**Authentication:**
- **Mandatory** `NATS_AUTH_TOKEN` — shared token between server and clients
- Optional TLS (`NATS_TLS=true`) for encrypted transport

**Durability:**
- JetStream state persisted to `/data/nats/`
- Survives container restarts; at-least-once delivery semantics

**Why NATS?**
- Lightweight (< 10MB binary)
- Built-in JetStream (persistent queues, no external dependencies)
- Async-native (works seamlessly with Python asyncio)

---

### Cache & Real-Time (Redis)

**Purpose:**
1. **Telemetry cache** — reduces database load for frequently-polled metrics
2. **Pub/Sub channels** — push real-time updates to WebSocket clients
   - `topology:updates` — entity/relationship changes
   - `telemetry:live` — live sensor readings (CPU, temp, power)
   - `discovery:progress` — scan progress updates

**Configuration:**
- Bind: `127.0.0.1:6379` (internal only)
- Max memory: 128MB (LRU eviction policy)
- Persistence: disabled (cache-only mode)
- Optional password from `/data/.redis_pass`

**Redis Client:**
- **redis-py** with **hiredis** (C parser for 10x performance on large responses)

---

### Web Server (nginx)

**Roles:**
1. **Static file serving** — React SPA from `/app/frontend/dist/`
2. **API reverse proxy** — forwards `/api/*` to FastAPI on `localhost:8000`
3. **WebSocket proxy** — upgrades HTTP connections for `/api/v1/*/stream` endpoints
4. **TLS termination** — handles HTTPS on port 8443

**Ports:**
- `8080` — HTTP (redirects to HTTPS, except `/api/v1/health` for Docker healthcheck)
- `8443` — HTTPS (main application)

**Security Headers (All Responses):**
- `Content-Security-Policy` — strict CSP with `frame-ancestors 'none'`
- `Strict-Transport-Security` — HSTS with 2-year max-age
- `X-Frame-Options: DENY` — clickjacking protection
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` — disables camera, microphone, geolocation, payments, USB

**TLS Certificates:**
- Mounted from `/data/tls/{fullchain.pem,privkey.pem}`
- Provided by user or generated during OOBE wizard
- Supports Let's Encrypt (external) or self-signed CA (local)

---

### Process Management (Supervisord)

**Supervisord** manages all services within the mono container as a single-container microservices orchestrator.

**Process Startup Order (Priority):**
1. **PostgreSQL** (priority 10) — database must be ready first
2. **pgbouncer** (priority 15) — connection pooler starts after Postgres
3. **NATS** (priority 20) — message bus for workers
4. **Redis** (priority 25) — cache and pub/sub
5. **Backend API + Workers** (priority 30) — FastAPI app and 4 worker processes
6. **nginx** (priority 40) — frontend and proxy (last to start)

**Workers (4 processes):**
- `worker-00` — **Discovery Worker** — nmap, SNMP, ARP, Proxmox scans
- `worker-01` — **Webhook Worker** — HTTP webhook dispatch (Slack, Discord, custom)
- `worker-02` — **Notification Worker** — alert routing and delivery
- `worker-03` — **Telemetry Collector** — scheduled polling of iDRAC/iLO/SNMP/UPS

**Logs:**
- Each service writes to `/data/{service}.log` and `/data/{service}_err.log`
- Supervisord master log: `/data/supervisord.log`
- All logs accessible from host at `${CB_DATA_DIR:-./circuitbreaker-data}/`

**Auto-Restart:**
- All services configured with `autorestart=true`
- Start retries: 5–10 attempts with backoff
- Graceful shutdown timeout: 20–30 seconds

---

## Application Architecture

### Backend Structure

```
apps/backend/src/app/
├── api/                    # FastAPI route handlers
│   ├── auth.py            # Login, logout, session, MFA
│   ├── entities.py        # CRUD for hardware, services, networks
│   ├── relationships.py   # Connections between entities
│   ├── discovery.py       # Scan dispatch, results, review queue
│   ├── telemetry.py       # Metrics polling, history, WebSocket stream
│   ├── topology.py        # Graph layout, positions, visual state
│   ├── integrations.py    # Proxmox, SNMP, Docker integration endpoints
│   ├── webhooks.py        # Webhook CRUD and test dispatch
│   ├── settings.py        # Global settings (RBAC, branding, etc.)
│   └── admin.py           # User management, audit log, vault
├── core/                   # Shared utilities
│   ├── config.py          # Pydantic settings from env vars
│   ├── security.py        # JWT, bcrypt, session management
│   ├── rbac.py            # Role-based access control logic
│   ├── audit_chain.py     # Tamper-evident hash chain for audit log
│   ├── vault.py           # Fernet encryption for secrets
│   ├── rate_limit.py      # slowapi rate limiting profiles
│   ├── url_validation.py  # SSRF guard for webhooks
│   ├── network_acl.py     # CIDR allowlist for scan targets
│   └── ws_manager.py      # WebSocket connection pool
├── db/                     # Database layer
│   ├── models.py          # SQLAlchemy ORM models
│   ├── session.py         # Async session factory
│   └── base.py            # Base model with common columns
├── schemas/                # Pydantic models for request/response
│   ├── entities.py        # Entity schemas
│   ├── auth.py            # Login, token schemas
│   ├── discovery.py       # Scan job, result schemas
│   └── telemetry.py       # Metric schemas
├── services/               # Business logic layer
│   ├── entity_service.py  # Entity CRUD operations
│   ├── discovery_service.py # Scan orchestration
│   ├── telemetry_service.py # Metrics collection
│   ├── vault_service.py   # Secret encryption/decryption
│   └── audit_service.py   # Audit log write + verification
├── integrations/           # External system clients
│   ├── proxmox.py         # Proxmox API client
│   ├── snmp.py            # SNMP poller
│   ├── ipmi.py            # IPMI client (iDRAC, iLO)
│   └── docker_client.py   # Docker API client
├── workers/                # Background job processors
│   ├── main.py            # Worker entrypoint (switches by --type flag)
│   ├── discovery.py       # Discovery worker (nmap, ARP, etc.)
│   ├── webhook.py         # Webhook dispatch worker
│   ├── notification.py    # Notification worker
│   └── telemetry.py       # Telemetry collection worker
├── middleware/             # FastAPI middleware
│   ├── security_headers.py # Security headers on all responses
│   ├── cors.py            # CORS configuration
│   └── logging.py         # Request/response logging with redaction
└── main.py                 # FastAPI app factory
```

**Key Design Patterns:**
- **Service Layer:** Business logic isolated from API routes (testable, reusable)
- **Repository Pattern:** Database access abstracted via services (easy to mock)
- **Dependency Injection:** FastAPI's `Depends()` for auth, DB sessions, settings
- **Async/Await:** All I/O is async (DB, HTTP, NATS, Redis) for concurrency
- **Pydantic Validation:** Type-safe request/response models with auto-generated OpenAPI docs

---

### Frontend Structure

```
apps/frontend/src/
├── api/                    # API client wrappers (Axios)
│   ├── auth.js            # Login, logout, session
│   ├── entities.js        # Entity CRUD
│   ├── discovery.js       # Scan operations
│   ├── telemetry.js       # Metrics fetching
│   └── topology.js        # Graph data
├── components/             # Reusable React components
│   ├── common/            # Buttons, modals, forms
│   ├── topology/          # ReactFlow nodes, edges, controls
│   ├── discovery/         # Scan results, review queue
│   ├── telemetry/         # Charts, badges, live data
│   └── layout/            # Header, sidebar, navigation
├── pages/                  # Route-level page components
│   ├── MapPage.jsx        # Main topology visualization
│   ├── DiscoveryPage.jsx  # Scan dashboard
│   ├── EntitiesPage.jsx   # Entity table/CRUD
│   ├── TelemetryPage.jsx  # Metrics dashboard
│   ├── SettingsPage.jsx   # Global settings UI
│   └── LoginPage.jsx      # Authentication
├── hooks/                  # Custom React hooks
│   ├── useAuth.js         # Authentication context
│   ├── useWebSocket.js    # WebSocket subscription manager
│   ├── useTelemetry.js    # Live telemetry polling
│   └── useTopology.js     # Graph state management
├── context/                # React Context providers
│   ├── AuthContext.jsx    # User session state
│   └── ThemeContext.jsx   # Dark/light mode
├── utils/                  # Helper functions
│   ├── api.js             # Axios instance with interceptors
│   ├── websocket.js       # WebSocket client wrapper
│   └── formatters.js      # Data formatting utilities
├── styles/                 # Global CSS, Tailwind config
└── App.jsx                 # Root component with routing
```

**State Management:**

- **React Context** for global state (auth, theme, settings)
- **React Hooks** for local component state
- **React Query** (planned) for server state caching

**WebSocket Integration:**

- Custom `useWebSocket` hook manages connections per stream
- Auto-reconnect with exponential backoff
- Redux-like action dispatchers for incoming events

---

## Data Flow

### 1. User Authentication Flow

```
User → Login Form (React)
  ↓
Frontend → POST /api/v1/auth/login (FastAPI)
  ↓
Backend → Verify bcrypt password → Generate JWT
  ↓
Backend → Set HttpOnly cookie (cb_session)
  ↓
Frontend ← 200 OK + user data
  ↓
AuthContext stores user → Redirect to /map
```

**Security Features:**

- HttpOnly, Secure, SameSite=Strict cookies (XSS-safe)
- CSRF token via `X-CSRF-Token` header (double-submit pattern)
- JWT with short expiry (15 min) + refresh token
- Optional TOTP MFA second factor
- Account lockout after 5 failed attempts (15 min lockout)

---

### 2. Discovery Scan Flow

```
User → "Launch Scan" (React)
  ↓
Frontend → POST /api/v1/discovery/scans (FastAPI)
  ↓
Backend → Validate target CIDR → Create scan job in DB
  ↓
Backend → Publish job to NATS stream (discovery-jobs)
  ↓
Discovery Worker ← Consume job from NATS
  ↓
Discovery Worker → Execute nmap/SNMP/ARP scan
  ↓
Discovery Worker → Write results to DB (discovered_hosts table)
  ↓
Discovery Worker → Publish progress events to Redis (pub/sub)
  ↓
Backend → Stream progress via WebSocket (/api/v1/discovery/stream)
  ↓
Frontend ← WebSocket updates → React state → Live UI update
```

**Concurrency:**

- Multiple workers can process scans in parallel
- NATS ensures at-least-once delivery (no lost jobs)
- Redis pub/sub broadcasts progress to all connected WebSocket clients

---

### 3. Telemetry Collection Flow

```
APScheduler (Backend) → Schedule telemetry job (every 5 min)
  ↓
Backend → Publish telemetry job to NATS (telemetry-jobs)
  ↓
Telemetry Worker ← Consume job from NATS
  ↓
Telemetry Worker → Poll SNMP/IPMI/Proxmox for metrics
  ↓
Telemetry Worker → Write snapshot to DB (telemetry_snapshot table)
  ↓
Telemetry Worker → Publish to Redis (telemetry:live channel)
  ↓
Backend → WebSocket stream (/api/v1/telemetry/stream)
  ↓
Frontend ← WebSocket updates → Update HUD badges (CPU, temp, power)
```

**Caching:**

- Recent metrics cached in Redis (5-min TTL)
- Reduces DB load for frequently-polled entities
- Cache hit: return from Redis; cache miss: query DB

---

### 4. Topology Rendering Flow

```
User → Open /map (React)
  ↓
Frontend → GET /api/v1/topology (FastAPI)
  ↓
Backend → Query entities + relationships from DB
  ↓
Backend → Apply saved layout positions (or compute with Dagre/D3)
  ↓
Frontend ← Receive nodes/edges JSON
  ↓
ReactFlow → Render interactive graph
  ↓
User → Drag node → Save position
  ↓
Frontend → PATCH /api/v1/entities/{id}/position
  ↓
Backend → Update position in DB + publish to Redis
  ↓
WebSocket broadcast → All clients → Live position update
```

**Layout Algorithms:**

- **Hierarchical:** Dagre (layered, top-down)
- **Force-directed:** D3-force (physics-based)
- **Radial:** Custom D3 radial tree
- **Concentric rings:** Sigma.js + custom algorithm
- **Manual:** User-dragged positions (saved to DB)

---

## Security Architecture

### Defense-in-Depth Layers

**1. Transport Security**

- HTTPS only (nginx terminates TLS)
- HSTS enforced (2-year max-age)
- WebSocket over TLS (WSS) in production (`CB_WS_REQUIRE_WSS=true`)

**2. Authentication & Authorization**

- JWT with HttpOnly cookies (XSS-safe)
- CSRF protection via `X-CSRF-Token` header
- TOTP MFA (RFC 6238)
- Role-based access control (4 roles: viewer, editor, admin, demo)
- Granular scopes (`read:*`, `write:hardware`, `delete:*`, etc.)

**3. Secrets Management**

- **Vault:** Fernet encryption for credentials (SNMP, Proxmox, SMTP)
- Vault key auto-generated during OOBE, persisted to `/data/.env`
- Key hash stored in DB (never the key itself)

**4. Input Validation & Sanitization**

- Pydantic models validate all API inputs
- DOMPurify sanitizes user HTML/Markdown (XSS prevention)
- SQL injection prevention via SQLAlchemy parameterized queries
- File upload magic-byte validation (reject mismatched MIME types)

**5. SSRF Prevention**

- Webhook URLs resolved and checked against RFC 1918, loopback, link-local
- Configurable CIDR allowlist for scan targets (`CB_NETWORK_ACL`)
- Airgap mode disables all outbound scanning (`CB_AIRGAP=true`)

**6. Rate Limiting**

- Per-IP rate limiting via slowapi (token-bucket algorithm)
- Three profiles: relaxed, normal, strict (live-switchable)
- Auth endpoints: 5 req/min; scans: 10 req/min; general: 60 req/min

**7. Audit Logging**

- Tamper-evident SHA-256 hash chain
- Every action logged with IP, User-Agent, actor, role, diff
- Chain verification endpoint (`/admin/audit-log/verify-chain`)
- Optional IP redaction for privacy

**8. Docker Hardening**

- Read-only root filesystem (`read_only: true`)
- Dropped capabilities (`cap_drop: ALL`)
- Minimal capabilities (`NET_RAW`, `NET_BIND_SERVICE`, `CHOWN`, `SETUID`, `SETGID`)
- No-new-privileges security option
- Non-root user (`breaker:breaker` UID/GID 1000)
- Resource limits (2 CPU, 2GB RAM)

**9. Secrets Redaction**

- Global log filter strips Bearer tokens, passwords, secrets, API keys
- Regex-based filter on all log outputs (stdout, stderr, files)

---

## Deployment Models

### 1. Mono Container (Recommended)

**Single-container deployment** with all services embedded:

- **Image:** `ghcr.io/blkleg/circuitbreaker:mono-{version}`
- **Pros:** Simplest setup, fastest to deploy, ideal for homelabs
- **Cons:** All services share resource limits (CPU, RAM)

**Components:**

- PostgreSQL + pgbouncer
- NATS JetStream
- Redis
- FastAPI backend (2 Uvicorn workers)
- 4 background workers
- nginx

**Use Case:** Single-host homelab, Raspberry Pi, NAS devices

---

### 2. Split Compose Stack (Advanced)

**Multi-container deployment** (available in `docker/docker-compose.yml`):
- Separate containers for frontend, backend, workers, NATS, Postgres
- Each service scales independently (e.g., 3 discovery workers)
- Shared Docker networks: `cb_frontend`, `cb_backend`, `cb_workers`

**Pros:** Better resource isolation, easier horizontal scaling
**Cons:** More complex networking, higher memory overhead

**Use Case:** Production environments, high-load scenarios, multi-host Docker Swarm/Kubernetes (future)

---

## Performance Characteristics

**Benchmarks (tested on Raspberry Pi 4, 4GB RAM):**
- Cold boot to ready: **< 60 seconds**
- Scan 256-host subnet (nmap TCP): **< 2 minutes**
- Proxmox cluster import (100 VMs): **< 60 seconds**
- Topology render (1000 nodes): **< 3 seconds** (frontend, with layout caching)
- Telemetry poll (50 devices): **< 10 seconds** (parallel SNMP requests)

**Memory Footprint:**
- Idle state: **< 500 MB RAM** (entire mono container)
- Active scan (256 hosts): **< 800 MB RAM**
- 10k+ entities in DB: PostgreSQL uses **< 100 MB RAM** (with pgbouncer)

**Scalability:**
- **Horizontal:** Add more worker replicas (discovery, telemetry)
- **Vertical:** Increase `DB_POOL_SIZE` and Uvicorn workers
- **Database:** PostgreSQL scales to 100k+ entities (tested to 50k)

---

## Data Persistence

**Volume Mount:** `/data` (bind mount to host)

**Contents:**
```
/data/
├── postgres/                # PostgreSQL data directory
├── nats/                    # NATS JetStream state
├── redis/                   # Redis dump (disabled by default)
├── uploads/                 # User-uploaded files
│   ├── icons/              # Custom device icons
│   └── branding/           # Login backgrounds, logos
├── tls/                     # TLS certificates
│   ├── fullchain.pem       # Certificate chain
│   └── privkey.pem         # Private key
├── .env                     # Persisted vault key (CB_VAULT_KEY)
├── .redis_pass              # Optional Redis password
├── supervisord.log          # Supervisord master log
├── backend_api.log          # FastAPI stdout
├── backend_api_err.log      # FastAPI stderr
├── worker_*.log             # Worker logs (4 files)
├── nginx.log                # Nginx access log
├── nginx_err.log            # Nginx error log
├── pg.log                   # PostgreSQL stdout
├── pg_err.log               # PostgreSQL stderr
├── nats.log                 # NATS server log
├── redis.log                # Redis log
└── pgbouncer.log            # pgbouncer log
```

**Backup Strategy:**

1. **PostgreSQL dump:** `docker exec circuitbreaker pg_dump -U breaker circuitbreaker > backup.sql`
2. **Volume snapshot:** Backup entire `/data` directory (includes vault key, TLS certs)
3. **Restore:** Copy backup to new `/data` mount, start container

**Critical Files:**

- `/data/.env` — Vault encryption key (required to decrypt secrets)
- `/data/postgres/` — Database (all entities, users, config)
- `/data/tls/` — TLS certificates (HTTPS)

---

## Observability

### Logging

**Log Levels:**

- **DEBUG:** Verbose (request/response bodies, SQL queries)
- **INFO:** Normal operations (scan started, entity created)
- **WARNING:** Recoverable issues (timeout, retry)
- **ERROR:** Failures requiring attention (DB connection lost)

**Log Destinations:**

- **stdout/stderr:** Captured by supervisord, written to `/data/`
- **Docker logs:** `docker compose logs -f circuitbreaker`
- **CLI tool:** `cb logs [-f]`

**Log Redaction:**

- Sensitive fields stripped before output (passwords, tokens, secrets)
- Regex-based filter in logging middleware

---

### Metrics (Prometheus)

**Exposed Endpoint:** `/api/v1/metrics` (Prometheus-compatible)

**Key Metrics:**

- `http_requests_total` — Request count by method, path, status
- `http_request_duration_seconds` — Latency histogram
- `discovery_scans_total` — Scan count by status (success, failed)
- `telemetry_polls_total` — Telemetry poll count by integration
- `nats_messages_published` — Message bus throughput
- `redis_cache_hits_total` / `redis_cache_misses_total` — Cache performance
- `postgres_pool_size` — Connection pool usage

**Visualization:**

- Grafana dashboard (example: `docs/grafana-dashboard.json`)
- Prometheus scrape config: `scrape_interval: 15s`

---

### Health Checks

**Endpoint:** `/api/v1/health`

**Response:**
```json
{
  "status": "healthy",
  "version": "0.2.0",
  "database": "connected",
  "nats": "connected",
  "redis": "connected",
  "workers": {
    "discovery": "running",
    "webhook": "running",
    "notification": "running",
    "telemetry": "running"
  }
}
```

**Docker Healthcheck:**
- Interval: 10 seconds
- Timeout: 5 seconds
- Retries: 5
- Start period: 60 seconds

---

## Development Workflow

### Local Development (Compose)

```bash
# Clone repo
git clone https://github.com/BlkLeg/circuitbreaker.git
cd circuitbreaker

# Build and start all services
docker compose up -d

# Watch logs
docker compose logs -f circuitbreaker

# Run tests
docker compose exec circuitbreaker pytest /app/backend/tests/

# Rebuild after code changes
docker compose build --no-cache
docker compose up -d
```

---

### Frontend Development

```bash
cd apps/frontend

# Install dependencies
npm ci

# Start dev server (Vite HMR)
npm run start
# Access: http://localhost:5173

# Lint and format
npm run lint
npm run format

# Run tests
npm run test

# Build for production
npm run build
# Output: ./dist/
```

**API Proxy:**

- Vite dev server proxies `/api/*` to backend (configured in `vite.config.js`)
- WebSocket auto-reconnect for live reloading

---

### Backend Development

```bash
cd apps/backend

# Install dependencies (Poetry)
poetry install

# Run migrations
poetry run alembic upgrade head

# Start FastAPI dev server (auto-reload)
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
poetry run pytest

# Lint and format
poetry run ruff check --fix .
poetry run ruff format .

# Type check
poetry run mypy src/
```

**Environment Variables:**

- Copy `docker/.env.example` to `apps/backend/.env`
- Required: `CB_DB_URL`, `CB_VAULT_KEY`, `CB_JWT_SECRET`, `NATS_AUTH_TOKEN`

---

## Build Pipeline

### Multi-Stage Docker Build

**Stages:**
1. **frontend-builder** (Node 20) — `npm ci && npm run build`
2. **backend-builder** (Python 3.12) — `pip install -r requirements.txt`
3. **runtime** (Python 3.12 slim) — copy artifacts + install system services

**Optimizations:**

- Dependency layers cached (changes to source don't invalidate deps)
- Python bytecode pre-compiled (`PYTHONOPTIMIZE=2`)
- Stripped debug symbols from `.so` files
- Removed docs, man pages, locale files

**Image Size:**

- Mono image: **~800 MB** (includes PostgreSQL, NATS, Redis, nginx)
- Backend-only: **~400 MB**
- Frontend-only: **~25 MB** (nginx + static assets)

---

### CI/CD (GitHub Actions)

**Workflows:**

1. **security.yml** — Bandit, Semgrep, Gitleaks, ESLint (security), Hadolint, Checkov, Trivy, npm audit
2. **test.yml** — pytest (backend), vitest (frontend)
3. **build.yml** — Multi-arch Docker build (amd64, arm64)
4. **publish.yml** — Push images to GHCR on tag push

**Multi-Arch Support:**

- **amd64:** Intel/AMD servers
- **arm64:** Raspberry Pi, Apple Silicon, ARM servers

**Tagging Strategy:**

- `mono-latest` — latest mono image
- `mono-v0.2.0` — tagged release (semantic versioning)
- `backend-latest`, `frontend-latest` — split images

---

## API Design

### RESTful Conventions

**Base URL:** `/api/v1/`

**Authentication:** JWT via HttpOnly cookie (`cb_session`)

**CSRF Protection:** `X-CSRF-Token` header on all mutating requests

**Response Format:**
```json
{
  "data": { ... },
  "meta": {
    "total": 100,
    "page": 1,
    "per_page": 20
  }
}
```

**Error Format:**
```json
{
  "detail": "Entity not found",
  "error_code": "ENTITY_NOT_FOUND",
  "status_code": 404
}
```

---

### Key Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/auth/login` | Authenticate user, set session cookie |
| `POST` | `/auth/logout` | Invalidate session |
| `GET` | `/entities` | List all entities (paginated) |
| `POST` | `/entities` | Create entity |
| `GET` | `/entities/{id}` | Get entity by ID |
| `PATCH` | `/entities/{id}` | Update entity |
| `DELETE` | `/entities/{id}` | Delete entity |
| `POST` | `/discovery/scans` | Launch discovery scan |
| `GET` | `/discovery/scans/{id}` | Get scan results |
| `GET` | `/discovery/stream` | WebSocket — live scan progress |
| `GET` | `/telemetry/{entity_id}` | Get telemetry history |
| `GET` | `/telemetry/stream` | WebSocket — live telemetry updates |
| `GET` | `/topology` | Get full topology graph (nodes + edges) |
| `PATCH` | `/topology/positions` | Bulk-update node positions |
| `POST` | `/integrations/proxmox/import` | Import Proxmox cluster |
| `GET` | `/admin/audit-log` | Get audit log (admin only) |
| `GET` | `/health` | Health check endpoint |

**OpenAPI Docs:** `/docs` (Swagger UI)

---

## Future Architecture Improvements

### Planned Enhancements (Roadmap)

**v0.3.0:**

- **VLAN support** — layer 2 topology with VLAN tagging
- **Mobile app** — React Native (iOS/Android)
- **GraphQL API** — alternative to REST for complex queries

**v0.4.0:**

- **Kubernetes Operator** — native K8s cluster discovery
- **Distributed tracing** — OpenTelemetry integration
- **Event sourcing** — CQRS pattern for audit log

**v1.0.0:**

- **Multi-tenancy** — organization/workspace isolation
- **High availability** — PostgreSQL replication, multi-instance backend
- **Plugin system** — custom integrations without forking

---

## Conclusion

Circuit Breaker's architecture balances **simplicity** (single-container deployment) with **scalability** (microservices-ready design). The tech stack prioritizes modern, security-first tools (FastAPI, PostgreSQL, NATS, React) while maintaining low resource overhead for homelab use.

**Key Architectural Principles:**

1. **Security-first** — defense-in-depth, encryption, RBAC, audit logging
2. **Async-native** — all I/O is non-blocking (backend, workers, WebSockets)
3. **Observable** — structured logs, Prometheus metrics, health checks
4. **Testable** — service layer isolation, dependency injection, unit/integration tests
5. **Maintainable** — typed code (TypeScript, Pydantic), linted, documented

For more details, see:
- [User Guide](https://blkleg.github.io/CircuitBreaker)
- [API Documentation](/docs)
- [Security Hardening](docs/deployment-security.md)
- [Discovery Guide](docs/discovery.md)
