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
- `/api/v1/bootstrap/status` now fails closed instead of hiding explicit setup-token provisioning
  errors such as a too-short `CB_SETUP_TOKEN`.
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
- `/api/v1/auth/login` now checks active lockout before issuing force-password-change or MFA
  challenge tokens, so a locked user cannot bypass lockout by presenting the correct password.
- Security tests now pin:
  - force-password-change and MFA challenge tokens are not accepted as full session tokens;
  - MFA backup-code login consumes each backup code exactly once;
  - OAuth callback state is single-use and expired states are consumed;
  - OIDC authorization persists nonce plus PKCE verifier material before redirect;
  - proxy-aware client identity honors `X-Forwarded-For` only from configured trusted proxy CIDRs;
  - secure/strict cookie flags behind a TLS-terminating proxy;
  - CSP, frame, nosniff, and HSTS headers behind a TLS-terminating proxy;
  - CSRF rejection for cookie-authenticated mutations with missing or mismatched CSRF headers;
  - hostile CORS origins not being reflected.

## Covered cases

- Missing setup token is rejected before bootstrap initializes.
- Wrong setup token is rejected and creates no user.
- Correct setup token creates exactly one admin and consumes the token.
- Replay after successful bootstrap receives the already-completed bootstrap response.
- Failed wrong-token attempts preserve the existing setup token and a later correct-token retry can
  still create the first admin.
- Expired generated tokens are rejected, replaced with a fresh private token file, and cannot create
  a user.
- `/bootstrap/status` generates a private token file when no operator-provided token exists.
- Operator-provided `CB_SETUP_TOKEN` values are hashed into storage, are not written to the generated
  token file, and are not disclosed in the public status response.
- Invalid operator-provided setup tokens fail closed with `503` and do not create users.
- Two simultaneous PostgreSQL-backed bootstrap attempts with the same valid setup token produce
  exactly one admin; the loser receives `409 Bootstrap already completed`.
- The setup-token workflow, expiry, single-use, replay, and recovery semantics are documented in
  `docs/installation/first-run.md` and `docs/installation/configuration.md`.
- SSE anonymous access is rejected, viewer access connects, and revoked sessions cannot reconnect.
- Monitor WebSocket session-cookie access connects, and revoked sessions cannot reconnect.
- Locked force-change and MFA users receive no challenge token until lockout expires.
- Force-change and MFA challenge tokens are rejected by normal protected APIs because they carry a
  non-session audience.
- Backup-code MFA login succeeds once, consumes the code, and rejects replay.
- OAuth callback states are popped on first use; expired states are also consumed so they cannot be
  replayed later.
- OIDC authorization stores a nonce and PKCE verifier and sends the nonce in the provider redirect.
- Trusted proxy identity uses the first valid `X-Forwarded-For` value only when the socket peer is
  configured as trusted; untrusted peers cannot spoof identity with forwarding headers.
- Existing auth/security tests cover password policy, force-change, MFA enrollment, backup-code
  storage, lockout, logout/revocation, CSRF/CORS/CSP, secure cookies, and session expiry behavior at
  the current backend test boundary.

## Verification commands

```bash
cd apps/backend
pytest -q --no-cov tests/test_bootstrap_security.py
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

Current SEC-09 local verification:

```bash
pytest -q --no-cov apps/backend/tests/test_bootstrap_security.py
```

Result: **PASS**, 8 tests.

Current bootstrap/auth regression verification:

```bash
pytest -q --no-cov apps/backend/tests/test_bootstrap_security.py \
  apps/backend/tests/test_bootstrap_domain.py apps/backend/tests/test_auth.py \
  apps/backend/tests/test_auth_e2e.py apps/backend/tests/test_security.py \
  apps/backend/tests/test_settings.py
```

Result: **PASS**.

Current SEC-10 adversarial verification:

```bash
pytest -q --no-cov apps/backend/tests/test_sec10_auth_controls.py
```

Result: **PASS**, 10 tests.

Current SEC-10 combined backend verification:

```bash
pytest -q --no-cov apps/backend/tests/test_sec10_auth_controls.py \
  apps/backend/tests/test_auth.py apps/backend/tests/test_auth_e2e.py \
  apps/backend/tests/test_security.py apps/backend/tests/test_settings.py \
  apps/backend/tests/api/test_events_stream_auth.py \
  apps/backend/tests/api/test_monitor_stream_auth.py
```

Result: **PASS**.

Current frontend OOBE/OAuth verification:

```bash
cd apps/frontend
npm run test -- src/__tests__/oobe-wizard.test.jsx src/__tests__/oauth-providers-manager.test.jsx
```

Result: **PASS**, 2 files / 9 tests.

Current lint and release-control verification:

```bash
ruff check apps/backend/src/app/services/auth_service.py apps/backend/tests/test_bootstrap_security.py
ruff check apps/backend/src/app/api/auth.py apps/backend/tests/test_sec10_auth_controls.py
python3 scripts/validate_v1_release_control.py
```

Result: **PASS**.

## Release-candidate evidence still pending

- Repeat the authentication and bootstrap suite against the packaged release candidate.
- Retain packaged mono/split/proxy deployment output as RC evidence for the local request-layer
  cases already covered above.
