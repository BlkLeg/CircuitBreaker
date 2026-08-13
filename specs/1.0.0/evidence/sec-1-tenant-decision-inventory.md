# SEC-1 Tenant Decision and Inventory

**Status:** Decision recorded; SEC-2B authorized; SEC-02 through SEC-04 not applicable for 1.0
**Generated:** 2026-08-11
**Requirement:** SEC-01
**Decision:** True multi-tenancy is deferred beyond 1.0. Circuit Breaker 1.0 is single-tenant with
multi-user RBAC.

## Decision summary

The v1 product supports multiple user accounts and roles inside one deployment. It does not support
multiple isolated tenants inside one deployment. Separate trust domains must use separate Circuit
Breaker deployments.

This authorizes `specs/1.0.0/slices/sec-2b-remove-unsupported-tenancy.md` for v1. It does not
authorize `SEC-2A` enforcement work unless ADR 0003 is superseded.

## Discovery commands

```bash
rg -n "tenant|tenancy|multi-tenant|multi tenant|organization|workspace" \
  README.md docs apps/backend/src apps/frontend/src specs/1.0.0 packaging deploy -g '!node_modules'

rg -n "tenant_id|current_tenant|row_security|tenant_members" \
  apps/backend/src apps/backend/migrations apps/backend/tests apps/frontend/src
```

## Tenant-bearing SQLAlchemy models

Regenerated from SQLAlchemy model metadata at current `HEAD`, then reconciled against the migrated
PostgreSQL test schema used by the SEC gates. These mapped tables carry `tenant_id`:

| Table | Model |
|---|---|
| `hardware` | `Hardware` |
| `agents` | `Agent` |
| `services` | `Service` |
| `networks` | `Network` |
| `hardware_clusters` | `HardwareCluster` |
| `external_nodes` | `ExternalNode` |
| `integration_configs` | `IntegrationConfig` |
| `scan_jobs` | `ScanJob` |
| `scan_results` | `ScanResult` |
| `users` | `User` |
| `topologies` | `Topology` |
| `audit_log` | `AuditLog` |
| `ip_addresses` | `IPAddress` |
| `vlans` | `VLAN` |
| `sites` | `Site` |
| `node_relations` | `NodeRelation` |

Additional tenant structures:

- `tenants` table and `Tenant` model;
- `tenant_members` association table;
- migration `0038_rename_teams_to_tenants.py`;
- migration `0040_rls_policies.py`;
- migration `0100_discovery_agent_execution.py` RLS policy for `scan_results`.

## Runtime and user-facing surfaces

| Surface | Current evidence | SEC-1 disposition |
|---|---|---|
| Backend tenants API | `apps/backend/src/app/api/tenants.py`, mounted under `/api/v1/tenants` | Remove, block, or hide for v1 under SEC-2B. |
| Tenant middleware | `apps/backend/src/app/middleware/tenant_middleware.py` resolves `X-Tenant-ID`, JWT tenant claim, user tenant, and sets context var | Must not be represented as v1 isolation; SEC-2B decides whether to remove or make inert. |
| DB session variable | `apps/backend/src/app/db/session.py` sets `app.current_tenant` on checkout | Not sufficient for v1 security boundary; hard-disable or make inert if tenancy unsupported. |
| RLS migration | `apps/backend/migrations/versions/0040_rls_policies.py` creates tenant policies but disables row security on `breaker` role | Confirms audit concern; not v1 support evidence. |
| Frontend tenant context | `apps/frontend/src/context/TenantContext.jsx` stores `cb_active_tenant_id` and reloads on switch | Remove/hide for v1 to avoid implying isolation. |
| API client tenant header | `apps/frontend/src/api/client.jsx` sends active tenant header from local storage | Remove/hard-disable for v1 unless internal-only and non-user-visible. |
| Tenant management UI | `/tenants` route and tenant tests exist | Remove/hide from navigation and route access for v1. |
| Discovery/agent tenant checks | Agent, discovery, monitor services include tenant mismatch checks | Treat as compatibility metadata only unless SEC-2A is reopened. |
| Historical docs | `docs/updates/v0.2.8_release.md` advertises multi-tenant foundations | Supersede for v1 with ADR 0003 and release notes. |

## Follow-on requirements for SEC-2B

- Existing tenant rows/columns remain inert compatibility metadata and are not collapsed.
- `/api/v1/tenants` and tenant member management return stable `410 Gone`.
- Tenant switcher/page/storage/header behavior is hard-disabled for v1.
- RBAC tests remain independent of tenant isolation claims.
- Docs/release notes state true multi-tenancy is a long-term goal and separate trust domains must
  use separate deployments for v1.

Under ADR 0003 and the SEC-2B implementation path, SEC-02, SEC-03, and SEC-04 are explicitly
deferred/not applicable to the 1.0 release because true multi-tenancy is not a supported security
boundary.

## User impact

Homelab users keep the important v1 behavior: multiple users, roles, maps, environments, tags, and
organizational views. Users needing hard isolation between groups/customers/sites must run separate
Circuit Breaker deployments for v1.
