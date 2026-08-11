# SEC-1 — Tenant Decision and Inventory

**Requirement:** SEC-01
**Priority:** P0
**Depends on:** RC-1

## Objective

Choose one coherent 1.0 tenant model using an exhaustive current-state inventory. This slice must end
with either SEC-2A or SEC-2B authorized, never both.

## Primary touchpoints

- `apps/backend/migrations/versions/0038_rename_teams_to_tenants.py`
- `apps/backend/migrations/versions/0040_rls_policies.py`
- `apps/backend/src/app/db/session.py`
- `apps/backend/src/app/middleware/tenant_middleware.py`
- `apps/backend/src/app/api/tenants.py`, `apps/backend/src/app/main.py`
- Tenant-bearing models and service queries under `apps/backend/src/app/`
- `apps/frontend/src/__tests__/tenant-context.test.jsx` and tenant UI/components

## Implementation tasks

1. Enumerate all tables with `tenant_id`, all foreign-key/nested ownership paths, global tables, and
   tenant membership/role tables from SQLAlchemy metadata and live PostgreSQL schema.
2. Enumerate HTTP/WebSocket/SSE/export/worker/agent flows that read or write tenant-owned data.
3. Trace request tenant selection through authentication, middleware, session checkout, transaction,
   queries, worker enqueue/dequeue, and connection return to pool.
4. Identify data with null tenant, cross-tenant references, implicit default tenant, admin bypass, and
   upgrade ambiguity.
5. Estimate SEC-2A enforcement and SEC-2B removal/hard-disable, including migration and user impact.
6. Record the product/security decision in RC-03 and update the entity/action matrix used for tests.

## Evidence commands

```bash
rg -n "tenant_id|current_tenant|row_security|tenant_members" \
  apps/backend/src apps/backend/migrations apps/backend/tests apps/frontend/src
```

The search is discovery evidence only; reviewers must reconcile results with SQLAlchemy metadata and
the migrated PostgreSQL schema.

## Definition of done

The inventory identifies every boundary surface, null/global rule, migration risk, and user claim;
product and security owners approve exactly one follow-on path.
