# FIX_PLAN: Systematic Mypy Findings Resolution

## Background & Motivation
The project has 682 mypy errors across 106 files reported in `bulk_findings.txt`. The goal is to systematically fix all of these issues directly on the current native branch to improve type safety and pass the mypy checks, with zero silencing.

## Scope & Impact
All files listed in `bulk_findings.txt` under `src/app` will be updated to include correct type annotations, resolve incompatible types, remove unused ignores, and address missing stubs.

## Proposed Solution (Categorized & Prioritized)

| Priority | Category | File | Issue | Fix Summary | Est Time |
|----------|----------|------|-------|-------------|----------|
| CRITICAL | Missing Stubs | `core/circuit_breaker.py` | Missing `types-cachetools` | Install missing library stubs via `poetry run mypy --install-types` | 5min |
| HIGH | Type Incompatibility | `core/redis.py`, `integrations/proxmox_client.py`, `api/auth_oauth.py`, `api/status.py` | Incompatible types in assignment/await, `no-any-return` | Fix incompatible variable assignments; correctly specify explicit structures for `dict` and `list` returns instead of `Any`. | 45min |
| MEDIUM | Missing Annotations | `api/*`, `services/*`, `workers/*` | `no-untyped-def` (Missing parameter & return types) | Add `-> None` or correct return types for all endpoints and worker methods; add explicit parameter types. | 60min |
| LOW | Polish | `core/markdown_render.py`, `integrations/ilo.py`, `schemas/settings.py`, `api/ws_topology.py` | Unused `type: ignore` comments | Remove unused `type: ignore` lines. | 10min |

## Implementation Steps

### Phase 1: CRITICAL & Polish
1. Run `poetry run mypy --install-types --non-interactive` to install `types-cachetools` and any other missing stubs.
2. Remove unused `type: ignore` comments in `markdown_render.py`, `ilo.py`, `settings.py`, `ws_topology.py`, `user_service.py`, `admin_users.py`, and `discovery_merge.py`.
3. Verify basic checks.

### Phase 2: Core & Services (HIGH & MEDIUM)
1. Fix `src/app/core/*` (e.g., `url_validation.py`, `redis.py`, `network_acl.py`, `auth_cookie.py`, `rbac.py`).
2. Fix `src/app/services/*` (e.g., `inference_service.py`, `telemetry_cache.py`, `status_page_service.py`, `smtp_service.py`, `discovery_import_service.py`).
3. Correct any missing annotations and type incompatibilities.
4. **Verification**: Run `poetry run ruff check --fix . && poetry run mypy src/` and `make deps-up && make backend`.

### Phase 3: Integrations & Workers (HIGH & MEDIUM)
1. Fix `src/app/integrations/*` (e.g., `proxmox_client.py`, `dispatcher.py`).
2. Fix `src/app/workers/*` (e.g., `webhook_worker.py`, `notification_worker.py`, `discovery.py`, `status_worker.py`, `telemetry_collector.py`, `main.py`).
3. Provide missing `-> None` for worker lifecycle events and resolve `json.loads()` type arguments.
4. **Verification**: Rerun lint/type checks and stress tests.

### Phase 4: APIs & Schemas (MEDIUM)
1. Systematically go through `src/app/api/*` and add missing return type annotations (`-> None`, `-> dict[str, Any]`, etc.).
2. Fix `src/app/schemas/*`.
3. Fix middleware, db, and start.py.
4. **Final Verification**: 
   ```bash
   make deps-up && make backend
   curl -s http://localhost:8000/api/v1/health
   pytest tests/stress/ -n auto --tb=short
   pkill -f uvicorn && make deps-down
   ```

## Verification & Testing
Native verification is mandatory per batch of fixes:
- Start dependencies and backend.
- Curl healthcheck.
- Run stress tests.

## Migration & Rollback
Revert using standard Git mechanisms (`git stash` / `git checkout`) if stress tests fail. No runtime behavior should change as these are strictly type hinting and signature updates.
