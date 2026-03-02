# GEMINI.md

This file is loaded automatically by Gemini CLI and Gemini Code Assist agent
mode at every session. It provides persistent project context so you never
need to re-explain the stack. Read this entire file before writing any code.

> **Hierarchy note**: This is the project-root context file. It applies to
> all work within this repository. User-level preferences live in
> `~/.gemini/GEMINI.md` and are additive — this file takes precedence on
> project-specific rules.

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
- Manual `ALTER TABLE` migrations (no Alembic auto-migrate)
- APScheduler (background workers, v0.2.0+)
- JWT auth via PyJWT, Fernet encryption for credential vault
- pysnmp, pyipmi, httpx for telemetry and discovery

### Frontend

- Vite + React — **`.jsx` for components, `.js` for everything else**
- **No TypeScript anywhere in the frontend**
- Tailwind CSS, Lucide icons
- Cytoscape.js (topology map), React Three Fiber / Three.js (3D rack)
- `@dnd-kit/core` for drag-and-drop (rack editor)

### Infrastructure

- Docker multi-arch: `linux/amd64`, `linux/arm64`, `linux/arm/v7`
- Multi-stage builds, Alpine runtime, non-root user `breaker:1000`
- Read-only rootfs — only `/data` is writable
- GitHub Actions CI/CD, Makefile build automation

---

## Non-Negotiable Constraints

These rules are hard constraints. Do not deviate from them under any
circumstances, regardless of what a prompt asks.

1. **Freeform first** — users can always type any value into any field and
   save it. Library lookups accelerate — they never gate.
2. **Simple first** — advanced features are opt-in. Never surface complexity
   on the default path.
3. **Docker first** — single container, no host runtime dependencies. SQLite
   in a named volume at `/data/app.db`.
4. **Non-root always** — container runs as `breaker:1000`. Root filesystem is
   read-only. All writes go to `/data`.
5. **No placeholders** — every code block is complete and production-ready.
   No `TODO`, no `pass`, no `...`, no `raise NotImplementedError`.
6. **Backward compatible** — never `DROP` a column. Never break existing API
   contracts. All DB changes use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
   with safe defaults.
7. **No TypeScript** — frontend is `.jsx` / `.js` only.

---

## Project File Map

```Bash
circuitbreaker/
├── backend/
│   ├── app/
│   │   ├── main.py              # Entrypoint, lifespan, migration guards
│   │   ├── api/                 # FastAPI routers — one file per entity
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── schemas/             # Pydantic input/output schemas
│   │   ├── services/            # Business logic — pure functions/classes
│   │   ├── integrations/        # iDRAC, iLO, APC, SNMP, Redfish clients
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
│   │   ├── api/                 # API clients — never inline fetch (.js)
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
CB_AUTH_ENABLED=true      # Enabled after OOBE bootstrap
CB_API_TOKEN=             # Optional machine-to-machine static token
```

Every env var must have a safe default. Never add a required var without
a fallback.

---

## Database Rules

- SQLite only at `/data/app.db` via SQLAlchemy ORM.
- Migration guards run at startup in `main.py`:

  ```sql
  ALTER TABLE foo ADD COLUMN IF NOT EXISTS bar TEXT DEFAULT ''
  CREATE TABLE IF NOT EXISTS new_table (...)
  ```

- Every model needs `created_at` and `updated_at`.
- Foreign keys: use `ON DELETE CASCADE` or `ON DELETE SET NULL` deliberately,
  and document the choice with a comment.
- Never `DROP COLUMN`, never rename a column, never use Alembic auto-migrate.

---

## API Rules

- Base path: `/api/v1/`
- Auth: `Authorization: Bearer <jwt>` header
- Response format: JSON, `snake_case` keys
- Errors: `{ "detail": "message" }` with standard HTTP codes
- Health: `GET /api/v1/health` → `{ "status": "ok", "version": "..." }`
- No business logic in route handlers — all logic lives in service layer.
- Secrets are never logged. Passwords always hashed before DB write.
- DB sessions always closed via `Depends(get_db)`.
- External calls always have a **5-second timeout**.

---

## Frontend Implementation Rules

- **No TypeScript** — `.jsx` for React components, `.js` for utilities.
- All API calls in `src/api/` — never inline `fetch()` in components.
- Use shared `client` instance from `src/lib/api.js`.
- No hardcoded URLs — use the `API_BASE` constant.
- Loading and error states always handled — no component assumes success.
- Forms validate on **blur AND on submit**.
- `React.memo` on expensive render components (topology nodes, rack models).
- `useFrame` animations in R3F always capped — document fps target in a
  comment above the hook.

---

## Data Model Reference

### Node Types (topology)

`hardware` | `service` | `network` | `compute` | `storage` | `cluster`
| `external` | `misc`

### Hardware Roles

`server` | `switch` | `router` | `firewall` | `access_point` | `ups`
| `pdu` | `nas` | `sbc` | `hypervisor` | `compute`

### Edge Relation Types

`on_network` | `hosts` | `runs` | `connects_to` | `cluster_member`
| `backs_up` | `monitors`

### Key Tables

`hardware`, `services`, `networks`, `clusters`, `external_nodes`,
`app_settings`, `users`, `logs`, `racks`, `rack_placements`,
`discovery_jobs`, `live_metrics`, `integration_configs`

---

## Versioning Scope

| Version | Status | Scope |
| --- | --- | --- |
| v0.1.0-beta | Shipped | Core CRUD, topology, rack, OOBE, auth, Docker |
| v0.1.2 | Active | Vendor catalog, telemetry, 3D rack v2, new node types |
| v0.2.0 | Planned | Auto-discovery, live telemetry, Proxmox/TrueNAS/UniFi |
| v0.3.0 | Planned | VLANs, WireGuard, mobile HUD |
| v1.0 | Planned | RBAC, SSO, multi-user, integration marketplace |

**Only build what is scoped to the current phase. Do not pre-build future
phase features.**

---

## Workflow — Follow This Every Session

Gemini CLI operates in three phases. Complete each before advancing.

### Phase 1 — Perceive & Understand

1. Read this file in full.
2. Identify the phase scope (which version tag).
3. Inspect directly affected files before writing anything:
   use `@src/` references to load relevant paths into context.
4. Check dependencies: DB migration needed? New Python libs? New env vars?
   Docker changes? New frontend packages?
5. Resolve all ambiguities — ask **one** clarifying question if needed.
6. Establish a testable definition of "done" before proceeding.

### Phase 2 — Reason & Plan

1. Identify every file that will be created or modified.
2. Design data flow: model → schema → service → API → frontend.
3. Present the plan with rationale. **Do not write implementation code
   until the plan is confirmed.**

### Phase 3 — Implement

1. Work in the smallest possible increments.
2. Write backend first: model, migration guard, service, API endpoint.
3. Write frontend second: API client module, component, page integration.
4. Write Docker/config changes last: Dockerfile, env vars, compose.
5. State exit criteria — a bullet list of exactly what must be true for
   the feature to be considered complete.

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

- API client (src/api/)
- Components
- Page integration

## Docker / Config

- Dockerfile additions
- New env vars with defaults
- docker-compose.yml changes

## Exit Criteria

- [ ] Testable condition 1
- [ ] Testable condition 2

### Bug Fix

## Root Cause

Exact explanation of why the bug occurs.

## Fix

Minimal code change — do not refactor unrelated code.

## Verification

Steps to confirm the fix works.

### Architecture / Planning

## Recommendation

Clear, opinionated answer.

## Rationale

Why this over alternatives.

## Trade-offs

What you give up with this choice.

## Implementation Steps

Ordered list.

---

## Telemetry Client Rules

When writing any integration (iDRAC, iLO, SNMP, Redfish, REST):

- Timeout: **max 5 seconds** on every external call.
- Return a clean dict on failure — never raise to the caller:

  ```python
  return {"error": str(e), "status": "unknown"}
  ```

- Normalize all vendor data to the standard telemetry shape:

  ```python
  {
    "cpu_temp": float | None,
    "fan_rpm": float | None,
    "psu1_load_w": float | None,
    "status": "healthy" | "degraded" | "critical" | "unknown"
  }
  ```

- Credentials always encrypted via `CredentialVault` before DB storage.
- Poll intervals are per-device configurable — default 60 seconds.
- Unsupported devices always return `status: "unknown"` — never an error page.

---

## What You Must Never Do

| Never | Instead |
| --- | --- |
| Write `TODO: implement this` | Ask one clarifying question |
| Hardcode IPs, passwords, or secrets | Use env vars or credential vault |
| Use root user in container | Use `breaker:1000` |
| Write to anywhere outside `/data` | Mount volume at `/data`, write there |
| Drop or rename DB columns | ADD new columns with safe defaults |
| Break existing API endpoints | Version or extend, never remove |
| Use wildcard imports | Explicit imports only |
| Use TypeScript in the frontend | `.jsx` / `.js` only |
| Use PostgreSQL, Redis, or external DBs | SQLite only |
| Add a required env var without a default | Always provide a safe fallback |
| Refactor code outside the current task scope | Stay focused on the task |
| Change visual design unless explicitly asked | Ask first |
| Pre-build a future-phase feature | Scope strictly to the current version |

---

## Clarification Protocol

Ask **exactly one** clarifying question when needed. Do not ask multiple
questions. Do not make assumptions that could break existing functionality.

**The north star**: *"I added my Proxmox cluster and it auto-mapped
everything in 2 minutes — and I could still add my custom franken-server
with one free-text field."*
