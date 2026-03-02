# AGENTS.md

This file is the authoritative guide for any AI coding agent working on
Circuit Breaker. It is discovered automatically by OpenAI Codex, Cursor,
Windsurf, Kilo Code, Aider, and all tools following the Agent Rules standard.

**Scope**: This file applies to the entire repository. Nested `AGENTS.md`
files in subdirectories take precedence for their scope. Direct prompt
instructions from the developer override everything here.

**Rule**: If this file includes programmatic checks, you MUST run all of them
after every code change and make a best effort to confirm they pass — even
for changes that appear simple or documentation-only.

---

## Project Identity

Circuit Breaker is a self-hosted homelab visualization and topology management
platform. It maps hardware, services, networks, clusters, and racks into an
interactive topology. Single container, SQLite, zero cloud dependency.

- **GitHub**: <https://github.com/BlkLeg/circuitbreaker>
- **Docker**: `ghcr.io/blkleg/circuitbreaker`
- **Install**: `curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash`

---

## Tech Stack — Know Before You Touch Anything

### Backend

- Python 3.12, FastAPI, Uvicorn, SQLAlchemy ORM
- SQLite at `/data/app.db` — no external databases, ever
- Manual `ALTER TABLE` migration guards in `main.py` — no Alembic
- APScheduler for background workers (v0.2.0+)
- PyJWT for auth, `cryptography.fernet` for credential vault
- pysnmp, pyipmi, httpx for telemetry / discovery

### Frontend

- Vite + React — **`.jsx` for all components, `.js` for everything else**
- **Zero TypeScript** in the frontend — do not introduce it
- Tailwind CSS, Lucide icons
- Cytoscape.js (topology map), React Three Fiber / Three.js (3D rack)
- `@dnd-kit/core` for drag-and-drop (rack editor)

### Container

- Multi-arch Docker: `linux/amd64`, `linux/arm64`, `linux/arm/v7`
- Runtime user: `breaker:1000` — non-root, always
- Read-only rootfs — only `/data` is writable
- Multi-stage build, Alpine runtime

---

## Build Commands

```bash
# ── Docker (primary artifact) ──────────────────────────────────────────────
make build                  # Build multi-arch Docker image
make run                    # Run local container on CB_PORT (default 8080)
make stop                   # Stop and remove container
make logs                   # Tail container logs

# ── Backend (local dev, no Docker) ────────────────────────────────────────
cd backend
poetry install              # Install Python dependencies
poetry run uvicorn app.main:app --reload --port 8000

# ── Frontend (local dev) ──────────────────────────────────────────────────
cd frontend
npm ci                      # Clean install (use ci, not install)
npm run dev                 # Vite dev server on :5173
npm run build               # Production build to frontend/dist/
npm run preview             # Preview production build
```

---

## Test Commands

```bash
# ── Backend tests ─────────────────────────────────────────────────────────
cd backend
poetry run pytest                          # Full test suite
poetry run pytest -x                       # Stop on first failure
poetry run pytest tests/test_hardware.py   # Single file
poetry run pytest -k "test_overlap"        # Filter by name
poetry run pytest --tb=short               # Compact tracebacks

# ── Frontend tests ────────────────────────────────────────────────────────
cd frontend
npm test                    # Run Vitest (watch mode)
npm run test:run            # Run once, no watch (CI mode)
npm run test:coverage       # Coverage report

# ── Type / lint checks ────────────────────────────────────────────────────
cd backend
poetry run ruff check .     # Linter
poetry run ruff format .    # Formatter

cd frontend
npm run lint                # ESLint

# ── Full pre-commit check (run this before declaring any task done) ────────
make check                  # Runs: ruff + pytest + npm test:run
```

### Programmatic Checks — You Must Run These

After **any** code change, run and confirm passing:

```bash
# Backend — must pass with zero failures
cd backend && poetry run pytest -x --tb=short

# Frontend — must pass with zero failures  
cd frontend && npm run test:run

# Linting — must have zero errors (warnings acceptable)
cd backend && poetry run ruff check .
cd frontend && npm run lint
```

Do not declare a task complete until all four commands exit cleanly.

---

## Repository Layout

```bash
circuitbreaker/
├── backend/
│   ├── app/
│   │   ├── main.py              # Entrypoint, lifespan, migration guards
│   │   ├── api/                 # FastAPI routers — one file per entity
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── schemas/             # Pydantic v2 input/output schemas
│   │   ├── services/            # Business logic — no logic in routers
│   │   ├── integrations/        # iDRAC, iLO, SNMP, Redfish clients
│   │   ├── workers/             # APScheduler background tasks
│   │   ├── middleware/          # Auth, logging, security headers
│   │   └── data/                # vendor_catalog.json, known_ports.py
│   ├── tests/
│   ├── pyproject.toml
│   └── poetry.lock
├── frontend/
│   ├── src/
│   │   ├── components/          # React components (.jsx)
│   │   ├── pages/               # Route pages (.jsx)
│   │   ├── hooks/               # Custom hooks (.js)
│   │   ├── api/                 # API clients (.js) — no inline fetch
│   │   └── lib/                 # Utilities, constants (.js)
│   ├── src/__tests__/           # Vitest test files
│   ├── package.json
│   └── vite.config.js
├── docker/
│   ├── backend.Dockerfile
│   └── docker-compose.yml
├── Dockerfile
├── Makefile
├── install.sh
├── AGENTS.md                    # ← this file
├── CLAUDE.md
└── GEMINI.md
```

---

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `CB_PORT` | `8080` | Host port |
| `CB_VAULT_KEY` | *(generated)* | Fernet key for credential encryption |
| `CB_AUTH_ENABLED` | `true` | Enabled after OOBE bootstrap |
| `CB_API_TOKEN` | *(none)* | Optional static machine-to-machine token |

All env vars must have safe defaults. Never add a required var without a
fallback.

---

## Coding Conventions

### Python (backend)

- `snake_case` everywhere — functions, variables, file names
- Type hints on **all** function signatures
- Docstrings on all classes and non-obvious functions
- No business logic in route handlers — service layer only
- DB sessions always closed via `Depends(get_db)`
- Secrets never logged; passwords always hashed before DB write
- External calls always have a **5-second timeout**
- Return `{"error": str(e), "status": "unknown"}` on integration failure —
  never raise to the caller

### JavaScript / React (frontend)

- `.jsx` for React components, `.js` for utilities, hooks, API clients
- **No TypeScript** — do not add `.ts` or `.tsx` files
- `PascalCase` for components, `camelCase` for variables and functions
- All API calls in `src/api/` — never inline `fetch()` in components
- No hardcoded URLs — use the `API_BASE` constant from `src/lib/api.js`
- Loading and error states always handled — no component assumes success
- Forms validate on **blur AND on submit**

### Database

- SQLite only via SQLAlchemy ORM
- Migrations: `ALTER TABLE foo ADD COLUMN IF NOT EXISTS bar TEXT DEFAULT ''`
- New tables: `CREATE TABLE IF NOT EXISTS`
- **Never** `DROP COLUMN`, never rename a column
- Every model needs `created_at` and `updated_at` timestamps
- Foreign keys: always specify `ON DELETE CASCADE` or `ON DELETE SET NULL`

### API

- Base path: `/api/v1/`
- Response format: JSON, `snake_case` keys
- Errors: `{ "detail": "message" }` with standard HTTP status codes
- No stack traces in client responses — catch at the API layer

---

## Hard Constraints

These are non-negotiable. Any violation must be flagged immediately.

1. **Freeform first**: users can always type any value into any field.
   Lookups accelerate — they never gate.
2. **Simple first**: advanced features are opt-in, progressively disclosed.
3. **Docker first**: single container, no host runtime dependencies.
4. **Non-root always**: `breaker:1000`, read-only rootfs, writes to `/data` only.
5. **No placeholders**: every code block is complete and production-ready.
6. **Backward compatible**: no dropped columns, no broken API contracts.
7. **No TypeScript**: frontend is `.jsx` / `.js` only.
8. **No external DB**: SQLite only for core data persistence.

---

## What You Must Never Do

```bash
NEVER                              → INSTEAD
─────────────────────────────────────────────────────────────────
Write TODO / pass / ...            → Ask one clarifying question
Hardcode secrets or IPs            → Use env vars / credential vault  
Use root in container              → Use breaker:1000
Write outside /data                → Mount /data, write there
DROP or rename a DB column         → ADD new column with safe default
Break an existing API endpoint     → Version or extend it
Use TypeScript in frontend         → .jsx / .js only
Use PostgreSQL, Redis              → SQLite only
Add required env var, no default   → Always provide a safe fallback
Refactor code outside task scope   → Stay focused, ask first
Pre-build a future-phase feature   → Scope to current version only
Log a secret or password           → Never. Not even at DEBUG level
```

---

## Versioning Scope

Only build what is scoped to the current phase. Do not pre-build features
from future versions.

| Version | Status | Scope |
| --- | --- | --- |
| v0.1.0-beta | Shipped | Core CRUD, topology, rack, OOBE, auth, Docker |
| v0.1.2 | Active | Vendor catalog, telemetry, 3D rack v2, new node types |
| v0.2.0 | Planned | Auto-discovery, live telemetry, Proxmox/TrueNAS/UniFi |
| v0.3.0 | Planned | VLANs, WireGuard, mobile HUD |
| v1.0 | Planned | RBAC, SSO, multi-user, integration marketplace |

---

## PR Message Instructions

When generating a pull request title and body, follow this format exactly:

```
<type>(<scope>): <short imperative summary under 72 chars>

## What
1–3 bullet points describing what changed.

## Why
1–2 sentences explaining why this change was needed.

## Testing
- [ ] Backend: `cd backend && poetry run pytest -x --tb=short` passes
- [ ] Frontend: `cd frontend && npm run test:run` passes
- [ ] Lint: `ruff check .` and `npm run lint` pass clean
- [ ] Exit criteria from task description verified

## Breaking Changes
None / <describe if any>
```

Allowed `<type>` values: `feat`, `fix`, `chore`, `docs`, `refactor`,
`test`, `perf`

Allowed `<scope>` values: `hardware`, `services`, `networks`, `rack`,
`topology`, `discovery`, `auth`, `docker`, `frontend`, `api`, `db`

---

## Task Completion Checklist

Before declaring any task complete, confirm every item:

- [ ] All new code is complete — no `TODO`, `pass`, `...`, or placeholder
- [ ] Backend tests pass: `cd backend && poetry run pytest -x --tb=short`
- [ ] Frontend tests pass: `cd frontend && npm run test:run`
- [ ] Ruff passes: `cd backend && poetry run ruff check .`
- [ ] ESLint passes: `cd frontend && npm run lint`
- [ ] No new TypeScript files introduced
- [ ] No DB columns dropped or renamed
- [ ] No secrets hardcoded or logged
- [ ] All external calls have a 5-second timeout
- [ ] Exit criteria listed in the task are verifiable and met
- [ ] PR message follows the template above

---

## When In Doubt

Ask **exactly one** clarifying question. Do not ask multiple at once.
Do not refactor code outside the current task scope.
Do not change visual design unless explicitly asked.

**The north star**: *"I added my Proxmox cluster and it auto-mapped
everything in 2 minutes — and I could still add my custom franken-server
with one free-text field."*
