`# AGENTS Guide for CircuitBreaker

## Big Picture
- CircuitBreaker is a monorepo: FastAPI backend in `apps/backend`, React/Vite frontend in `apps/frontend`, packaging/deploy at repo root.
- Runtime shape is "single app + async workers": API routes, scheduled jobs, and worker loops are wired in `apps/backend/src/app/main.py`.
- Backend uses Postgres + Redis + NATS for dev/prod parity (see `docker-compose.deps.yml` and `Makefile` targets).
- Frontend talks to `/api/v1` through one Axios client in `apps/frontend/src/api/client.jsx` (CSRF + tenant headers are injected there).

## Service Boundaries and Data Flow
- HTTP API boundary: FastAPI routers are mounted centrally in `apps/backend/src/app/main.py` under `/api/v1/...`.
- Real-time boundary is split:
  - WebSocket streams for discovery/topology/telemetry (`ws_*` routers in `apps/backend/src/app/main.py`).
  - SSE stream at `/api/v1/events/stream` in `apps/backend/src/app/api/events.py`.
- Event backbone is NATS subjects in `apps/backend/src/app/core/subjects.py`.
- Important resilience pattern: SSE and NATS publishing degrade gracefully if NATS is unavailable (`apps/backend/src/app/api/events.py`, `apps/backend/src/app/core/nats_client.py`).

## Critical Dev Workflows
- Bootstrap local dev once: `make install` (creates root `.venv`, installs backend extras + frontend deps).
- Start full native dev stack: `make dev` (starts deps + backend + frontend).
- Start only infra deps: `make deps-up`; stop with `make deps-down`.
- When hot-reload is unstable, use `run_backend.sh` (runs Alembic then starts uvicorn without reload).
- Run migration explicitly: `make migrate`.
- Quality gates used by CI are mirrored by `make lint`, `make test`, and `make security-check`.

## Project-Specific Conventions
- Always use Python 3.12 and Node 20 (aligned with workflows in `.github/workflows/ci.yml`).
- Keep backend imports resolvable with `PYTHONPATH=src` (used by Makefile/CI commands).
- New backend endpoints should be added via router modules in `apps/backend/src/app/api/` and included in `app/main.py`.
- Frontend API calls should be added to `apps/frontend/src/api/client.jsx` (not scattered direct `fetch` calls).
- Realtime UI updates should emit/listen via module-level emitters (`discoveryEmitter` in `useDiscoveryStream.js`, `sseEmitter` in `sseClient.js`).
- Versioning is repo-root driven (`VERSION`); frontend syncs version during build (`apps/frontend/package.json` -> `syncversion`).

## Integration Touchpoints
- External systems include Proxmox, SMTP, OIDC/OAuth providers, SNMP/IPMI, and webhook sinks (see routers/services under `apps/backend/src/app/api/` + docs in `docs/integrations-webhooks-notifications.md`).
- Webhook/notification/discovery workers may run in-process or separately depending on `CB_RUN_INPROCESS_WORKERS` (`apps/backend/src/app/main.py`).
- Docker deployment defaults to `Dockerfile.mono` via `docker-compose.yml` (single container bundling app + internal services).

## Where to Start for Common Changes
- API behavior: `apps/backend/src/app/api/` + related service in `apps/backend/src/app/services/`.
- Cross-cutting security/middleware: `apps/backend/src/app/middleware/` and `apps/backend/src/app/core/`.
- UI pages/routes: `apps/frontend/src/pages/` and route wiring in `apps/frontend/src/App.jsx`.
- Build/release/packaging: `Makefile`, `scripts/build_native_release.py`, and `packaging/README.md`.

