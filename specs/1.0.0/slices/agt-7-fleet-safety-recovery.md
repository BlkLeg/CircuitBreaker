# AGT-7 — Fleet Safety and Recovery

**Requirements:** AGT-16, AGT-17, AGT-18
**Depends on:** AGT-6 state contract

## Primary files

- `apps/frontend/src/pages/AgentDetailPage.jsx`, agent list/page tests and components
- `apps/backend/src/app/api/agents.py`, schemas, registry/capability/update services
- `apps/agent/internal/spool/`, update/link/uninstall handling
- Agent security and operations documentation

## Build sequence

1. Define impact tiers and confirmation payloads for revoke, uninstall, scope expansion, remote probe,
   discovery grant, and update dispatch. Enforce authorization and target version/state server-side.
2. Add idempotency, actor/target/before/after/outcome audit, cancellation boundaries, and safe retries.
3. Design paginated/filterable fleet queries for presence, version drift, update state/failure, spool
   pressure, and capability health; add indexes only from measured query plans via forward migration.
4. Implement accessible filters, saved URL state, bounded refresh/live updates, empty/error/stale states,
   and aggregate counts that cannot disagree with filtered rows.
5. Write and exercise runbooks for lost server key, cloned machine ID, duplicate agent, hostname/IP
   change, expired pairing code, and server restore/re-key.
6. Load test target fleet size and test concurrent actions, partial failure, retry, and audit export.

## Verification and rollout

Run backend agent API/service suites, frontend agent page tests, browser E2E, PostgreSQL query-plan
checks, and recovery table-tops. Roll out indexes concurrently where supported and gate bulk actions
behind explicit feature readiness. Done requires safe operations and exercised recovery—not docs alone.
