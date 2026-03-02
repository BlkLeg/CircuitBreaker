# CLAUDE.md

This file provides guidance to Claude (and any AI coding agent) working on
Circuit Breaker. Read this before writing a single line of code.

---

## What Is Circuit Breaker

Circuit Breaker is a self-hosted homelab visualization and topology management
platform. It maps hardware, services, networks, clusters, and racks into an
interactive topology. It runs entirely in Docker with SQLite — no external
databases, no Redis, no cloud dependency.

- **GitHub**: <https://github.com/BlkLeg/circuitbreaker>
- **Docker**: `ghcr.io/blkleg/circuitbreaker`
- **Install**: `curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash`
- **Target users**: Homelab enthusiasts, self-hosters, small IT teams.

---

## Tech Stack

### Backend

- Python 3.12, FastAPI, Uvicorn
- SQLAlchemy ORM — SQLite at `/data/app.db`
- Alembic-style manual migrations (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`)
- APScheduler (background workers, v0.2.0+)
- JWT auth via PyJWT, Fernet encryption for credential vault
- pysnmp, pyipmi, httpx for telemetry and discovery

### Frontend

- Vite + React — **`.jsx` for components, `.js` for everything else**
- **No TypeScript** — the entire frontend is plain JavaScript
- Tailwind CSS, Lucide icons
- Cytoscape.js (topology map), React Three Fiber / Three.js (3D rack)
- `@dnd-kit/core` for drag-and-drop (rack editor)

### Infrastructure

- Docker — multi-arch: `linux/amd64`, `linux/arm64`, `linux/arm/v7`
- Multi-stage builds, Alpine runtime, non-root user `breaker:1000`
- Read-only rootfs — only `/data` is writable
- GitHub Actions CI/CD, Makefile build automation

---

## Core Principles — Never Violate These

### 1. Freeform First

Users can always type any value into any name/model/vendor field and save it.
Library lookups and catalog autocomplete **accelerate** the experience — they
never gate it. If a lookup returns nothing, the user's typed value is always
accepted as-is.

### 2. Simple First

Every feature must be usable by someone who just wants to add a device and
draw some lines. Advanced features (telemetry, SNMP, 3D rack, integrations)
are opt-in and progressively disclosed. Do not surface complexity on the
default path.

### 3. Docker First

The app runs in a single container. No host dependencies. SQLite lives in a
named volume at `/data/app.db`. Never require the user to install Python,
Node, or any other runtime on the host.

### 4. Non-Root Always

The container runs as `breaker:1000`. The root filesystem is read-only. Only
`/data` is writable. Do not revert this for any reason. If a feature needs
write access, it goes to `/data`.

### 5. No Placeholders

Every code block you write is complete and production-ready. No `TODO`, no
`pass`, no `...`, no `raise NotImplementedError`. If you need more information,
ask before writing incomplete code.

### 6. Backward Compatible

Existing data must never be lost during upgrades. All DB changes use
`ALTER TABLE ... ADD COLUMN` with safe defaults. **Never `DROP` a column.**
Never break existing API contracts without a versioned replacement.

---

## What You Must Never Do

| Never | Instead |
| --- | --- |
| Write `TODO: implement this` | Ask for clarification first |
| Hardcode IPs, passwords, or secrets | Use env vars or the credential vault |
| Use root user in container | Use `breaker:1000` |
| Write to anywhere outside `/data` | Mount volume at `/data`, write there |
| Drop or rename DB columns | ADD new columns with safe defaults |
| Break existing API endpoints | Version or extend without removing |
| Use wildcard imports | Explicit imports only |
| Ignore CORS, auth, or rate limiting | All endpoints behind existing middleware |
| Use PostgreSQL, Redis, or external DBs | SQLite only for core data |
| Add a required env var without a default | Always provide a safe default |
| Assume the user has Node/Python on host | Docker-first, always |
| Use TypeScript in frontend files | `.jsx` / `.js` only |

---

## Project File Structure

```bash
circuitbreaker/
├── backend/
│   ├── app/
│   │   ├── main.py              # App entrypoint, lifespan, migrations
│   │   ├── api/                 # FastAPI routers (one file per entity)
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── schemas/             # Pydantic input/output schemas
│   │   ├── services/            # Business logic (pure functions/classes)
│   │   ├── integrations/        # iDRAC, iLO, APC, SNMP clients
│   │   ├── workers/             # APScheduler background tasks
│   │   ├── middleware/          # Auth, logging, security headers
│   │   └── data/                # vendor_catalog.json, known_ports.py
│   ├── pyproject.toml
│   └── poetry.lock
├── frontend/
│   ├── src/
│   │   ├── components/          # React components (.jsx)
│   │   ├── pages/               # Route-level pages (.jsx)
│   │   ├── hooks/               # Custom hooks (.js)
│   │   ├── api/                 # API client modules (.js) — never inline fetch
│   │   └── lib/                 # Utilities, constants (.js)
│   ├── package.json
│   └── vite.config.js
├── docker/
│   ├── backend.Dockerfile
│   └── docker-compose.yml
├── Dockerfile
├── Makefile
├── install.sh
└── .github/workflows/
```

---

## Environment Variables

```bash
CB_PORT=8080              # Host port (default: 8080)
CB_VAULT_KEY=             # Fernet key for credential encryption
CB_AUTH_ENABLED=true      # Set after OOBE bootstrap
CB_API_TOKEN=             # Optional machine-to-machine token
```

All env vars must have safe defaults. Never make a new var required without
a fallback.

---

## Database Conventions

- **SQLite only** at `/data/app.db` via SQLAlchemy ORM.
- Migrations are manual `ALTER TABLE` guards run at startup in `main.py`.
- Pattern: `ALTER TABLE foo ADD COLUMN IF NOT EXISTS bar TEXT DEFAULT ''`
- New tables: `CREATE TABLE IF NOT EXISTS`
- **Never** use Alembic auto-migrations, never `DROP COLUMN`, never rename.
- Every model needs `created_at` and `updated_at` timestamps.
- Foreign keys use `ON DELETE CASCADE` or `ON DELETE SET NULL` — choose
  deliberately and document which in a comment.

---

## API Conventions

- **Base path**: `/api/v1/`
- **Auth**: Bearer JWT in `Authorization` header
- **Response format**: JSON, `snake_case` keys
- **Errors**: `{ "detail": "message" }` with standard HTTP status codes
- **Health**: `GET /api/v1/health` → `{ "status": "ok", "version": "..." }`
- No business logic in route handlers — all logic lives in service layer.
- Secrets are never logged. Passwords are always hashed before DB write.
- DB sessions always closed via `Depends(get_db)`.
- Connection timeouts on all external calls — **max 5 seconds**.

### Standard HTTP Codes

- `200` OK, `201` Created, `204` No Content
- `400` Validation error, `401` Unauthenticated, `403` Forbidden
- `404` Not found, `409` Conflict, `422` Unprocessable entity
- `500` Server error — should never expose stack traces to clients

---

## Frontend Conventions

- **No TypeScript** — `.jsx` for React components, `.js` for everything else.
- All API calls live in `src/api/` — never inline `fetch()` in components.
- Use the shared `client` instance from `src/lib/api.js` for all requests.
- No hardcoded URLs — use the `API_BASE` constant.
- Loading and error states are always handled — no component assumes success.
- Forms validate on **blur AND on submit**.
- Components use `React.memo` where renders are expensive (map nodes, rack
  components, 3D models).
- `useFrame` animations in R3F are always capped — document the fps target
  in a comment above the hook.

---

## Data Model Quick Reference

### Node Types (topology map)

`hardware` | `service` | `network` | `compute` | `storage` | `cluster`
| `external` | `misc`

### Hardware Roles

`server` | `switch` | `router` | `firewall` | `access_point` | `ups`
| `pdu` | `nas` | `sbc` | `hypervisor` | `compute`

### Relation Types (edges)

`on_network` | `hosts` | `runs` | `connects_to` | `cluster_member`
| `backs_up` | `monitors`

### Key Tables

`hardware`, `services`, `networks`, `clusters`, `external_nodes`,
`app_settings`, `users`, `logs`, `racks`, `rack_placements`,
`discovery_jobs`, `live_metrics`, `integration_configs`

---

## Branch Strategy

| Branch | Purpose |
| --- | --- |
| `main` | Stable — release tags live here |
| `dev` | Feature integration branch |
| `feature/*` | Isolated feature branches |
| `hotfix/*` | Urgent fixes — merge to both `main` and `dev` |

---

## Versioning Reference

| Version | Status | Scope |
| --- | --- | --- |
| v0.1.0-beta | Shipped | Core CRUD, topology, rack, OOBE, auth, Docker |
| v0.1.2 | Active | Vendor catalog, telemetry, 3D rack v2, new node types |
| v0.2.0 | Planned | Auto-discovery, live telemetry, Proxmox/TrueNAS/UniFi |
| v0.3.0 | Planned | VLANs, WireGuard, mobile HUD |
| v1.0 | Planned | RBAC, SSO, multi-user, integration marketplace |

**Only build what is scoped to the current phase.** Do not pre-build v0.2.0
features while working on v0.1.2.

---

## How to Approach a Feature Request

Follow this sequence every time:

1. **Identify the phase** — which version does this belong to?
2. **Check dependencies** — DB migration needed? New Python libs? New env
   vars? Docker changes?
3. **Design data flow** — backend model → schema → service → API → frontend.
4. **Write backend first** — model, migration guard, service, API endpoint.
5. **Write frontend second** — API client module, component, page integration.
6. **Write Docker/config changes** — Dockerfile layers, env var docs,
   `docker-compose.yml`.
7. **State exit criteria** — list exactly what must be true for the feature
   to be considered complete.

---

## Output Format

### Feature Implementation

## Overview

2–3 sentences: what you're building and why.

## Backend Implementation

- Models / Migrations
- Schemas
- Services
- API endpoints

## Frontend Implementation

- API client (`src/api/`)
- Components
- Page integration

## Docker / Config

- Dockerfile additions
- New env vars
- docker-compose.yml changes

## Exit Criteria

- [ ] Testable condition 1
- [ ] Testable condition 2

### Bug Fix

```text
## Root Cause
Exact explanation of why the bug occurs.

## Fix
Minimal code change — do not refactor unrelated code.

## Verification
Steps to confirm the fix works.
```

### Architecture / Planning

## Recommendation

Clear, opinionated answer.

## Rationale

Why this approach over alternatives.

## Trade-offs

What you give up with this choice.

## Implementation Steps

Ordered list.

---

## Telemetry Integration Rules

When writing any integration client (iDRAC, iLO, SNMP, REST API):

- Always set a connection timeout — **max 5 seconds**.
- Always return a clean error dict on failure, never raise to the caller:
  
  ```python
  return {"error": str(e), "status": "unknown"}
  ```

- Normalize all raw vendor data into the standard telemetry shape:

  ```python
  {
    "cpu_temp": float | None,
    "fan_rpm": float | None,
    "psu1_load_w": float | None,
    "status": "healthy" | "degraded" | "critical" | "unknown"
  }
  ```

- Credentials are always encrypted via `CredentialVault` before DB storage.
- Poll intervals are per-device configurable — default 60 seconds.
- Freeform/unsupported devices always get `status: unknown` — never an error
  page.

---

## When In Doubt

Ask **exactly one clarifying question**. Do not ask multiple questions at
once. Do not make assumptions that could break existing functionality. Do not
refactor code outside the scope of the current task. Do not change the visual
design unless explicitly asked.

**The north star**: *"I added my Proxmox cluster and it auto-mapped everything
in 2 minutes — and I could still add my custom franken-server with one
free-text field."*
