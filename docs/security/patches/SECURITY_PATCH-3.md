# Security Hardening Report — CircuitBreaker v0.2.2

**Date:** 2026-03-13
**Scope:** End-to-end security hardening of the CircuitBreaker monolith
**Status:** Applied and verified in production container

---

## Summary

This report documents all security hardening changes applied to CircuitBreaker as part of the
pre-flight security review. Changes span authentication, CSRF protection, API token storage,
WebSocket auth, container runtime validation, secrets scanning, and frontend request security.
All fixes were driven by audit findings and the security regression test suite defined in
`PROMPT.md`.

---

## 1. JWT Secret — Mandatory Startup Validation

**Problem:** The app could start without a JWT secret, falling back to an empty or weak
signing key. A weak/shared JWT secret allows token forgery.

**Changes — `docker/entrypoint-mono.sh` (lines 23–38):**
- Added hard-fail validation on startup:

  - `CB_JWT_SECRET` must be set
  - Minimum 32 characters
  - Must not equal `"CHANGE_ME"`
  - Must differ from `CB_VAULT_KEY` (prevents key reuse across subsystems)
- On failure: prints generation command and exits with code 1 (blocking container start)

**Changes — `docker/docker-compose.yml` and `docker/docker-compose.prod.yml`:**
- `CB_JWT_SECRET` added to `environment:` block with `:?` interpolation
  (`${CB_JWT_SECRET:?Set CB_JWT_SECRET}`) so `docker compose up` fails loudly if unset
- `NATS_AUTH_TOKEN` added with same mandatory pattern

**Fix applied during session:** `CB_JWT_SECRET` was not being forwarded into the container
because it was absent from the `environment:` block. Value was in root `.env` instead of
`docker/.env` (the project directory Compose actually reads). Both gaps corrected.

---

## 2. CSRF Protection — Double-Submit Cookie Pattern

**Problem:** All mutating API endpoints (POST, PUT, PATCH, DELETE) were vulnerable to
Cross-Site Request Forgery. Any page could silently trigger writes against an authenticated session.

**Changes — `apps/backend/src/app/middleware/csrf.py` (new file):**
- `CSRFMiddleware` added to the FastAPI middleware stack
- Cookie `cb_csrf`: 64-char hex token (`secrets.token_hex(32)`), non-HttpOnly (readable
  by JS), Secure, SameSite=Strict
- Header `X-CSRF-Token`: must match cookie value on all mutating requests
- Comparison: `hmac.compare_digest()` (timing-safe)
- Middleware only activates for authenticated requests (presence of `cb_session` cookie)
- Exempted public endpoints: `/auth/login`, `/auth/register`, `/auth/demo`,
  `/auth/accept-invite`, `/auth/vault-reset`, `/auth/force-change-password`,
  `/auth/mfa/verify`, `/health`

**Changes — `apps/backend/src/app/core/auth_cookie.py`:**
- `auth_response_with_cookie()` now generates and sets both cookies on every login
- Session cookie `cb_session`: HttpOnly, Secure, SameSite=Strict
- CSRF cookie `cb_csrf`: same Secure/SameSite settings, HttpOnly=False

**Changes — `apps/frontend/src/api/client.jsx`:**
- Added `getCookie(name)` helper to read `cb_csrf` from `document.cookie`
- Added request interceptor logic: injects `X-CSRF-Token` header on all POST, PUT,
  PATCH, DELETE requests using the cookie value
- No new dependencies; fully contained in the existing axios interceptor

---

## 3. JWT Audience Validation — Token Type Confusion Prevention

**Problem (C-03):** A password-reset or MFA token signed with the same secret could be
replayed as a session token against authenticated endpoints.

**Changes — `apps/backend/src/app/core/security.py`:**
- `SESSION_AUDIENCE = "fastapi-users:auth"` required on all session JWTs
- `decode_token()` and `get_optional_user()` both validate `audience=[SESSION_AUDIENCE]`
- Tokens with any other audience (`cb:change-password`, `cb:mfa`, blank, etc.) are rejected
- Separate audiences enforced per token type, preventing cross-purpose replay

---

## 4. API Token Security — Salted HMAC Hashing

**Problem:** Legacy API tokens were stored as unsalted HMAC-SHA256(secret, token), allowing
bulk precomputation attacks if the database is compromised.

**Changes — `apps/backend/src/app/core/security.py`:**
- New function `create_salted_api_token_hash(raw_token)`:
  - Salt: 32 random bytes (`os.urandom(32)`)
  - Storage format: `{salt_hex}:{hmac_hex}`
  - Algorithm: HMAC-SHA256(salt, raw_token)
- New function `verify_salted_api_token_hash(raw_token, stored)`:
  - Extracts salt from stored value, recomputes HMAC
  - Uses `hmac.compare_digest()` for timing-safe comparison
  - Returns `False` for legacy unsalted hashes (no `:` separator)
- Legacy function `hash_api_token()` retained read-only for migration compatibility

---

## 5. Session Validation Cache — Revocation Effectiveness

**Problem:** Without a cache TTL, revoked sessions could continue working until the next
request hit the DB. With a long-lived cache, revocation is delayed.

**Changes — `apps/backend/src/app/core/security.py`:**
- In-memory cache: `token_hash → (user_id, expiry_ts)`
- Cache key: SHA256(raw_token) — never stores raw tokens in memory
- TTL: 10 seconds (balances DB load vs revocation latency)
- Max size: 2000 entries; LRU-style eviction on overflow
- Thread-safe: `threading.Lock()` guards all read/write operations
- `invalidate_session_cache(token)` removes a specific token on logout
- `invalidate_session_cache(None)` clears all entries on bulk revocation

---

## 6. WebSocket Authentication — Token-First Protocol

**Problem:** WebSocket endpoints previously lacked authentication, allowing unauthenticated
clients to subscribe to topology and discovery event streams.

**Changes — `apps/backend/src/app/api/ws_discovery.py` and `ws_topology.py`:**
- Authentication protocol: client must send a raw JWT as the first WebSocket message
  within 10 seconds of connecting
- Token validated via `decode_token()` with full audience and expiry checking
- On failure: server sends `{"error": "unauthorized"}` then closes with code 1008 (Policy Violation)
- On success: server sends `{"status": "connected"}` and begins event streaming

**DoS Protections (both endpoints):**
- Global connection cap: `CB_WS_MAX_CONNECTIONS` (default 50)
- Per-IP connection limit: `CB_WS_MAX_PER_IP` (default 5)
- Client IP via `X-Forwarded-For` (trusted from nginx reverse proxy)
- Auth timeout: 10-second deadline, explicit close on timeout

---

## 7. NATS Message Bus — Authenticated Internal Bus

**Problem:** NATS internal message bus had no authentication, allowing any process in the
container network to publish or subscribe to internal events.

**Changes — `apps/backend/src/app/core/nats_client.py`:**
- `NATS_AUTH_TOKEN` required via environment variable
- Fallback: `NATS_USER` / `NATS_PASSWORD` basic auth
- TLS support: `NATS_TLS=true` converts `nats://` to `tls://`
- Mandatory token enforced in `docker-compose.yml` via `:?` interpolation

---

## 8. Container Hardening — Non-Root Execution

**Changes — `docker/docker-compose.yml`:**
- `security_opt: no-new-privileges:true` — prevents privilege escalation via setuid
- `cap_drop: ALL` with minimal `cap_add`:
  - `NET_RAW`, `NET_BIND_SERVICE` (networking)
  - `CHOWN`, `FOWNER`, `SETUID`, `SETGID`, `DAC_OVERRIDE` (file/user management only)
- `read_only: true` root filesystem with explicit `tmpfs` mounts
- Resource limits: 2 CPUs, 1 GB RAM (prevents resource exhaustion DoS)

**Runtime — `docker/entrypoint-mono.sh`:**
- All app processes run as `breaker` (non-root uid 1000)
- Docker socket access: group-based only (`docker-host` group), not world-readable
- Redis password auto-generated at startup (`CB_REDIS_PASSWORD`), stored at
  `$DATA/.redis_pass` (mode 600)
- PgBouncer userlist generated from `CB_DB_PASSWORD` at startup (not hardcoded)

---

## 9. Secrets Scanning — Gitleaks Configuration

**Problem:** The old `.gitleaks.toml` used deprecated v7 `[allowlist]` syntax, causing
scanner failures and missing active rules.

**Changes — `.gitleaks.toml`:**
- Migrated to v8 `[[allowlists]]` format
- Added named allowlist `third-party-venv-example-tokens`: suppresses example JWTs
  embedded in FastAPI-Users library files under `.venv/`
- Added named allowlist `runtime-tls-certs`: suppresses self-signed TLS certificates in
  `docker/data/tls/` and `docker/circuitbreaker-data/tls/` (never committed secrets)
- Alembic migration revision IDs suppressed (hex strings misidentified as tokens)

---

## 10. Security Scan Automation

**Changes — `scripts/security_scan.sh`:**
- Integrates Bandit (Python SAST), Semgrep (multi-language SAST), Gitleaks (secret
  detection), and Trivy (container/filesystem CVE scanning)
- All scans respect `.trivyignore` for accepted false positives
- Output: `security_scan_report.md` for CI artifact upload
- GitHub Actions workflow (`.github/workflows/test.yml`) runs security subset on every
  push to `main`, `dev`, `feature/*`, `hotfix/*`

---

## 11. Regression Test Suite

**Changes — `apps/backend/tests/`:**
Per `PROMPT.md`, a full backend test suite was written covering:
- `test_security.py`: one test per audit finding (C-01 through M-17), all marked
  `@pytest.mark.security` — build fails if any security test fails
- `test_auth.py`: login timing oracle, expired JWT, wrong-audience token, logout
  invalidation, MFA lockout
- All tests run against real PostgreSQL (testcontainers-python) — no mocked DB
- Coverage threshold: 75% (`--cov-fail-under=75`)
- CI timeout: 30 seconds per test, 20 minute total job limit

Key security regression tests:
| Finding | Test | Assertion |
|---------|------|-----------|
| C-01 | `test_c01_nmap_shell_metacharacters_rejected` | 8 shell-injection payloads → 422 |
| C-02 | `test_c02_snmp_community_invalid_chars_rejected` | 6 bad SNMP strings → 422 |
| C-03 | `test_c03_wrong_audience_rejected` | 5 wrong-aud JWTs → 401 |
| C-05 | `test_c05_oauth_tokens_stored_encrypted` | DB value starts with `gAAAAA` |
| C-07 | `test_c07_webhook_ssrf_blocked` | 11 SSRF URLs → 422 |
| C-08 | `test_c08_proxmox_ssrf_blocked` | 3 private Proxmox URLs → 422 |
| H-07 | `test_vault_startup_failure_exits` | Invalid vault key → `SystemExit(1)` |
| H-10 | `test_mfa_brute_force_locked_after_5_attempts` | 6th attempt → 429 |
| H-12 | `test_h12_path_traversal_rejected` | `../../etc/cron.d/evil.png` → 422 |
| H-14 | `test_h14_telemetry_credentials_masked_in_response` | No plaintext in GET response |
| M-17 | `test_m17_cidr_too_broad_rejected` | `/8` CIDR → 422 |

---

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `apps/backend/src/app/middleware/csrf.py` | New | CSRF double-submit middleware |
| `apps/backend/src/app/core/auth_cookie.py` | Modified | HttpOnly + CSRF cookie on login |
| `apps/backend/src/app/core/security.py` | Modified | JWT audience, salted tokens, session cache |
| `apps/backend/src/app/core/nats_client.py` | Modified | NATS auth token support |
| `apps/backend/src/app/api/auth.py` | Modified | Cookie-based login response |
| `apps/backend/src/app/api/admin_users.py` | Modified | RBAC enforcement hardening |
| `apps/backend/src/app/api/ws_discovery.py` | Modified | WebSocket auth + DoS limits |
| `apps/backend/src/app/api/ws_topology.py` | Modified | WebSocket auth + DoS limits |
| `apps/backend/src/app/main.py` | Modified | CSRFMiddleware registration |
| `apps/frontend/src/api/client.jsx` | Modified | CSRF token injection in interceptor |
| `docker/entrypoint-mono.sh` | Modified | CB_JWT_SECRET / CB_VAULT_KEY validation |
| `docker/docker-compose.yml` | Modified | Mandatory secrets, container hardening |
| `docker/docker-compose.prod.yml` | Modified | Mandatory secrets propagation |
| `.gitleaks.toml` | Modified | v8 format, false-positive allowlists |
| `scripts/security_scan.sh` | Modified | SAST + secret scan automation |
| `.github/workflows/test.yml` | New | CI pipeline with security test gate |
| `apps/backend/tests/` | New | Full regression test suite (14 files) |
