# RUFF_FIX_PLAN: Systematic Ruff Findings Resolution

## Background & Motivation
A recent ruff scan reported 64 formatting and linting errors across the codebase in `src/app`. The objective is to fix all of these findings without using any silencing comments (like `noqa` or `type: ignore`). They must be fixed properly by refactoring code, sorting imports, and wrapping lines correctly to pass the ruff check.

## Scope & Impact
Files affected include API endpoints, core modules, middleware, services, and workers. 

## Proposed Solution (Categorized)

| Category | Issue | Fix Summary | Est Time |
|----------|-------|-------------|----------|
| **E501** | Line too long (> 100 chars) | Wrap parameters, extract variables, or break strings across lines in `src/app/api/*`, `core/*`, `middleware/*`, `workers/*`, and `start.py`. | 30min |
| **I001** | Unsorted / unformatted imports | Reorganize and sort import blocks logically (stdlib -> third party -> local). Apply to `api/auth_oauth.py`, `api/bootstrap.py`, `api/ipam.py`, `api/logs.py`, `core/auth_cookie.py`, `core/redis.py`, `core/scheduler.py`, `db/cve_session.py`. | 15min |
| **F401** | Unused imports | Remove unused `json` and `typing.Any` imports from `api/settings.py`, `core/rbac.py`, `services/*`. | 10min |
| **E402** | Module level import not at top of file | Move `from app.db.models import ScanResult` to the top of `src/app/services/inference_service.py`. | 5min |
| **UP041** | Replace aliased errors | Replace `asyncio.TimeoutError` with the built-in `TimeoutError` in `workers/discovery.py`, `workers/notification_worker.py`, `workers/webhook_worker.py`. | 5min |

## Implementation Steps

### Phase 1: Import Fixes (I001, F401, E402)
1. **Unused Imports**: Remove the unused imports flagged by `F401`.
   - `src/app/api/settings.py` (json)
   - `src/app/core/rbac.py` (Any)
   - `src/app/services/catalog_service.py` (Any)
   - `src/app/services/compute_units_service.py` (json)
   - `src/app/services/hardware_service.py` (json)
   - `src/app/services/self_discovery.py` (json)
2. **Sort Imports**: Manually reorganize imports in `auth_oauth.py`, `bootstrap.py`, `ipam.py`, `logs.py`, `auth_cookie.py`, `redis.py`, `scheduler.py`, `cve_session.py`.
3. **Module Imports**: Move `from app.db.models import ScanResult` to the top of `src/app/services/inference_service.py`.

### Phase 2: Refactor Syntax & Types (UP041)
1. Replace `asyncio.TimeoutError` with `TimeoutError` in:
   - `src/app/workers/discovery.py`
   - `src/app/workers/notification_worker.py`
   - `src/app/workers/webhook_worker.py`

### Phase 3: Line Length Wrapping (E501)
1. Systematically refactor long lines to fit within 100 characters.
   - Refactor FastAPI signatures to wrap multiple `Depends` parameters properly on new lines.
   - Break down long dictionary comprehensions, tuple unpacking, or string concatenations.
   - Files: `api/auth.py`, `api/auth_oauth.py`, `api/docs.py`, `api/external_nodes.py`, `api/hardware.py`, `api/ip_check.py`, `api/misc.py`, `api/networks.py`, `api/notifications.py`, `api/proxmox.py`, `api/rack.py`, `api/services.py`, `api/settings.py`, `api/storage.py`.
   - Other files: `core/network_acl.py`, `middleware/csrf.py`, `middleware/logging_middleware.py`, `middleware/security_headers.py`, `services/hardware_service.py`, `start.py`, `workers/notification_worker.py`, `workers/status_worker.py`, `workers/webhook_worker.py`.

## Verification & Testing
1. Run `/home/shawnji/Documents/projects/CircuitBreaker/.venv/bin/ruff check src/app` and ensure 0 errors remain.
2. Confirm the codebase behaves identically since these are purely formatting, linting, and unused import removals.
3. No silencing comments (`noqa` or `# type: ignore`) will be used.