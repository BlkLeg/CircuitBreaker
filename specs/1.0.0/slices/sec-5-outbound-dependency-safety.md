# SEC-5 — Outbound and Dependency Safety

**Requirements:** SEC-11, SEC-12, SEC-13, SEC-14
**Priority:** P0
**Depends on:** SEC-1; may run parallel to endpoint work

## Objective

Close the known dependency advisory, prevent outbound SSRF including DNS rebinding, make limits
consistent across instances, and eliminate insecure missing-secret/dependency fallback.

## Primary touchpoints

- Python dependency manifests/locks and `.github/workflows/security.yml`
- Webhook/integration services under `apps/backend/src/app/services/`
- `apps/backend/src/app/core/rate_limit.py`
- `apps/backend/src/app/middleware/rate_limit_middleware.py`
- `apps/backend/src/app/core/config.py`, credential vault, startup validation in `main.py`
- Redis/NATS configuration under `deploy/config/` and installation examples

## Implementation sequence

1. Upgrade or constrain Click to a nonvulnerable version, regenerate locks if present, run dependency
   compatibility tests, and retain the resolved advisory report.
2. Inventory every server-side outbound URL and redirect-capable client. Centralize parsing,
   normalization, scheme/port policy, DNS resolution, IP classification, redirect validation, and
   connection address pinning or mandatory egress proxy.
3. Test IPv4/IPv6 literals and encodings, private/reserved/link-local/metadata targets, mixed DNS
   answers, rebinding between validation/connect, redirects, and proxy behavior.
4. Make application rate limits use shared Redis atomic operations with explicit unavailable behavior.
   Derive identity from forwarding headers only for configured trusted proxies.
5. Inventory Redis, NATS, vault, signing, encryption, and session dependencies/secrets. Define startup
   fail, readiness fail, or documented degradation per feature; empty equals missing.
6. Add startup/config validation and operator-facing errors without logging secret material.

## Verification

```bash
python -m pip_audit
cd apps/backend
PYTHONPATH=src pytest -q --no-cov tests -k 'webhook or ssrf or rate_limit or vault or secret'
```

Use a multi-process/multi-instance integration topology for shared limits and a controllable DNS
server for rebinding. Monkeypatched resolver-only tests are insufficient for the final gate.

## Rollout and rollback

Document required Redis/proxy/secret configuration before enabling strict startup validation. Provide
a preflight command. Do not roll back to known-vulnerable or fail-open behavior; use an RC-08 exception
only with explicit compensating network controls and expiry.

## Definition of done

The advisory is closed, all outbound clients share the hardened policy, multi-instance limits agree,
and missing critical dependencies or secrets cannot create an insecure operating mode.
