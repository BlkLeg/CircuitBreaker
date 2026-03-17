# Background & Motivation
The goal is to implement the "Backend Systemic Stability Plan" + "native-first dev tooling" as detailed in the `async_ci_plan.md` specification. This will eliminate hangs, prevent recurrence of stability issues, and ensure zero production drift for local developers.

# Scope & Impact
These changes encompass several key areas:
- **Backend Application Configuration:** Ruff and MyPy strictness to catch sync-in-async errors.
- **Backend Database and Lifespan:** Timeout configs, task management, executor delegation for blocking IO (logging, polling).
- **Tooling:** A shift towards running local application servers natively while relying on Docker exclusively for dependencies (`docker-compose.deps.yml`).
- **Testing and Verification:** Implementing stress tests with Tox and Pytest, alongside tighter pre-commit rules.

# Proposed Solution

## Phase 1: Stability Patches
1. **apps/backend/pyproject.toml**
   - Enable Ruff ASYNC checks, set up per-file ignores, and enforce strict MyPy checks.
2. **apps/backend/src/app/db/session.py**
   - Set pool_timeout=5 on SQLAlchemy engine to fail fast.
3. **apps/backend/src/app/middleware/logging_middleware.py**
   - Execute _write_log using loop.run_in_executor without awaiting it.
4. **apps/backend/src/app/api/events.py**
   - Rewrite SSE polling loop to utilize executors and avoid blocking the event loop.
5. **apps/backend/src/app/services/listener_service.py**
   - Replace SSDP run_in_executor loops with native async socket reading: loop.sock_recvfrom.
6. **apps/backend/src/app/main.py**
   - Correct lifespan logic: keep track of tasks/subscriptions and cleanly cancel/unsubscribe them on shutdown.
   - Adjust the default thread pool executor size.
   - Apply asyncio.timeout wrappers to proxmox jobs.
7. **apps/backend/src/app/db/migrations/versions/0048_telemetry_indexes_purge.py**
   - Add new migration for ix_telemetry_ts_entity, ix_telemetry_ts_metric and purge logic.
8. **CODING_STANDARDS.md**
   - Create file outlining mandatory Async rules.

## Phase 2: Native-First Dev Orchestrator
1. **docker-compose.deps.yml**
   - Create configuration focusing only on Postgres, Redis, and NATS.
2. **Makefile**
   - Add and update targets for deps-up, deps-down, dev, backend, backend-watch, and frontend.
3. **.env.dev**
   - Create to support dev overrides matching production native environments.

## Phase 3: Stress Tests + CI Guardrails
1. **tests/stress/test_event_loop.py**
   - Implement load testing using pytest-asyncio and httpx.
2. **tox.ini**
   - Add a testenv configuration for executing stress tests.
3. **.pre-commit-config.yaml**
   - Add ruff and mypy pre-commit hooks.

# Verification
1. Run pre-commit run --all-files and verify zero violations.
2. Ensure make backend remains stable for 30+ minutes, and /health stays responsive.
3. Ensure make backend-watch triggers clean restarts on file saves.
4. Run tox -e stress to validate concurrent loads.
5. Boot system with make dev and ensure native backend/frontend and Docker dependencies start cleanly with no hangs.