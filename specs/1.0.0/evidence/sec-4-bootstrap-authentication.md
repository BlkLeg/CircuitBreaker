# SEC-4 Bootstrap and Authentication Hardening Evidence

**Status:** Local implementation and verification complete; packaged RC verification still pending
**Generated:** 2026-08-11
**Requirements:** SEC-09, SEC-10
**Depends on:** SEC-3

## Implemented controls

- Added one-time setup-token storage to `app_settings`:
  - `bootstrap_token_hash`
  - `bootstrap_token_expires_at`
  - `bootstrap_token_used_at`
- Added migration `apps/backend/migrations/versions/0102_bootstrap_setup_token.py`.
- `/api/v1/bootstrap/status` now ensures a setup token exists before first-run setup:
  - operators can provide `CB_SETUP_TOKEN`;
  - otherwise a generated token is written to `CB_DATA_DIR/bootstrap-setup-token`;
  - the generated token file is written with `0600` permissions;
  - public status reports only that a token is required and its expiry, never the token value.
- `/api/v1/bootstrap/initialize` and `/api/v1/bootstrap/initialize-oauth` now require
  `setup_token`.
- Successful bootstrap consumes the token by clearing the stored hash/expiry and recording
  `bootstrap_token_used_at`.
- First-admin creation now serializes on the `app_settings` row with `SELECT FOR UPDATE`, and the
  locked row is force-refreshed so concurrent SQLAlchemy sessions cannot reuse stale
  pre-bootstrap state.
- OOBE now collects the setup token before account creation and sends it for both local and OAuth
  bootstrap completion.
- Agent E2E bootstrap helper now reads `CB_SETUP_TOKEN` or the generated private token file when it
  initializes a fresh stack.
- `/api/v1/events/stream` now requires viewer-or-higher authentication before opening the SSE
  response; anonymous and revoked sessions are rejected on connect/reconnect.
- Monitor WebSocket reconnect now rejects a revoked session before streaming resumes.
- Session and CSRF cookies now treat `X-Forwarded-Proto: https` as TLS termination for the
  `Secure` flag, matching the existing HSTS proxy detection path.
- Security tests now pin:
  - secure/strict cookie flags behind a TLS-terminating proxy;
  - CSP, frame, nosniff, and HSTS headers behind a TLS-terminating proxy;
  - CSRF rejection for cookie-authenticated mutations with missing or mismatched CSRF headers;
  - hostile CORS origins not being reflected.

## Covered cases

- Missing setup token is rejected before bootstrap initializes.
- Wrong setup token is rejected and creates no user.
- Correct setup token creates exactly one admin and consumes the token.
- Replay after successful bootstrap receives the already-completed bootstrap response.
- `/bootstrap/status` generates a private token file when no operator-provided token exists.
- Two simultaneous PostgreSQL-backed bootstrap attempts with the same valid setup token produce
  exactly one admin; the loser receives `409 Bootstrap already completed`.
- SSE anonymous access is rejected, viewer access connects, and revoked sessions cannot reconnect.
- Monitor WebSocket session-cookie access connects, and revoked sessions cannot reconnect.
- Existing auth/security tests continue to cover password policy, force-change, MFA, lockout,
  logout/revocation, CSRF/CORS/CSP, secure cookies, and session expiry behavior at the current
  backend test boundary.

## Verification commands

```bash
cd apps/backend
pytest -q --no-cov tests/test_bootstrap_security.py tests/test_bootstrap_domain.py \
  tests/test_auth.py tests/test_auth_e2e.py tests/test_security.py tests/test_settings.py \
  tests/api/test_events_stream_auth.py tests/api/test_monitor_stream_auth.py \
  tests/test_endpoint_policy_inventory.py
ruff check src/app/api/bootstrap.py src/app/services/auth_service.py src/app/schemas/auth.py \
  src/app/db/models.py src/app/api/events.py src/app/core/auth_cookie.py \
  tests/test_bootstrap_security.py tests/api/test_events_stream_auth.py \
  tests/api/test_monitor_stream_auth.py tests/test_security.py \
  migrations/versions/0102_bootstrap_setup_token.py
CB_DB_URL=postgresql://breaker:test@127.0.0.1:5432/circuitbreaker PYTHONPATH=src alembic heads

cd ../frontend
npm run lint -- --quiet
npm run test -- src/__tests__/oobe-wizard.test.jsx
npx prettier --check src/pages/OOBEWizardPage.jsx src/__tests__/oobe-wizard.test.jsx
```

## Release-candidate evidence still pending

- Repeat the authentication and bootstrap suite against the packaged release candidate.
- Retain packaged mono/split/proxy deployment output as RC evidence for the local request-layer
  cases already covered above.
