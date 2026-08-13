# SEC-3 Endpoint Policy and Monitor Authorization Evidence

**Status:** Implementation complete; release-artifact verification still pending
**Generated:** 2026-08-11
**Requirements:** SEC-06, SEC-07, SEC-08
**Depends on:** SEC-2B
**Source state:** working tree based on `79f9a0b8`

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
- The full inventory now includes mounted static/file surfaces separately from FastAPI routes:
  uploads, user icons, branding assets, and conditional frontend `/assets` and `/icons` mounts.
  The gate fails if a runtime static mount lacks a reviewed public disclosure policy.
- The policy test also fails if the SEC-07 review metadata or CODEOWNERS mapping for
  `endpoint_policy.json` is removed or changed unexpectedly.
- Monitor read routes now require `require_scope("read", "*")`, so scoped API/service tokens must
  carry read authority instead of inheriting the token owner's role.
- API token scope state is propagated through `get_optional_user`/RBAC for both stored bearer
  tokens and service-account JWTs.
- Legacy tenant-tagged monitor targets are non-enumerable across mismatched tenant readers:
  list/overview/target-summary omit inaccessible rows and monitor-id nested reads return 404.
- Monitor API tests now cover:
  - anonymous users cannot read monitor list/detail/history/events/probe-runs/uptime/overview;
  - viewers, editors, admins, and unexpired demo sessions can read every named monitor surface;
  - expired demo sessions, expired JWTs, revoked sessions, and agent-like bearer tokens are denied
    across every named monitor surface;
  - stored API tokens and service-account JWTs without `read:*` are denied across every named
    monitor surface;
  - `read:*` service API tokens can read every named monitor surface;
  - wrong-tenant upgraded targets are hidden from list/overview/target-summary and return 404 for
    detail/history/events/probe-runs/uptime;
  - viewers cannot create monitors;
  - editors can create monitors.
- Monitor WebSocket subscriptions authorize every requested monitor ID with the same read-scope and
  legacy-tenant policy used by HTTP monitor reads. Inaccessible IDs are filtered, not enumerated.
- Monitor WebSocket tests cover unauthenticated handshake rejection, authenticated session-cookie
  connection/reconnect behavior, revoked session reconnect denial, wrong-tenant subscription
  filtering, service JWT read-scope enforcement, write-only service JWT denial, and expired-demo
  identity denial.

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

## Local SEC-08 verification

```bash
cd apps/backend
pytest -q --no-cov tests/api/test_monitor_api.py tests/api/test_monitor_stream_auth.py \
  tests/test_endpoint_policy_inventory.py
ruff check src/app/core/security.py src/app/core/rbac.py src/app/api/monitor.py \
  src/app/services/monitor_service.py tests/api/test_monitor_api.py \
  tests/api/test_monitor_stream_auth.py tests/test_endpoint_policy_inventory.py \
  scripts/generate_endpoint_inventory.py
PYTHONPATH=src ../../.venv/bin/mypy src/app
cd ../..
python3 scripts/validate_v1_release_control.py
```

Result: **PASS**, monitor API/stream authorization cases plus endpoint inventory, Ruff, mypy, and
release-control validation. The latest local rerun covered endpoint inventory, SEC-2B tenant
contract, monitor API, monitor stream auth, bootstrap security, SEC-10 auth controls, and events SSE
auth.

Masqueraded-admin identity remains not applicable in the current runtime: the model still has
historical masquerade fields, but there is no active route, transport claim, or request marker that
can create a masqueraded session. SEC-08 coverage should be extended if that feature is re-enabled.

## Release-candidate evidence still pending

- Re-run the SEC-3 suite from the packaged release candidate.
- Retain the generated endpoint inventory and route-policy reconciliation output as RC evidence.
