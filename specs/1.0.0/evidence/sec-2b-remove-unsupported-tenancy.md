# SEC-2B Remove Unsupported Tenancy Evidence

**Status:** Implementation evidence captured; release-artifact upgrade rehearsal still pending
**Generated:** 2026-08-11
**Requirement:** SEC-05
**Decision basis:** [ADR 0003](../../../docs/adr/0003-defer-true-multi-tenancy.md)

## Implemented v1 behavior

- `/api/v1/tenants` and every nested legacy tenant API path remain mounted but return HTTP `410 Gone`
  with a stable unsupported-tenancy message.
- Tenant request middleware no longer resolves `X-Tenant-ID`, JWT `tenant_id`, user tenant defaults,
  or tenant membership. It resets `current_tenant_id` to `None` for each request.
- The frontend API client no longer reads `cb_active_tenant_id` and no longer sends `X-Tenant-ID`.
- The frontend tenant context no longer fetches tenants, stores an active tenant, switches tenants,
  or reloads the application. It clears stale `cb_active_tenant_id` browser storage on mount.
- The `/tenants` frontend route redirects to `/map`.
- Tenant navigation/dock entries and the tenant management page were removed.

## Upgrade/data handling policy

Existing tenant-shaped database columns and rows are retained as inert compatibility metadata for
1.0. They are not a supported isolation mechanism.

Databases that previously relied on tenant isolation for security must not be silently merged or
operated as a multi-tenant 1.0 deployment. Operators must export or split those trust domains into
separate Circuit Breaker deployments before relying on 1.0.

The compatibility policy records this behavior in
`docs/release/1.0.0-compatibility-policy.md`.

## Tests added or rewritten

- `apps/backend/tests/test_single_tenant_contract.py`
  - authenticated direct calls to legacy tenant CRUD/member paths return `410`;
  - crafted `X-Tenant-ID` headers do not select request tenant context.
  - tenant-shaped upgraded rows, tenant memberships, users with legacy `tenant_id`, and JWT
    `tenant_id` claims remain inert compatibility data while legacy tenant APIs stay `410`.
- `apps/frontend/src/__tests__/tenant-context.test.jsx`
  - tenant context exposes no active tenant;
  - stale `cb_active_tenant_id` local storage is cleared;
  - `switchTenant` cannot set local storage or reload.

## Local verification

```bash
cd apps/backend
pytest -q --no-cov tests/test_single_tenant_contract.py

cd ../frontend
npm run test -- src/__tests__/tenant-context.test.jsx \
  src/__tests__/oobe-wizard.test.jsx \
  src/__tests__/oauth-providers-manager.test.jsx
```

Result: **PASS** on 2026-08-11. Backend SEC-2B contract tests include the tenant-shaped
upgrade rehearsal; focused frontend tests cover stale tenant storage, OOBE setup-token flows, and
OAuth/OIDC provider management.

## Remaining tenant references review

The required SEC-2B search still returns intentional references:

- backend compatibility shims: `apps/backend/src/app/api/tenants.py`,
  `apps/backend/src/app/middleware/tenant_middleware.py`, and the legacy tenant rate-limit wrapper;
- inert data fields and API response fields that predate the v1 decision;
- historical audit/release documents that are superseded by ADR 0003 and the v1 support contract;
- user-facing docs that explicitly state v1 is single-tenant per deployment.

## Pending release evidence

This slice still needs the broader ACC upgrade rehearsal from release artifacts before SEC-05 can be
treated as final release evidence:

- upgrade a `0.3.5` database with tenant-shaped rows to the 1.0 candidate;
- verify rows are preserved and not silently merged/deleted;
- verify stale browser storage and direct legacy API calls remain disabled after upgrade.
