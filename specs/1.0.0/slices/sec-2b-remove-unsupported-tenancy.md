# SEC-2B — Remove Unsupported Tenancy

**Requirement:** SEC-05
**Priority:** P0
**Run only if:** RC-03 declares 1.0 single-tenant

## Objective

Remove the appearance and activation paths of a security boundary Circuit Breaker does not support,
while preserving existing user data through an explicit upgrade policy.

## Primary touchpoints

- `apps/backend/src/app/api/tenants.py`, `apps/backend/src/app/middleware/tenant_middleware.py`
- Tenant router registration in `apps/backend/src/app/main.py`
- Tenant/team models, settings, membership scopes, and migrations
- Frontend tenant context, tenant management UI, navigation, settings, and local storage
- `docs/auth-access.md`, deployment/security/privacy/support documentation

## Implementation sequence

1. Decide how existing multi-tenant-shaped databases migrate: block upgrade pending export, select one
   tenant with explicit operator confirmation, or provide a reviewed merge tool. Never merge silently.
2. Remove/hard-disable tenant create/switch/member APIs and UI. Requests to legacy paths should return
   a stable removal error, not expose dormant behavior.
3. Remove tenant-selection middleware assumptions and define ownership for formerly null/global rows.
4. Retain schema columns only where needed for safe compatibility; label them internal and prevent
   configuration from reactivating unsupported behavior.
5. Remove public multi-tenant claims and add migration/known-limitation documentation.
6. Add tests for direct legacy API calls, crafted tenant headers/cookies, stale browser storage,
   upgraded databases, and configuration attempts.

## Verification

```bash
rg -n "tenant|team" README.md docs apps/frontend/src apps/backend/src/app/api \
  apps/backend/src/app/middleware
```

Review every remaining product-facing hit. Run backend auth/tenant tests, frontend tenant-context
tests rewritten for the single-tenant contract, and the full upgrade rehearsal.

## Rollout and rollback

Require a pre-upgrade backup and data-shape report. If migration needs operator choice, stop before
mutation. A rollback must restore the prior database and application together; mixed binaries/schema
must be rejected under RC-04.

## Definition of done

No user or request can activate, select, or reasonably infer supported multi-tenancy, and existing
data follows the approved, tested migration policy.
