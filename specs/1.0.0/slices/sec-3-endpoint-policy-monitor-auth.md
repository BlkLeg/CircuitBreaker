# SEC-3 — Endpoint Policy and Monitor Authorization

**Requirements:** SEC-06, SEC-07, SEC-08
**Priority:** P0
**Depends on:** SEC-2A or SEC-2B

## Objective

Make the authorization posture of every externally reachable endpoint explicit and prevent anonymous,
wrong-role, or wrong-tenant access to monitor data and nested execution state.

## Primary touchpoints

- Router registration in `apps/backend/src/app/main.py`
- Routers under `apps/backend/src/app/api/`, especially `api/monitor.py`
- Auth dependencies/scopes in `apps/backend/src/app/core/security.py` and auth modules
- Monitor services and stream/probe paths under `apps/backend/src/app/services/`
- `apps/backend/tests/api/test_monitor_api.py`, `tests/test_auth*.py`, security tests

## Implementation sequence

1. Build a route-introspection tool from the FastAPI runtime table. Record method/path/transport,
   router, public reason, auth dependency, scope, tenant policy, and response disclosure class.
2. Store the reviewed public allowlist in a small checked-in data file. Health/startup/metrics and
   pre-auth endpoints still require explicit classifications.
3. Add a CI test that fails an unclassified route, a missing declared dependency, duplicate ambiguous
   policy, or an allowlisted path whose runtime signature changed.
4. Apply read scope and tenant-aware target lookup to monitor list, detail, history, events, probe
   runs, overview, summary, uptime, streams, and download/export surfaces.
5. Make wrong-tenant identifiers non-enumerable according to the approved 404/403 policy.
6. Add a parametrized matrix for anonymous, viewer, demo, editor, admin, masqueraded admin,
   expired/revoked session, wrong tenant, and agent identity across each endpoint class.
7. Include WebSocket/SSE connect and reconnect, query/header/cookie alternatives, and nested IDs.

## Verification

```bash
cd apps/backend
PYTHONPATH=src pytest -q --no-cov tests/api/test_monitor_api.py tests/test_auth.py \
  tests/test_auth_e2e.py tests/test_security.py
```

Also run the route-inventory reconciliation against the production app configuration and full
PostgreSQL suite. Retain the generated inventory as release evidence.

## Rollout and compatibility

Adding auth to previously exposed reads is an intentional breaking security correction. Document API
client impact and ensure UI calls already carry credentials/scopes. Do not keep an unauthenticated
compatibility alias.

## Definition of done

Runtime routes and the checked-in policy inventory match exactly, all monitor reads are protected,
and the complete identity matrix passes without cross-tenant disclosure.
