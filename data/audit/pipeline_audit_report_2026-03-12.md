# Circuit Breaker Pipeline Audit Report

Date: 2026-03-12

Scope: API -> service layer -> DB/Redis/runtime -> frontend rendering, with focused traces for Hardware CRUD, Telemetry, Auth, and Discovery/Review Queue.

Artifacts generated during audit:
- `data/audit/route_ledger.json`
- `data/audit/route_ledger_combined.json`
- `data/audit/unauth_sensitive_routes.txt`
- `data/audit/route_limiter_coverage.json`

## Critical

### F-001: Discovery pipeline is currently broken by DB schema drift (`BROKEN`)
- Impact: Discovery status/history APIs fail with `500`, blocking core workflow visibility.
- Evidence:
  - Runtime probe: `/api/v1/health` returns `200` while `/api/v1/discovery/jobs` returns `500`.
  - Repeated runtime error in `/home/shawnji/Documents/circuitbreaker-data/backend_api_err.log`: `UndefinedColumn: column scan_jobs.error_reason does not exist`.
- Affected flows: **Flow D** (Discovery -> Review Queue), operational observability.

### F-002: Sensitive data routes are exposed without auth dependencies (`INSECURE`)
- Impact: Topology, hardware inventory, discovery jobs/results/logs, settings, and recent-change audit feed are readable without explicit auth guard in route dependency chain.
- Evidence:
  - 30 endpoints captured in `data/audit/unauth_sensitive_routes.txt`.
  - Includes `GET /api/v1/settings`, `GET /api/v1/admin/recent-changes`, `GET /api/v1/graph/topology`, and multiple `GET /api/v1/discovery/*` routes.
- Affected flows: **Flow A**, **Flow D**, cross-cutting security posture.

## High

### F-003: Unbounded hot-path queries and missing pagination (`SCALE`)
- Impact: Query and serialization cost scale linearly with dataset size; risk of latency spikes and memory pressure at 1000+ node topology.
- Evidence:
  - `GET /api/v1/discovery/results` returns `.all()` with no limit.
  - `GET /api/v1/hardware` returns full collection with no page/limit cursor.
  - `GET /api/v1/graph/topology` builds large in-memory graph payloads.
- Affected flows: **Flow A**, **Flow D**, map rendering and discovery review.

### F-004: Frontend map path is non-virtualized and frequently O(N) state churn (`SCALE`)
- Impact: Large graphs cause heavy client CPU/memory use; repeated full-array transforms degrade interactivity.
- Evidence:
  - Topology load path in `useMapDataLoad` maps all nodes/edges into client state in one pass.
  - `MapPage` applies frequent full `setNodes`/`setEdges` transforms for updates and filters.
- Affected flows: **Flow A**, **Flow B** render paths.

### F-005: Rate limiting is sparse outside selected endpoints (`INCOMPLETE`)
- Impact: Expensive or sensitive endpoints can be queried repeatedly without throttle controls.
- Evidence:
  - Route scan result: 340 total routes, 34 with `@limiter.limit`, 306 without (`data/audit/route_limiter_coverage.json`).
  - High-read surfaces (graph/hardware/discovery list endpoints) generally not rate-limited.
- Affected flows: cross-cutting.

### F-006: Container healthcheck does not reflect functional route health (`UNSTABLE`)
- Impact: Orchestrator sees container as healthy while critical business routes are failing.
- Evidence:
  - Compose healthcheck uses only `/api/v1/health` (`docker/docker-compose.yml`).
  - Runtime demonstrated green health with failing discovery route.
- Affected flows: deployment reliability and incident detection.

## Medium

### F-007: Raw `fetch` calls bypass centralized API client behavior (`INCOMPLETE`)
- Impact: Inconsistent retry/session-expiry/error handling and telemetry around API failures.
- Evidence:
  - Raw `fetch` in `OOBEWizardPage`, `AuthContext`, `LiveListenersPanel`, `SecurityBanner`, `HeaderWidgets`, `HardwareForm`, and logout path in `api/client`.
- Affected flows: **Flow C** plus general frontend reliability.

### F-008: Several pages/components fail silently or with console-only errors (`INCOMPLETE`)
- Impact: Operators get incomplete feedback during degraded backend conditions.
- Evidence:
  - Discovery load paths log warnings/errors without user-facing state in multiple branches (jobs/profiles/pending/status fetch failures).
  - ErrorBoundary coverage is present, but async data failures are not consistently surfaced in UI.
- Affected flows: **Flow D** and general UX resilience.

### F-009: Telemetry fallback polling can still create burst load patterns (`SCALE`)
- Impact: During WS degradation, per-node polling and short scheduler loops can create bursty backend load.
- Evidence:
  - `useMapRealTimeUpdates` fallback loop checks due nodes every 5s and issues per-node requests with `Promise.allSettled`.
  - Backoff exists, but large node sets can still spike at alignment boundaries.
- Affected flows: **Flow B**.

### F-010: Legacy API token remains an admin-capable bypass path (`INSECURE`)
- Impact: Single bearer secret grants broad admin-equivalent access where accepted (including WS auth path), increasing blast radius of token leakage.
- Evidence:
  - Legacy token middleware and WS auth both accept API token path when configured.
- Affected flows: **Flow C**, WS security model.

### F-011: Stale vault key warning repeats in worker runtime (`UNSTABLE`)
- Impact: Secret lifecycle/rotation drift raises operational risk and confusion during recovery/rotation events.
- Evidence:
  - Repeated warning in `/home/shawnji/Documents/circuitbreaker-data/worker_3_err.log` indicating stale `CB_VAULT_KEY` hash mismatch.
- Affected flows: secret management and long-term ops hygiene.

### F-012: OAuth token lifecycle appears incomplete for long-lived sessions (`INCOMPLETE`)
- Impact: Provider token refresh continuity risk (especially if access token expires and refresh token is not persisted/used end-to-end).
- Evidence:
  - OAuth flow implementation does not clearly persist/use refresh-token lifecycle for long-lived provider sessions.
- Affected flows: **Flow C** (OAuth branch).

## Low

### F-013: CORS method/header posture is broad if origins are misconfigured (`INSECURE`)
- Impact: Current default is strict-origin, but permissive methods/headers create wider risk if origin list is broadened incorrectly.
- Evidence:
  - `allow_methods=["*"]`, `allow_headers=["*"]` with origin list from settings.
- Affected flows: cross-cutting security hardening.

### F-014: Hardcoded API base constants appear in component-level calls (`INCOMPLETE`)
- Impact: Configuration drift risk and maintenance overhead.
- Evidence:
  - `LiveListenersPanel` defines `API_BASE = '/api/v1'` instead of using shared client abstraction.
- Affected flows: frontend maintainability.

### F-015: Residual N+1 patterns remain in some serialization paths (`SCALE`)
- Impact: Elevated DB round-trips under larger inventory.
- Evidence:
  - Hardware list serializes tags per-row via helper calls despite other bulk optimizations.
- Affected flows: **Flow A** read path.

## Flow Implementation Status

| Flow | Status | Notes |
|---|---|---|
| A: Hardware CRUD | Implemented with high-risk gaps | Functional CRUD path, but unauthenticated reads + unbounded listing + scale risk. |
| B: Telemetry Poll/Stream | Implemented with medium-risk gaps | WS + cache fallback present; fallback polling can become bursty at scale. |
| C: Authentication | Implemented with medium/high gaps | Cookie/JWT/session revocation/rate-limit pieces exist; legacy token and lifecycle consistency gaps remain. |
| D: Discovery -> Review Queue | **Partially broken** | Runtime schema drift currently breaks key status/history endpoints with 500s. |

## Ordered Remediation Plan (by impact)

### P0 (Immediate)
1. Fix schema drift: ensure `scan_jobs.error_reason` exists in live DB everywhere this release runs.
2. Apply auth dependency guards to all sensitive read routes (settings, recent-changes, topology, discovery internals).
3. Add contract/regression checks in CI: model-vs-migration drift detection and smoke test for discovery status/jobs endpoints.

### P1 (Near-term)
1. Add pagination and default limits to heavy list endpoints (`hardware`, `discovery/results`, graph-related payload APIs where feasible).
2. Expand route-level rate limiting profile to sensitive/expensive reads.
3. Improve health strategy: keep liveness lightweight, add readiness probe(s) for representative business-critical route success.

### P2 (Hardening + scale)
1. Normalize frontend network calls behind shared API client (eliminate raw internal `fetch` for app API routes).
2. Add explicit async failure UI states for discovery/map data loaders (not console-only).
3. Reduce map render churn for large topologies (batch updates, memoized selectors, progressive rendering/virtualization strategy).
4. Tighten secrets lifecycle ops around vault key rotation and runtime env reconciliation.

## Completion Checklist

- [x] Full backend route ledger built (auth/DB/Redis/schema/error metadata)
- [x] Auth lifecycle traced frontend <-> backend
- [x] Hardware CRUD flow traced end-to-end
- [x] Telemetry poll/stream/cache/worker flow traced
- [x] Discovery/Proxmox/review queue flow traced
- [x] DB/Redis runtime assumptions validated against live runtime
- [x] Security/frontend completeness/scale sweeps completed and classified
- [x] Final structured report delivered with severity buckets, flow status table, and prioritized remediation plan
