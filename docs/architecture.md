# Architecture (for contributors)

This page is for someone reading the code for the first time. It describes the
tree as it stands, names the parts that do not yet match the pattern they are
supposed to follow, and points at the records that are authoritative for
everything it does not cover.

**Every count and line number below was measured against commit `fef1a689` on
2026-09-08** with `git show HEAD:<path> | wc -l` and `git ls-tree`. If a number
here disagrees with your checkout, your checkout is right and this page is
stale — please correct it in the same PR that moves the code.

For a visual walkthrough of the same system — nine annotated diagrams covering
deployment, the request lifecycle, telemetry, real-time fan-out, monitoring, the
Go agent, discovery and the map engine — see
[Architecture Walkthrough](architecture.html). That page is the picture; this
one is the map of the source tree.

---

## 1. Process topology

Circuit Breaker ships as a **modular monolith plus an independent Go agent**.
The canonical deployment is the mono container, whose process list is defined in
`docker/supervisord.mono.conf`. Reading that file is the fastest way to see what
actually runs.

| Process | What it is | Listens on |
|---|---|---|
| `postgres` | Embedded PostgreSQL 15. Skipped when `CB_DB_URL` points at an external host. | 5432 (loopback) |
| `pgbouncer` | Transaction-mode connection pool in front of Postgres. Only starts in embedded-DB mode. | 6432 (loopback) |
| `nats` | NATS with JetStream — the internal event bus. Refuses to start without `NATS_AUTH_TOKEN`. | 4222 (loopback) |
| `redis` | Cache **and** the cross-process pub/sub that fans real-time events out to WebSocket clients. Capped at 128 MB, `allkeys-lru`, no persistence. | 6379 (loopback) |
| `backend-api` | The FastAPI app under Uvicorn, `--workers 2`, `CB_TOPOLOGY_MODE=api`. | 127.0.0.1:8000 |
| `worker-*` | Seven worker programs, eight processes: `discovery`, `notification`, `telemetry`, `integration`, `monitor_scheduler`, `monitor_poll` (×2), `monitor_probe_dispatch`. All are `python -m app.workers.main --type=<name>` with `CB_TOPOLOGY_MODE=worker`. | — |
| `nginx` | Serves the built SPA from `/app/frontend/dist`, proxies `/api/` and the streams to `http://127.0.0.1:8000`. | 8080 (redirect + ACME + health), 8443 (TLS) |

Two details that surprise people:

- **supervisord runs as root on purpose.** It has to, so the discovery worker's
  launcher can grant ambient `CAP_NET_RAW` via `setpriv` for nmap. Every program
  drops to `breaker` explicitly — through `user=breaker` or through its `setpriv`
  launcher. Nothing application-facing runs as root.
- **Migrations and the runtime take different DB paths.** The entrypoint runs
  Alembic against Postgres directly on 5432; the running backend routes through
  pgbouncer on 6432 (`docker/entrypoint-mono.sh`, `docker/pgbouncer.ini`).

### Who talks to whom

- Browser → **nginx** (8443) → **backend-api** (8000). nginx has dedicated
  `location` blocks with `Upgrade` headers for each WebSocket stream
  (`/api/v1/{discovery,topology,telemetry,monitors,agents}/stream`,
  `/api/v1/agents/{enroll,link}`) and an explicit non-upgrading block for the SSE
  endpoint `/api/v1/events/stream`.
- **backend-api** and every **worker** → Postgres (via pgbouncer), Redis, NATS.
- **Workers → NATS → backend-api.** Subjects are constants in
  `app/core/subjects.py`, in the shape `<domain>.<entity>.<event>`. Never
  hard-code a subject string. `app/startup/messaging.py` subscribes the
  NATS→WebSocket bridges on the API process at startup.
- **Redis pub/sub is the primary cross-process fan-out** for real-time push;
  the NATS bridges are a secondary path for events published on the bus. A
  single-process deployment with no NATS is supported — the bridge subscribes
  nothing and Redis carries everything.
- **`cb-agent`** (Go, `apps/agent/`, 116 `.go` files, 57 of them non-test) runs
  on a *remote* host, not in this container. It dials two WebSockets against the
  server:
  `/api/v1/agents/enroll` for a Noise IK handshake at enrolment, then
  `/api/v1/agents/link` as its persistent link (`apps/agent/internal/enroll/`,
  `apps/agent/internal/link/`).

### The topology mode is the thing that decides ownership

`app/core/topology.py` is the single source of truth for which process owns which
background loop. Three modes:

- `mono` — one process; the API also runs every background owner. The default,
  and what a single-node native install does.
- `api` — HTTP only; background functions belong to dedicated worker processes.
- `worker` — a worker process; serves no HTTP.

The `JOB_OWNERS` table in that module classifies every loop and job. A
`CB_TOPOLOGY_MODE` that contradicts the legacy `CB_RUN_INPROCESS_WORKERS` is a
startup error, not a coin toss.

### Locally

`make dev` starts the same shape without Docker for the app: deps
(Postgres/Redis/NATS) in containers via `docker-compose.deps.yml`, then the
backend natively on :8000 with `CB_TOPOLOGY_MODE=api`, the monitor scheduler and
poll worker as separate `worker`-mode processes, and Vite on :5173. See
`make dev`, `make deps-up`, `make backend`, `make monitor-workers` in the
`Makefile`.

---

## 2. The request path

### Backend

```
apps/backend/src/app/
  main.py         358 lines — app construction, middleware stack, lifespan
  api/routing.py  the route table: 68 include_router() calls, nothing else
  api/*.py        61 route modules — thin: parse, authorize, delegate, shape
  services/*.py   96 modules + backup/ intelligence/ monitoring/ — the logic
  db/models/      21 modules by bounded context
```

`main.py` builds the app and owns the lifespan; it does **not** know the route
list. `api/routing.py` is deliberately a table and not logic, so adding an
endpoint never touches the startup sequence. `api/static_spa.py` claims
`GET /{full_path:path}` and is therefore registered last, by `main` — after
`include_all_routers()` returns.

Startup work lives in `app/startup/` (`bootstrap.py`, `jobs.py`, `messaging.py`,
`paths.py`, `scheduler.py`, `schema.py`, `seed.py`, `workers.py`), not in
`main.py`.

**`db/models/` is a package, not a module.** It was one 3,030-line file holding
86 classes; it is now 21 modules split by bounded context — `agents`, `audit`,
`auth`, `common`, `compute`, `credentials`, `discovery`, `external`, `hardware`,
`integrations`, `intel`, `kb`, `monitors`, `networks`, `notifications`,
`privacy`, `services`, `settings`, `telemetry`, `tenants`, `topology` — plus
`_shared.py`. `from app.db.models import Hardware` still works and is still the
right import: `__init__.py` re-exports everything, and importing the package
imports every model module, which is **not optional**. `migrations/env.py` reads
`Base.metadata` through it and the test fixtures build the schema with
`create_all`, so a model that is defined but never imported is a table that
silently does not exist in either place.

Sessions come from `Depends(get_db)`. Errors go out as `{"detail": "..."}`.
JSON is snake_case.

### Frontend

```
apps/frontend/src/
  pages/          32 route-level components + oobe/ and settings/ subtrees
  features/map/   49 files — the one feature-folder so far
  components/     shared and domain components
  hooks/  lib/  utils/  context/  providers/  theme/
  api/            13 modules; client.jsx is the axios instance
```

**Calls to this application's API go through the axios client in
`src/api/client.jsx`** — 135 modules import it, 110 of them outside the test
suite — and never through an inline `fetch`. That client owns request IDs, auth,
CSRF, retries, the diagnostics ring buffer and the server-clock record; a bare
`fetch` silently opts out of all of it. The other twelve files in `src/api/` are
per-domain wrappers around that one client; they do not create their own.

Six call sites across four files in `src/` do use a bare `fetch`, and all six
sit outside that rule rather than being exceptions to it. Four reach third-party
or other-origin URLs (`components/HeaderWidgets.jsx` calls Open-Meteo for
geocoding and weather; `pages/oobe/useOOBEWizard.js` calls Open-Meteo geocoding
and downloads the Caddy root CA from a different origin). One loads a static
asset (`components/common/LoadingScreen.jsx`). One is the liveness poll in
`hooks/useServerLifecycle.js`, which probes `/api/v1/health` deliberately
outside the client's interceptors because it has to work while the server is
down. Anything that is a normal API call belongs in `src/api/`.

`features/map/` is the pattern to follow for anything large:
`MapWorkspace.jsx` composes 25 `components/`, 15 `hooks/`, 7 `model/` and one
`renderers/` file, and `pages/MapPage.jsx` is a **46-line route shell** that
resolves the active map and mounts the workspace inside its providers. New
subsystems of that size belong in `features/`, not in `pages/`.

Render loading and error states — always. `MapPage.jsx` is a small, complete
example of both.

---

## 3. "Routes thin, services hold logic" is a target

It is the rule for new code, and it is **not** a description of the whole tree
today. These files are the largest that remain, and they are known debt rather
than examples to copy. If you are adding to one of them, prefer extracting a
service (or, on the frontend, a `features/` folder) over making it longer.

**Route modules that carry logic they should not:**

| File | Lines |
|---|---|
| `apps/backend/src/app/api/agents.py` | 2,179 |
| `apps/backend/src/app/api/discovery.py` | 1,465 |
| `apps/backend/src/app/api/ws_agents.py` | 1,440 |
| `apps/backend/src/app/api/auth.py` | 1,347 |
| `apps/backend/src/app/api/graph.py` | 1,233 |
| `apps/backend/src/app/api/auth_oauth.py` | 1,113 |

**Services large enough to be worth splitting:**

| File | Lines |
|---|---|
| `apps/backend/src/app/services/agent_registry.py` | 1,972 |
| `apps/backend/src/app/services/discovery_service.py` | 1,798 |
| `apps/backend/src/app/services/agent_discovery.py` | 1,782 |
| `apps/backend/src/app/services/discovery_fingerprint.py` | 1,543 |
| `apps/backend/src/app/services/auth_service.py` | 1,321 |
| `apps/backend/src/app/services/monitor_service.py` | 1,212 |
| `apps/backend/src/app/services/proxmox_discovery.py` | 1,113 |

`apps/backend/src/app/cli.py` (1,568) is neither a route nor a service; it is the
`cb` command surface and is large for its own reasons.

**Frontend components over a thousand lines:**

| File | Lines |
|---|---|
| `apps/frontend/src/pages/AdminUsersPage.jsx` | 1,535 |
| `apps/frontend/src/features/map/MapWorkspace.jsx` | 1,470 |
| `apps/frontend/src/pages/LogsPage.jsx` | 1,453 |
| `apps/frontend/src/components/discovery/ReviewQueuePanel.jsx` | 1,388 |
| `apps/frontend/src/components/auth/ProfileModal.jsx` | 1,130 |
| `apps/frontend/src/features/map/components/Sidebar.jsx` | 1,120 |
| `apps/frontend/src/components/agents/AgentTelemetryTab.jsx` | 1,083 |

`MapWorkspace.jsx` is on this list even though `features/map/` is otherwise the
model to copy: the composition root itself is still too big.

Some of the layering is enforced rather than merely intended.
`tests/build/test_phase3_boundary_ratchets.py` freezes measured counts of
`core → services` imports, raw session operations in routes, and silent
exception handlers — numbers that may only go **down**. If one fails, lowering
the constant in the same commit is the correct response; raising it is not.

---

## 4. Tests

- `apps/backend/tests/` — the backend suite, with `api/`, `services/`,
  `discovery/`, `integration/`, `workers/`, `core/`, `unit/` and more.
- `apps/frontend/src/__tests__/` — 187 Vitest test files plus their shared harnesses.
- `tests/build/` — repo-policy suites. These are file-shape and contract tests,
  not behaviour tests, and they couple files you would not expect: the skip
  register, the record indexes (`plans/README.md`, `SECURITY_REPORTS/README.md`),
  the endpoint policy inventory, the CSP and font guards. Run
  `.venv/bin/python -m pytest tests/build -q --no-cov` (~13s) before you push;
  it is what catches a governance file you did not know your change touched.
- `tests/integration/`, `tests/fixtures/` — cross-cutting integration work.

Large test files are split by behaviour rather than by the module under test —
`apps/backend/tests/discovery/` (eight scenario modules plus `helpers.py` and
`conftest.py`) and the eight `agent-detail-*.test.jsx` files with their shared
`agentDetailHarness.jsx` are the current examples. Follow that shape.

`make lint` runs ruff, mypy and eslint. `make verify` is the pre-push gate and
is what `.husky/pre-push` runs. Never lower the coverage gate to make a build
green.

---

## 5. Where to look next

- **`CLAUDE.md`** — the conventions. Naming, typing, error handling, the
  freeform-first product rule, air-gap, backward compatibility. Read it before
  your first PR.
- **`CONTRIBUTING.md`** — local setup, including the Go toolchain and
  `govulncheck` that `make verify` needs and `make install` does not bootstrap.
- **`specs/1.0.0/release-control/`** — the requirement ledger
  (`requirement-ledger.csv`) and its companions: the skip register, exception
  register, risk register, release blockers, owner map. **This is the status
  source of truth.** A plan is intent; the ledger is what shipped.
- **`plans/README.md`** — the index of historical implementation plans, with a
  status column and a four-word status vocabulary (Complete / Active /
  Superseded / Reference). Several plans there describe finished work in the
  present tense; that is normal for a plan, which is exactly why the index
  carries a status.
- **`docs/evidence/`** — dated measurement and audit snapshots, linked from the
  pages that cite them.
- **`docs/adr/`** — decision records.
- The four skills under `.claude/skills/` — `cb-code-quality`,
  `cb-security-hardening`, `cb-realtime-api`, `cb-build-test` — carry the detail
  behind `CLAUDE.md`.

---

## 6. What on this site is *not* current architecture

Dated records describe the tree on the day they were written and were not
updated afterwards. Do not read them as a description of today:

- `docs/evidence/2026-08-30-architecture-assessment.md` — a static review at
  `dev` @ `52364918`. It says so in its own opening lines. Its structural claims
  predate the `main.py`, `db/models/` and map splits.
- `docs/evidence/2026-08-30-production-readiness-route.md` — the remediation
  route derived from that assessment. Same caveat; its phase status is tracked
  in the requirement ledger, not in the document.
- Everything under `docs/design/` — designs and implementation plans. Each
  carries a status banner in its first lines; read the banner before you trust
  the body.
- `.superdesign/` — scratch output from a design tool. Not onboarding material
  and not a source of truth for the shipped UI. See `.superdesign/README.md`.

When a record and the code disagree, the code wins, and the record should be
corrected.
