# SEC-2A — Enforced Tenant Boundary

**Requirements:** SEC-02, SEC-03, SEC-04
**Priority:** P0
**Run only if:** RC-03 declares multi-tenancy supported

## Objective

Enforce tenant isolation using the production PostgreSQL role plus application predicates, including
pooled connections, streams, workers, nested resources, exports, and agent traffic.

## Primary touchpoints

- `apps/backend/src/app/db/session.py`
- `apps/backend/src/app/middleware/tenant_middleware.py`
- `apps/backend/migrations/versions/0040_rls_policies.py` plus a new forward migration
- Tenant-bearing models, API routers, and services under `apps/backend/src/app/`
- PostgreSQL test setup in `apps/backend/tests/conftest.py`
- Existing tenant/discovery/agent tests under `apps/backend/tests/`

## Design constraints

- Never rewrite migration `0040` for deployed databases; add an idempotent forward migration.
- Tenant session state must be set inside the same transaction that executes protected queries.
- The application role must not have `BYPASSRLS` or `row_security=off` in production.
- RLS is the database boundary; application predicates are defense in depth and clearer 404/403 logic.
- Explicit platform administration must use a separately authorized path, not a silent global bypass.

## Implementation sequence

1. Add schema/role assertions that fail if the production role bypasses RLS or a tenant table lacks
   the expected policy.
2. Introduce a transaction-scoped tenant context API. Reject authenticated requests without valid
   membership before opening protected work; use `SET LOCAL`/transaction-local configuration.
3. Ensure connection checkout/reset cannot inherit tenant context. Add reuse and exception-path tests.
4. Add the forward migration to remove the role default bypass, enable/force policies as designed,
   and cover new tenant-bearing tables. Verify upgrade and downgrade safety explicitly.
5. Add tenant predicates to repositories/services, including nested lookups and mutations. Avoid
   fetch-by-ID followed by authorization if the query itself can scope ownership.
6. Propagate signed/validated tenant identity to workers, WebSockets/SSE, exports, and agent jobs;
   never trust payload tenant IDs over authenticated ownership.
7. Build a parametrized entity/action matrix across two tenants for CRUD, search, export, streams,
   background work, agent identity, null context, invalid context, concurrency, and enumeration.

## Verification

```bash
cd apps/backend
PYTHONPATH=src pytest -q --no-cov tests -k 'tenant or rls or authorization'
```

Then run the full PostgreSQL/Timescale suite using the production-equivalent application role. A
SQLite or superuser-only run cannot close this slice. Inspect `pg_roles`, `pg_class`, and `pg_policy`
as part of retained evidence.

## Rollout and rollback

Preflight must report null/orphan/cross-tenant data before policy enforcement. Roll out in an RC
upgrade rehearsal with backup and restore. Downgrade must not re-enable a bypass silently; if safe
downgrade is impossible, block it with an actionable message and documented restore path.

## Definition of done

All entity/action rows deny cross-tenant access at API and database layers using the exact production
role, including pooled reuse and asynchronous work.
