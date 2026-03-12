---
name: cb-security-hardening
description: Enforces Circuit Breaker security hardening conventions across backend, frontend, Docker, and nginx. Use when modifying authentication logic, security headers, Docker configuration, credential handling, session management, URL validation, WebSocket auth, or any code in core/security.py, core/rbac.py, middleware/security_headers.py, url_validation.py, docker-compose.yml, nginx.mono.conf, entrypoint-mono.sh, or supervisord.mono.conf.
---

# Circuit Breaker — Security Hardening Conventions

Codified from SECURITY_STANDING-1.md and SECURITY_STANDING-2.md audit reports.

## 1. Authentication Is Always Enforced

Authentication cannot be disabled after OOBE. The `auth_enabled` column on `AppSettings` is a **one-way OOBE completion marker** only.

**Rules:**
- Never add a code path that skips auth when `auth_enabled` is `False` post-bootstrap
- `get_optional_user` returns `None` only when no `jwt_secret` exists (pre-OOBE)
- `require_write_auth` always raises `401` when `user_id is None`
- `require_role` / `require_scope` in `core/rbac.py` never return a synthetic admin for unauthenticated requests
- WebSocket handlers (`ws_discovery.py`, `ws_status.py`, `ws_telemetry.py`) must validate JWT — no anonymous sentinel when `auth_enabled` is `False`
- The `AppSettingsUpdate` schema must not include `auth_enabled`
- Frontend `AuthContext` has no `authEnabled` state or `setAuthEnabled` — auth is always on
- Frontend route gating: `!isAuthenticated` redirects to `/login` (not `authEnabled && !isAuthenticated`)

## 2. Timing-Safe Token Comparison

All sensitive token comparisons must use `hmac.compare_digest`, never `==`.

```python
# Correct
import hmac
if api_token and raw_token and hmac.compare_digest(raw_token, api_token):
    return 0

# Wrong — timing side-channel
if api_token and raw_token == api_token:
    return 0
```

**Applies to:** `CB_API_TOKEN`, any bearer token comparison, webhook signature verification.

## 3. Session Revocation on Password Change

When a user changes their password, all other active sessions must be revoked.

```python
from app.services.user_service import _hash_token, revoke_all_sessions

token = _extract_token(request)
except_hash = _hash_token(token) if token else None
revoke_all_sessions(db, user_id, except_token_hash=except_hash)
```

An audit log entry (`action="password_changed"`) must also be written.

## 4. SSRF Prevention — URL Scheme Validation

`core/url_validation.py` must reject all non-HTTP(S) schemes before any IP resolution:

```python
_ALLOWED_SCHEMES = frozenset({"http", "https"})

scheme = (parsed.scheme or "").lower()
if scheme not in _ALLOWED_SCHEMES:
    raise ValueError(f"URL scheme '{scheme}' is not allowed.")
```

This blocks `file://`, `gopher://`, `ftp://`, `dict://`, etc.

## 5. Security Headers

All responses must include these headers (set in both `middleware/security_headers.py` and `nginx.mono.conf`):

| Header | Value |
|--------|-------|
| Content-Security-Policy | `default-src 'self'; script-src 'self' 'unsafe-inline' 'strict-dynamic'; ...` |
| X-Content-Type-Options | `nosniff` |
| X-Frame-Options | `DENY` |
| Referrer-Policy | `strict-origin-when-cross-origin` |
| Strict-Transport-Security | `max-age=63072000; includeSubDomains` |
| Permissions-Policy | `camera=(), microphone=(), geolocation=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()` |

**Rules:**
- `'strict-dynamic'` must remain in `script-src` to progressively override `'unsafe-inline'`
- Never remove `frame-ancestors 'none'` from CSP
- Never weaken `X-Frame-Options` from `DENY`

## 6. Transport Security — HTTPS Redirect

`nginx.mono.conf` must have two server blocks:

1. **Port 80** — returns `301` redirect to `https://` for all paths except `/api/v1/health` (exempt for Docker healthchecks)
2. **Port 443** — main HTTPS server with TLS termination

Never serve application content over plain HTTP.

## 7. Docker Socket Isolation

The Docker socket is **not mounted by default** in `docker-compose.yml`.

**Opt-in methods:**
1. Override file: `docker compose -f docker-compose.yml -f docker-compose.socket.yml up -d`
2. TCP proxy: set `CB_DOCKER_HOST=tcp://proxy:2375`

Backend Docker discovery code (`docker_discovery.py`, `discovery_safe.py`) must check `CB_DOCKER_HOST` env var first, falling back to the local socket only if present.

## 8. Container Filesystem Immutability

`docker-compose.yml` must specify:

```yaml
read_only: true
tmpfs:
  - /tmp:size=100M
  - /run:size=10M
  - /var/log:size=50M
  - /var/lib/nginx:size=10M
  - /var/lib/postgresql:size=10M
```

Only `/data` is a persistent writable bind mount. Never add writable volume mounts without explicit justification.

## 9. Redis Authentication

Embedded Redis must use `--requirepass`. The password is:
- Auto-generated at first container start (`openssl rand -base64 32`) to `/data/.redis_pass`
- Injected into `CB_REDIS_URL` by `entrypoint-mono.sh` when not user-supplied
- Read by `supervisord.mono.conf` at Redis process start

Never run Redis without `requirepass` inside the container.

## 10. Vault Key Rotation

The Fernet vault key auto-rotates via an APScheduler daily job (04:30):
- Reads `vault_key_rotation_days` (default 90) and `vault_key_rotated_at` from `AppSettings`
- Calls `rotate_vault_key()` which re-encrypts all credentials, persists the new key, and hot-swaps the in-memory vault

When modifying vault-related code, ensure the rotation path remains functional and tested.

## 11. Mandatory Secrets

`docker-compose.yml` must fail-fast on missing secrets:

```yaml
environment:
  - CB_DB_PASSWORD=${CB_DB_PASSWORD:?Set CB_DB_PASSWORD}
  - CB_VAULT_KEY=${CB_VAULT_KEY:?Set CB_VAULT_KEY}
  - NATS_AUTH_TOKEN=${NATS_AUTH_TOKEN:?Set NATS_AUTH_TOKEN for internal bus auth}
```

Never remove the `:?` error syntax. Never add defaults for secret values.

## 12. Capability Restrictions

Docker containers must run with:

```yaml
security_opt:
  - no-new-privileges:true
cap_drop:
  - ALL
cap_add:
  - NET_RAW
  - NET_BIND_SERVICE
  - CHOWN
  - SETUID
  - SETGID
  - DAC_OVERRIDE
```

Never add capabilities without documenting why.

## Validation Checklist

When reviewing security-sensitive changes:

- [ ] No `==` for token/secret comparison — use `hmac.compare_digest`
- [ ] No code path allows unauthenticated writes post-OOBE
- [ ] WebSocket handlers validate JWT (no anonymous bypass)
- [ ] URL inputs validate scheme is HTTP(S) only
- [ ] All security headers present in both middleware and nginx
- [ ] Docker socket not mounted in default compose
- [ ] `read_only: true` on container, only `/data` writable
- [ ] Redis uses `requirepass`
- [ ] Secrets use `${VAR:?error}` in compose — no defaults
- [ ] Password changes revoke other sessions
- [ ] Vault rotation scheduler job intact

## Reference

- [SECURITY_STANDING-1.md](../../../SECURITY_REPORTS/SECURITY_STANDING-1.md) — initial audit
- [SECURITY_STANDING-2.md](../../../SECURITY_REPORTS/SECURITY_STANDING-2.md) — post-remediation
