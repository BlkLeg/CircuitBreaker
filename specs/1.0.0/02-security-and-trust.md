# 1.0.0 Security and Trust Specification

**Status:** Draft; release-blocking
**Priority:** P0

## Outcome

The production application enforces its declared identity, authorization, and tenant boundaries at
the API and database layers, fails safely when dependencies or secrets are unavailable, and ships
without unreviewed high-impact security findings.

## Tenant boundary

| ID | Requirement | Acceptance |
|---|---|---|
| SEC-01 | Decide whether multi-tenancy is a supported 1.0 security boundary. | Decision is recorded under RC-03 before implementation. |
| SEC-02 | If supported, tenant context is mandatory after login and established inside the request transaction; pooled connections cannot retain a previous tenant. | Tests cover missing/invalid context, connection reuse, concurrent tenants, workers, and admin override. |
| SEC-03 | The production application role must not bypass PostgreSQL RLS; policies are verified using that exact role. | Database adversarial suite proves isolation with production-equivalent grants and configuration. |
| SEC-04 | Application queries include tenant predicates as defense in depth for tenant-owned resources and nested relations. | Entity matrix proves read/create/update/delete/search/export and identifier enumeration isolation. |
| SEC-05 | If multi-tenancy is unsupported, tenant UI, routes, middleware, claims, and ambiguous configuration are removed or hard-disabled. | Anonymous and authenticated users cannot activate or infer a security boundary that is not provided. |

## Route and identity policy

| ID | Requirement | Acceptance |
|---|---|---|
| SEC-06 | Every HTTP, WebSocket, SSE, metrics, health, bootstrap, upload/download, and agent endpoint declares public/auth/RBAC/tenant policy. | Checked-in inventory is generated or validated in CI; unknown routes fail the gate. |
| SEC-07 | Public endpoints exist on a reviewed allowlist with disclosure rationale. | Adding a public route requires an allowlist diff and security-owner review. |
| SEC-08 | Monitor list/detail/history/events/probe-run/overview/summary/uptime and nested data require the correct read scope and tenant. | Authorization matrix passes for anonymous, viewer, demo, editor, admin, masqueraded admin, expired/revoked session, wrong tenant, and agent identity. |
| SEC-09 | Initial setup cannot expose an admin-equivalent race window. | One-time setup token or explicitly supported local/private bootstrap prevents competing first-admin creation. |
| SEC-10 | MFA, forced password change, lockout order, revocation, OAuth callback handling, CSRF/CORS/CSP, secure cookies, and proxy-aware identity are adversarially tested. | Tests run in every documented proxy/deployment topology and include WebSocket/SSE authentication. |

## Systemic security controls

| ID | Requirement | Acceptance |
|---|---|---|
| SEC-11 | Resolve `click 8.3.1` / `PYSEC-2026-2132` and scan all production dependency graphs. | pip-audit and other required scanners are green for the RC artifact. |
| SEC-12 | Outbound webhooks and integrations resist DNS-rebinding SSRF through address pinning or enforced egress policy. | Tests cover private/reserved targets, redirect chains, DNS answer changes, IPv4/IPv6 encodings, and every outbound integration. |
| SEC-13 | Rate limiting uses shared storage and trusts forwarded client identity only from configured proxies. | Multi-instance tests prove common limits; spoofed forwarding headers do not change identity. |
| SEC-14 | Missing or empty Redis, NATS, vault, signing, encryption, and session secrets fail closed where the feature requires them. | Fresh-install and dependency-loss tests prove no insecure fallback. |
| SEC-15 | Uploaded SVG and other active content is sanitized, rasterized, or rejected and served with safe content policy. | Malicious upload corpus cannot execute script or escape origin controls. |
| SEC-16 | Audit-chain writes serialize safely and verification/repair behavior is documented. | Concurrent-writer tests cannot fork the chain; tampering and repair procedures are exercised. |
| SEC-17 | Destructive actions have safeguards proportional to impact and produce audit events. | Clear-lab, wipe restore, tenant deletion, agent revoke/uninstall, and bulk import tests prove confirmation, authorization, and recoverability rules. |
| SEC-18 | CodeQL, Semgrep, Bandit, Trivy, Checkov, Gitleaks, npm audit, pip-audit, Go vulnerability, container, and secret scans pass or have RC-08 exceptions. | Reports are retained against the RC digest; suppressions include owner, reason, expiry, and compensating control. |

## Non-goals

- Counting green aggregate tests as proof of an untested security boundary.
- Using historical security reports as the current source of truth.
- Treating UI concealment as authorization.
