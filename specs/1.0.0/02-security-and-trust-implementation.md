# Security and Trust — Sprint Implementation Slices

**Companion spec:** [02-security-and-trust.md](./02-security-and-trust.md)
**Status:** Ready for technical design
**Priority:** P0

## Standalone slice plans

- [SEC-1 — Tenant decision and inventory](./slices/sec-1-tenant-decision-inventory.md)
- [SEC-2A — Enforced tenant boundary](./slices/sec-2a-enforced-tenant-boundary.md)
- [SEC-2B — Remove unsupported tenancy](./slices/sec-2b-remove-unsupported-tenancy.md)
- [SEC-3 — Endpoint policy and monitor authorization](./slices/sec-3-endpoint-policy-monitor-auth.md)
- [SEC-4 — Bootstrap and authentication](./slices/sec-4-bootstrap-authentication.md)
- [SEC-5 — Outbound and dependency safety](./slices/sec-5-outbound-dependency-safety.md)
- [SEC-6 — Content, audit, destructive actions, and scans](./slices/sec-6-content-audit-scans.md)

## Slice SEC-1 — Tenant product decision and inventory

**Requirements:** SEC-01
**Depends on:** RC-1

- [ ] Inventory tenant UI, routes, middleware, models, database policies, workers, streams, exports,
  agent paths, and user-facing claims.
- [ ] Produce two estimates: enforce multi-tenancy as a 1.0 boundary or remove/hard-disable it.
- [ ] Record the chosen boundary in RC-03 and define migration/upgrade behavior.
- [ ] Build the tenant-owned entity/action matrix used by later slices.

**Verification:** Security and product owners approve one path; no implementation begins with a
hybrid or implicit tenant promise.

## Slice SEC-2A — Enforced tenant boundary

**Requirements:** SEC-02, SEC-03, SEC-04
**Runs only if:** Multi-tenancy is supported

- [ ] Move tenant context establishment into the request transaction and make authenticated tenant
  context mandatory.
- [ ] Remove production-role RLS bypass and validate grants/migrations for fresh and upgraded DBs.
- [ ] Add tenant predicates to service/repository queries as defense in depth.
- [ ] Propagate explicit tenant context to workers, WebSockets/SSE, exports, and agent dispatch.
- [ ] Add pooled-connection, concurrent-tenant, missing/invalid context, admin override, nested route,
  and ID-enumeration adversarial tests.

**Verification:** Full entity/action matrix passes at both application and RLS layers using the
production database role.

## Slice SEC-2B — Remove unsupported tenancy

**Requirements:** SEC-05
**Runs only if:** Multi-tenancy is not supported

- [ ] Remove or hard-disable tenant selection, management, routes, middleware, settings, and claims.
- [ ] Define upgrade handling for existing tenant records without merging or exposing data silently.
- [ ] Add tests proving unsupported tenant features cannot be enabled by request or configuration.
- [ ] Update support, security, privacy, and migration documentation.

**Verification:** UI/API/configuration inspection exposes only the supported single-tenant model and
upgrade tests preserve data according to the approved migration decision.

## Slice SEC-3 — Endpoint policy and monitor authorization

**Requirements:** SEC-06, SEC-07, SEC-08
**Depends on:** SEC-2A or SEC-2B

- [ ] Generate an inventory of HTTP, WebSocket, SSE, metrics, health, bootstrap, file, and agent
  endpoints with declared public/auth/RBAC/tenant policy.
- [ ] Create a reviewed public-route allowlist and a CI failure for unclassified new routes.
- [ ] Protect all monitor read and nested-data endpoints with correct scope and tenant policy.
- [ ] Implement the role/session/tenant/agent authorization matrix as parametrized tests.
- [ ] Check alternate encodings, identifier enumeration, downloads, and stream reconnects.

**Verification:** The inventory and runtime route table reconcile exactly; the full identity matrix
passes and public disclosure is limited to approved fields.

## Slice SEC-4 — Bootstrap and authentication hardening

**Requirements:** SEC-09, SEC-10
**Depends on:** SEC-3

- [ ] Select one-time setup token or approved local/private bootstrap binding and define expiry,
  replay, restart, and competing-request behavior.
- [ ] Implement first-admin race tests with simultaneous clients.
- [ ] Test MFA, backup codes, forced password change, lockout ordering, logout/revocation, expired
  sessions, OAuth callback codes, CSRF/CORS/CSP, secure cookies, and proxy identity.
- [ ] Repeat relevant authentication cases through HTTP, WebSocket, and SSE in every deployment mode.

**Verification:** No competing user gains first-admin authority; revocation takes effect across all
transports and trusted-proxy behavior matches configuration.

## Slice SEC-5 — Outbound and dependency safety

**Requirements:** SEC-11, SEC-12, SEC-13, SEC-14
**Depends on:** Can run after SEC-1

- [x] Resolve the Click advisory and add/confirm production dependency scans.
- [x] Centralize outbound destination validation and pin validated addresses or enforce egress proxy
  policy for webhooks and every integration.
- [x] Move rate limits to shared storage and implement trusted-proxy client identity.
- [x] Inventory mandatory secrets/dependencies and define fail-closed versus explicitly degraded
  behavior for Redis, NATS, vault, signing, encryption, and sessions.
- [x] Add DNS rebinding, redirect, address-encoding, multi-instance rate-limit, spoofed header, and
  empty/missing secret tests.

**Verification:** Security integration suite and dependency scans pass in mono and split topologies.

## Slice SEC-6 — Content, audit, destructive actions, and scans

**Requirements:** SEC-15, SEC-16, SEC-17, SEC-18
**Depends on:** SEC-3; can overlap SEC-5

- [ ] Choose sanitize, rasterize, or reject policy for SVG/active uploads and enforce safe serving.
- [ ] Serialize audit-chain writes and implement verification plus supported repair procedure.
- [ ] Define and implement safeguards for clear-lab, wipe restore, tenant deletion, revoke/uninstall,
  and bulk import, including audit events.
- [ ] Standardize scan suppression metadata and make the complete scan set an RC artifact gate.
- [ ] Add malicious-upload, concurrent audit, tamper/repair, destructive cancellation/recovery, and
  scanner-exception tests.

**Verification:** SEC-15 through SEC-18 evidence is attached to the exact RC artifact; no open high
impact finding or unexplained suppression remains.

## Sprint handoff

Each slice must include migrations, rollback impact, tests, public/operations documentation, and
evidence-ledger updates. Do not combine SEC-2A and SEC-2B in one implementation.
