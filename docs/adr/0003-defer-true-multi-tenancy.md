# ADR 0003: Defer True Multi-Tenancy Beyond 1.0

**Status:** Accepted for 1.0 planning
**Date:** 2026-08-11
**Requirements:** SEC-01, RC-03
**Decision owners:** Product, security, release

## Context

Circuit Breaker has tenant-shaped code today: tenant tables, membership rows, tenant headers, tenant
context in the frontend, RLS/session-variable machinery, and tenant IDs on several data models. The
1.0 audit found that this does not currently add up to a proven security boundary because tenant
context, RLS behavior, service queries, workers, WebSockets, exports, and background jobs are not
fully and adversarially verified.

For a homelab-focused 1.0 release, the valuable near-term feature is multi-user administration with
RBAC inside one trusted deployment. True multi-tenancy is valuable for MSP, consultant, community lab,
hosted/SaaS, or strict multi-team scenarios, but it substantially expands the security and test
surface.

## Decision

Circuit Breaker 1.0 will not support true multi-tenancy as a security boundary.

The v1 product model is:

- one deployment represents one trust boundary;
- multiple users and RBAC are supported inside that deployment;
- environments, tags, maps, and organizational metadata may be used for filtering and organization;
- separate trust domains require separate Circuit Breaker deployments; and
- true tenant isolation is postponed as a long-term goal.

SEC-2B is the authorized follow-on path for v1. SEC-2A is not authorized for v1 unless this ADR is
superseded.

## Required v1 behavior

- Tenant management UI must be removed, hidden, or hard-disabled.
- Tenant headers/local-storage context must not cause users to believe data is isolated.
- Tenant APIs must be removed, blocked, or admin-internal only with explicit unsupported messaging.
- Documentation and release notes must state that v1 is single-tenant.
- Existing tenant-shaped database columns may remain as inert compatibility metadata only if they do
  not affect the v1 security claim.
- Backups, exports, audit logs, agents, scans, metrics, and WebSockets must be documented and tested
  as single-tenant surfaces for v1.

## Rejected alternative

| Alternative | Reason rejected |
|---|---|
| Implement full SEC-2A tenant enforcement for v1 | High security/test cost relative to homelab value; not necessary for the 1.0 target audience. |
| Leave tenant UI/API visible as beta | Visible controls imply a security boundary users may rely on. That is unsafe for v1. |
| Rename tenants to environments and keep behavior | Cosmetic rename does not remove the security ambiguity unless isolation behavior is also disabled. |
| Delete every tenant column immediately | Risky migration churn for v1. Inert compatibility columns are acceptable if they cannot be used as a security promise. |

## Long-term reopening criteria

True multi-tenancy can be reconsidered after v1 when there is a clear target customer and the team is
ready to fund:

- mandatory tenant context at authentication and transaction boundaries;
- production-role RLS verification;
- tenant predicates for all tenant-owned queries as defense in depth;
- route, WebSocket, SSE, export, backup, worker, agent, metrics, and audit isolation;
- adversarial cross-tenant test matrix;
- tenant-aware backup/restore and deletion semantics; and
- operational runbooks for tenant migration, merge, split, export, and deletion.

