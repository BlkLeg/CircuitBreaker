# SEC-4 — Bootstrap and Authentication Hardening

**Requirements:** SEC-09, SEC-10
**Priority:** P0
**Depends on:** SEC-3 route policy

## Objective

Eliminate the first-admin race and prove authentication/session controls across REST, WebSocket, SSE,
OAuth, MFA, and every supported proxy topology.

## Primary touchpoints

- `apps/backend/src/app/api/bootstrap.py`, `api/auth.py`, `api/auth_oauth.py`
- Auth/security configuration in `apps/backend/src/app/core/`
- Router/middleware order in `apps/backend/src/app/main.py`
- `apps/frontend/src/components/auth/` and auth API/session state
- `apps/backend/tests/test_auth.py`, `test_auth_e2e.py`, `test_security.py`
- `apps/frontend/src/__tests__/` authentication tests

## Implementation sequence

1. Choose one-time token or approved local/private binding. Define generation, storage, display,
   expiry, single use, restart, failed attempt, replay, and recovery semantics.
2. Serialize first-admin creation at the database boundary so simultaneous valid requests yield one
   winner and an unambiguous result for all others.
3. Audit middleware ordering and session issuance around incomplete OOBE.
4. Build cases for password policy, forced change, MFA enrollment/challenge/recovery codes, lockout
   ordering, session expiry/revocation, logout, masquerade, and credential reset.
5. Verify OAuth state/nonce/callback code single use, provider errors, redirects, and account linking.
6. Verify CSRF/CORS/CSP, secure/SameSite cookies, HTTPS detection, trusted proxy identity, and public
   status disclosure in native, mono, and split proxy topologies.
7. Repeat token/session revocation and authorization for WebSocket/SSE connect and reconnect.

## Verification

```bash
cd apps/backend
PYTHONPATH=src pytest -q --no-cov tests/test_auth.py tests/test_auth_e2e.py \
  tests/test_security.py tests/test_settings.py tests/test_bootstrap_domain.py
```

Run frontend auth tests and browser E2E through each documented proxy topology. Include a real
concurrent PostgreSQL first-admin test; sequential mocks cannot prove race prevention.

## Rollout and recovery

Existing initialized systems must not re-enter bootstrap. Fresh installs require a recoverable,
documented token delivery path that does not log the token broadly. Define operator recovery when the
token is lost without reopening an unauthenticated window.

## Definition of done

Only one authorized first admin can be created, all session controls work across transports, and proxy
configuration cannot weaken identity or cookie security.
