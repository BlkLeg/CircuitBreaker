# SEC-3 Endpoint Policy and Monitor Authorization Evidence

**Status:** Implementation complete; release-artifact verification still pending
**Generated:** 2026-08-11
**Requirements:** SEC-06, SEC-07, SEC-08
**Depends on:** SEC-2B
**Source state:** working tree based on `56e4bdd8`

## Implemented controls

- Added checked-in endpoint policy metadata at
  `apps/backend/src/app/security/endpoint_policy.json`.
- Added checked-in full runtime endpoint inventory at
  `apps/backend/src/app/security/endpoint_inventory.json`.
- Added reproducible inventory generator at
  `apps/backend/scripts/generate_endpoint_inventory.py`.
- Added runtime reconciliation tests in `apps/backend/tests/test_endpoint_policy_inventory.py`.
- Added SEC-07 review metadata to the public/protocol allowlist. The metadata identifies
  `security-owner`, the CODEOWNERS file, and the mapped GitHub owner used for required review.
- Added `.github/CODEOWNERS` coverage for the public endpoint allowlist, generated runtime
  inventory, inventory generator, route-policy tests, and SEC-3 evidence/slice docs.
- Updated `.github/branch-protection.md` to require Code Owner review before merging.
- The reconciliation gate fails if a FastAPI HTTP/WebSocket route lacks both:
  - an enforced auth dependency; and
  - a reviewed public/protocol policy entry.
- The gate also fails stale allowlist entries whose method/path/transport no longer exist at runtime.
- The full inventory gate fails if method, path, transport, endpoint name, dependency calls,
  auth/RBAC policy, tenant policy, or disclosure class drift from the runtime route table.
- The policy test also fails if the SEC-07 review metadata or CODEOWNERS mapping for
  `endpoint_policy.json` is removed or changed unexpectedly.
- Monitor read routes now declare explicit `require_role("viewer")` dependencies in
  `apps/backend/src/app/api/monitor.py`.
- Monitor API tests now cover:
  - anonymous users cannot read monitor list/detail/history/events/probe-runs/uptime/overview;
  - viewers can read monitor surfaces;
  - demo sessions can read monitor surfaces until expiry;
  - expired demo sessions, expired JWTs, revoked sessions, and agent-like bearer tokens are denied;
  - service API tokens can read through the normal authenticated path;
  - viewers cannot create monitors;
  - editors can create monitors.
- Monitor WebSocket tests cover unauthenticated handshake rejection and authenticated session-cookie
  connection/reconnect behavior.

## Current route-policy posture

The checked-in unauthenticated/protocol policy is intentionally narrow and includes:

- login, OAuth, MFA challenge, password reset, and bootstrap/OOBE flows;
- agent enrollment/link WebSockets that authenticate inside the Noise protocol;
- bounded public assets such as health, favicon, browser manifest, install script, and SPA fallback;
- compatibility auth endpoints that currently perform session checks inside handlers.

The `auth-internal` entries are explicitly reviewed compatibility routes. Moving those session checks
into standard FastAPI dependencies can shrink the public/protocol allowlist in a future hardening
pass, but SEC-3 now prevents any new unreviewed unauthenticated route from landing silently.

## Verification commands

```bash
cd apps/backend
pytest -q --no-cov tests/test_endpoint_policy_inventory.py \
  tests/api/test_monitor_api.py \
  tests/api/test_monitor_stream_auth.py \
  tests/test_auth.py \
  tests/test_auth_e2e.py \
  tests/test_security.py
ruff check scripts/generate_endpoint_inventory.py src/app/api/monitor.py \
  tests/test_endpoint_policy_inventory.py tests/api/test_monitor_api.py \
  tests/api/test_monitor_stream_auth.py
```

## Local SEC-07 verification

```bash
cd apps/backend
pytest -q --no-cov tests/test_endpoint_policy_inventory.py
ruff check scripts/generate_endpoint_inventory.py tests/test_endpoint_policy_inventory.py
```

Result: **PASS**, 4 endpoint-policy tests plus Ruff.

## Release-candidate evidence still pending

- Re-run the SEC-3 suite from the packaged release candidate.
- Retain the generated endpoint inventory and route-policy reconciliation output as RC evidence.
