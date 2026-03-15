# Circuit Breaker — Security Standing (Post-Remediation)

**Date:** 2026-03-11
**Scope:** Backend (FastAPI/SQLAlchemy), Frontend (React/Vite), Docker mono-image deployment
**Version:** v0.2.0 (dev branch) - Pending v0.2.2
**Time:** 3:30 PM MST
**Prior report:** `SECURITY_STANDING-1.md` (2026-03-11 10:50 AM MST)

---

## Executive Summary

This report documents the security posture of Circuit Breaker following a targeted remediation cycle that resolved all 10 High and Medium severity findings identified in the initial security standing review. The three critical items — timing-unsafe API token comparison, unrestricted Docker socket mount, and missing HTTP-to-HTTPS redirect — have been fully addressed. Seven Medium severity items covering vault key rotation, Redis authentication, CSP hardening, Permissions-Policy, session revocation, URL scheme validation, and container filesystem immutability were also completed.

The remediation moves the project from "strong for homelab, approaching enterprise" to a posture suitable for small-to-mid enterprise deployments. The remaining open items are exclusively Low severity and relate to defence-in-depth refinements (debug tool removal, DNS rebinding mitigation, audit redaction tuning, cookie prefixes, and nginx-level rate limiting). No High or Medium severity findings remain.

---

## Remediation Summary

The table below maps each finding from the original report to its resolution status.

| # | Severity | Area | Original Finding | Status | Resolution |
|---|----------|------|------------------|--------|------------|
| 1 | High | Auth | `CB_API_TOKEN` compared with `==` (timing side-channel) | **Resolved** | Replaced with `hmac.compare_digest` in `core/security.py:215`. |
| 2 | High | Docker | Docker socket mounted by default (host-equivalent access) | **Resolved** | Socket removed from default `docker-compose.yml`. Opt-in via `docker-compose.socket.yml` override or `CB_DOCKER_HOST` TCP proxy env var. |
| 3 | High | Transport | No HTTP-to-HTTPS redirect at nginx | **Resolved** | `nginx.mono.conf` split into port-80 (301 redirect) and port-443 (HTTPS) server blocks. Health endpoint exempted for Docker healthchecks. |
| 4 | Medium | Secrets | Vault key rotation schema exists but never triggers | **Resolved** | Daily APScheduler job (`vault_rotation_check`, 04:30) checks `vault_key_rotation_days` and auto-rotates via existing `rotate_vault_key()`. |
| 5 | Medium | Secrets | Redis has no `requirepass` | **Resolved** | Entrypoint generates random 32-byte password to `/data/.redis_pass`. Redis starts with `--requirepass`. `CB_REDIS_URL` auto-embeds the password. |
| 6 | Medium | Transport | CSP uses `'unsafe-inline'` without mitigation | **Resolved** | Added `'strict-dynamic'` to `script-src`. In supporting browsers this overrides `'unsafe-inline'`, providing progressive XSS hardening without breaking the SPA. |
| 7 | Medium | Network | No URL scheme validation (allows `file://`, `gopher://`) | **Resolved** | `_reject_ssrf_impl` now rejects all non-HTTP(S) schemes at the top of validation. |
| 8 | Medium | Headers | No `Permissions-Policy` header | **Resolved** | Added to both `security_headers.py` middleware and `nginx.mono.conf`. Restricts camera, microphone, geolocation, payment, USB, magnetometer, gyroscope, accelerometer. |
| 9 | Medium | Auth | `change_password` does not revoke sessions | **Resolved** | Endpoint now calls `revoke_all_sessions()` (current session exempted) and writes an audit log entry. |
| 10 | Medium | Docker | No `read_only: true` filesystem in docker-compose | **Resolved** | Added `read_only: true` with explicit `tmpfs` mounts for `/tmp`, `/run`, `/var/log`, `/var/lib/nginx`, `/var/lib/postgresql`. |

---

## 1. Authentication and Authorization

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| JWT sessions | `core/security.py` | HS256 tokens with audience segregation (`fastapi-users:auth`, `cb:mfa-challenge`, `cb:change-password`). Tokens are extracted from Bearer header or `cb_session` HttpOnly cookie. |
| RBAC | `core/rbac.py` | Four roles: `viewer`, `editor`, `admin`, `demo`. Scope-based authorization with wildcard matching (`action:resource`). Endpoints use `require_role()` / `require_scope()` FastAPI dependencies. |
| MFA | `api/auth.py` | Full TOTP lifecycle: setup, activate (8 backup codes), verify, disable. Challenge tokens are audience-scoped with a 5-minute TTL. Backup codes are bcrypt-hashed. |
| Session management | `api/auth.py`, `services/auth_service.py` | DB-backed sessions (`UserSession` table) with hash-based token storage, explicit revocation, and an in-memory cache (10s TTL, 2048 max entries). |
| API token comparison | `core/security.py` | `CB_API_TOKEN` is now validated with `hmac.compare_digest` (constant-time), eliminating the timing side-channel. |
| Password change hardening | `api/auth.py` | `change_password` now revokes all other sessions for the user (keeping the current session alive) and writes an audit log entry, matching the behaviour of `reset_local_user_password`. |
| Cookie security | `core/auth_cookie.py` | `cb_session` cookie: `HttpOnly`, `SameSite=Strict`, `Secure` auto-detected per request. |
| Password policy | `services/auth_service.py` | 8+ characters, must include uppercase, lowercase, digit, and special character. ReDoS mitigation via input length caps before regex. |
| Account lockout | `services/auth_service.py` | Configurable `login_lockout_attempts` and `login_lockout_minutes` via AppSettings. |

### Known limitations (unchanged from prior report)

- When auth is disabled and no `CB_API_TOKEN` is set, all requests receive synthetic admin access.
- The session validation cache is per-process — in a multi-worker deployment, a revoked session may be accepted for up to 10 seconds by another worker.
- Demo users are created as real DB rows without a cleanup job.

---

## 2. Secrets Management

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| Fernet vault | `services/credential_vault.py` | Lazy-initialising singleton wrapping `cryptography.Fernet` (AES-128-CBC + HMAC-SHA256). All integration credentials (`Credential` model) are encrypted at rest. |
| Automated vault key rotation | `main.py`, `services/vault_service.py` | Daily APScheduler job at 04:30 reads `vault_key_rotation_days` (default 90) and `vault_key_rotated_at`. When overdue, calls `rotate_vault_key()` which re-encrypts all secrets, persists the new key to `/data/.env` and `AppSettings`, and hot-swaps the in-memory vault. |
| NATS auth | `docker/supervisord.mono.conf` | NATS requires `NATS_AUTH_TOKEN` at startup; hard-fails if unset. |
| Redis authentication | `docker/supervisord.mono.conf`, `docker/entrypoint-mono.sh` | Entrypoint generates a random 32-byte password to `/data/.redis_pass` (0600 permissions, owned by `breaker`). Redis starts with `--requirepass`. The backend `CB_REDIS_URL` is automatically constructed with the password embedded. |
| Credential redaction | `services/log_service.py` | Recursive key-matching redaction (`password`, `secret`, `token`, `key`, `credential`, `community`, etc.) before any audit log write. |

### Known limitations

- `CB_VAULT_KEY`, `CB_DB_PASSWORD`, and `NATS_AUTH_TOKEN` are passed as environment variables, visible in `docker inspect` and `/proc/*/environ`.
- The Fernet key is used directly (no per-record salt or key derivation function).
- `AppSettings.vault_key` stores the plaintext key in the database as a fallback.

### Resolved since prior report

- ~~Vault key rotation schema exists but no automated rotation logic is implemented.~~ (Daily scheduler job now handles this.)
- ~~Redis has no `requirepass`.~~ (Auto-generated password at container start.)

---

## 3. Network and Scanning Safeguards

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| Air-gap mode | `core/network_acl.py`, `core/config.py` | `CB_AIRGAP` env var or `AppSettings.airgap_mode` flag. When active, all network scans are rejected with HTTP 403. |
| CIDR ACL | `core/network_acl.py`, `db/models.py` | `AppSettings.scan_allowed_networks` (default: RFC 1918 ranges). Scan targets must be a subnet of at least one allowed network. |
| RFC 1918 enforcement | `core/network_acl.py` | Public (non-RFC 1918) IP ranges are blocked from scanning, even if the ACL is wide. |
| URL scheme validation | `core/url_validation.py` | Only `http` and `https` schemes are accepted. `file://`, `gopher://`, `ftp://`, and all other schemes are rejected before any IP resolution occurs. |
| CIDR size limits | `services/discovery_service.py` | Maximum 1M addresses per target, minimum /12 prefix length for IPv4, /0 rejected. |
| Nmap arg sanitiser | `core/nmap_args.py` | Allowlist-only validation: only `-sT`, `-sV`, `-F`, `--open`, `-T0`-`-T5`, and `-p <spec>` are accepted. Shell metacharacters are rejected. Max 256 chars. |
| SNMP community validator | `core/validation.py` | Regex allowlist (`[a-zA-Z0-9_.\-]+`), 64-char limit. Communities encrypted via vault before storage. |
| SSRF protection | `core/url_validation.py` | Scheme validation + DNS resolution before IP check. Two policies: strict (webhooks — blocks all private IPs) and relaxed (Proxmox — allows RFC 1918). Checks all resolved addresses. |
| Scan concurrency | `services/discovery_service.py` | Hard limit of 2 concurrent scan jobs. |

### Known limitations (unchanged)

- SSRF validation is TOCTOU-vulnerable: the resolved IP at validation time may differ from the IP connected to later (DNS rebinding).
- `is_ip_in_cidrs` treats an empty list as "allow all" (permissive default for WS whitelist).
- No IPv6 support: `is_rfc1918` returns `False` for all IPv6; ULA ranges (`fc00::/7`) are not covered.
- The `"docker"` sentinel value bypasses all CIDR and ACL validation.

### Resolved since prior report

- ~~No URL scheme validation — does not reject `file://`, `gopher://`, etc.~~ (Scheme allowlist now enforced.)

---

## 4. Transport Security

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| TLS termination | `docker/nginx.mono.conf` | Nginx terminates HTTPS on port 443. Self-signed RSA-4096 cert auto-generated if none exists. |
| HTTP-to-HTTPS redirect | `docker/nginx.mono.conf` | Port 80 returns `301` to HTTPS for all requests. The `/api/v1/health` endpoint is exempted so Docker healthchecks continue to work over plain HTTP. |
| HSTS | `middleware/security_headers.py`, `docker/nginx.mono.conf` | Both nginx and the backend middleware set `Strict-Transport-Security: max-age=63072000; includeSubDomains` (2 years). Conditional on HTTPS in the backend middleware. |
| Content-Security-Policy | `middleware/security_headers.py` | `default-src 'self'; script-src 'self' 'unsafe-inline' 'strict-dynamic'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https://www.gravatar.com; connect-src 'self' ws: wss: https://geocoding-api.open-meteo.com https://api.open-meteo.com; frame-ancestors 'none';` |
| Permissions-Policy | `middleware/security_headers.py`, `docker/nginx.mono.conf` | Restricts `camera`, `microphone`, `geolocation`, `payment`, `usb`, `magnetometer`, `gyroscope`, `accelerometer` to empty allowlists. |
| X-Frame-Options | `middleware/security_headers.py` | `DENY` |
| X-Content-Type-Options | `middleware/security_headers.py` | `nosniff` |
| Referrer-Policy | `middleware/security_headers.py` | `strict-origin-when-cross-origin` |
| WSS enforcement | `core/auth_cookie.py` | Optional `CB_WS_REQUIRE_WSS=true` flag rejects plain-text WebSocket connections. |

### Known limitations

- CSP `style-src` still includes `'unsafe-inline'` due to Tailwind inline style dependencies. Full nonce-based style CSP requires a build pipeline change.
- `'strict-dynamic'` in `script-src` is only effective in CSP Level 3 browsers. Older browsers fall back to `'unsafe-inline'`.
- Self-signed cert uses `CN=localhost` with no Subject Alternative Names.

### Resolved since prior report

- ~~No HTTP-to-HTTPS redirect at the nginx layer.~~ (Port 80 now redirects.)
- ~~CSP allows `'unsafe-inline'` without mitigation.~~ (`'strict-dynamic'` added — progressively overrides `'unsafe-inline'` in modern browsers.)
- ~~No `Permissions-Policy` header.~~ (Added to both middleware and nginx.)

---

## 5. Container and Runtime Hardening

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| Multi-stage build | `Dockerfile.mono` | Three stages: frontend build, backend/pip build, runtime. Build toolchains are discarded. |
| Non-root user | `Dockerfile.mono` | `breaker:1000` with `/sbin/nologin` shell. All app/data directories owned by `breaker`. |
| PID 1 init | `Dockerfile.mono` | `tini` as entrypoint for signal forwarding and zombie reaping. |
| Read-only filesystem | `docker/docker-compose.yml` | `read_only: true` with explicit `tmpfs` mounts for `/tmp` (100M), `/run` (10M), `/var/log` (50M), `/var/lib/nginx` (10M), `/var/lib/postgresql` (10M). Only `/data` is a persistent writable volume. |
| Capability restriction | `docker/docker-compose.yml` | `cap_drop: ALL` with selective `cap_add: [NET_RAW, NET_BIND_SERVICE, CHOWN, SETUID, SETGID, DAC_OVERRIDE]`. |
| Privilege escalation block | `docker/docker-compose.yml` | `security_opt: [no-new-privileges:true]`. |
| Docker socket opt-in | `docker/docker-compose.yml`, `docker/docker-compose.socket.yml` | Socket is **not** mounted by default. Users who need Docker discovery opt in via `docker-compose.socket.yml` override or set `CB_DOCKER_HOST` to a TCP-based Docker API proxy (e.g., Tecnativa/docker-socket-proxy). |
| Docker host proxy | `services/docker_discovery.py`, `services/discovery_safe.py` | `CB_DOCKER_HOST` env var allows TCP-based Docker API access (e.g., `tcp://proxy:2375`), enabling Docker discovery without mounting the host socket. |
| Process isolation | `docker/supervisord.mono.conf` | Postgres, NATS, Redis, backend, and workers all run as `breaker`. Only nginx and supervisord run as root. |
| Mandatory secrets | `docker/docker-compose.yml` | `CB_DB_PASSWORD`, `CB_VAULT_KEY`, `NATS_AUTH_TOKEN` are fail-fast required (`${VAR:?error}`). |
| Pinned base images | `Dockerfile.mono` | `python:3.12.9-slim-bookworm`, `node:20.19.0-alpine3.21`. |

### Known limitations

- Supervisord runs as root (required for nginx port binding and child process management).
- Nginx runs as root — could be replaced with `CAP_NET_BIND_SERVICE` on a non-root process.
- Debug tools (`curl`, `jq`, `netcat-traditional`, `iproute2`) remain in the runtime image.
- `chmod 1777` on the PostgreSQL socket directory is world-writable within the container.

### Resolved since prior report

- ~~Docker socket mounted by default.~~ (Now opt-in via override file or TCP proxy.)
- ~~No `read_only: true` filesystem flag.~~ (Added with explicit tmpfs mounts.)

---

## 6. Audit and Observability

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| Hash-chained audit log | `services/log_service.py` | Every log entry includes a SHA-256 hash of its payload chained to the previous entry's hash. Tampering with or deleting any entry breaks the chain. |
| Credential redaction | `services/log_service.py` | Recursive, deep redaction of values for keys matching sensitive substrings. Applied to diffs, request bodies, and response bodies. |
| Append-only design | `services/log_service.py` | No update or delete API exists for audit logs. |
| Automatic logging | `middleware/logging_middleware.py` | All mutating API operations (POST, PUT, PATCH, DELETE) are automatically logged with actor, entity, status code, and sanitised payloads. Auth paths are explicitly excluded. |
| Password change audit | `api/auth.py` | `change_password` now writes an explicit audit log entry (previously missing). |
| Redis audit stream | `services/log_service.py` | After writing to Postgres, audit events are published to Redis `audit:stream` channel for real-time consumers. |
| Log retention | `db/models.py` | `AppSettings.audit_log_retention_days` (default 90). |

### Known limitations (unchanged)

- Hash chain uses `SELECT ... ORDER BY id DESC LIMIT 1` without strong serialisation in concurrent environments — duplicate `previous_hash` values are possible.
- The `REDACTED_KEYS` set includes `"key"` which is very broad — any dict key containing the substring "key" will be redacted (e.g., `"primary_key"`, `"keyboard"`).
- Redis audit publish is fire-and-forget with bare exception swallowing — consumers can silently miss events.
- Failed operations (e.g., 404 on delete) are not audit-logged in all routers.

---

## 7. Rate Limiting

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| Profile system | `core/rate_limit.py` | Three named profiles (relaxed/normal/strict) stored in `AppSettings.rate_limit_profile`. Admin-configurable at runtime. |
| Category limits | `core/rate_limit.py` | Per-category rates: `auth` (20/5/3 per min), `scan` (5/1/1 per min), `telemetry` (30/15/5 per min), `mfa_verify` (10/5/3 per 15 min), `ip_check` (30/10/5 per min). |
| Scan concurrency | `services/discovery_service.py` | Global hard cap of 2 concurrent scan jobs. |
| WS connection caps | `api/ws_telemetry.py` | Global max 100 connections, per-IP max 10, per-connection max 200 subscriptions. |

### Known limitations (unchanged)

- Rate limiting keys on `get_remote_address` (IP-based) — easily spoofed behind a misconfigured reverse proxy. No per-user rate limiting.
- Profile cache has a 5-minute TTL — a profile switch does not take effect immediately.
- WS connection counters are per-process — with 2 Uvicorn workers, effective limits double.
- No nginx-level `limit_req` — all throttling happens at the application layer.

---

## 8. Frontend Security

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| XSS sanitisation | `components/MarkdownViewer.jsx`, `components/Map/Sidebar.jsx` | Both uses of `dangerouslySetInnerHTML` are wrapped with `DOMPurify.sanitize()`. |
| HttpOnly session | `core/auth_cookie.py` | Session token is stored in an HttpOnly cookie, inaccessible to JavaScript. |
| No secret storage | `frontend/src/` | `localStorage` is used only for UI preferences (theme, legend state, map viewport, sidebar width, doc drafts). No tokens, passwords, or API keys are stored. |
| CSRF protection | `core/auth_cookie.py` | `SameSite=Strict` cookie policy prevents cross-origin cookie attachment. |

### Known limitations (unchanged)

- No `__Host-` or `__Secure-` cookie name prefix for defence-in-depth.
- `clear_auth_cookie_response` does not mirror `samesite`/`secure`/`httponly` flags on the deletion Set-Cookie header.

---

## 9. Remaining Improvements

All High and Medium severity items from the prior report have been resolved. The remaining items are Low severity.

| # | Severity | Effort | Area | Description |
|---|----------|--------|------|-------------|
| 1 | Low | Low | Docker | Remove debug tools (`curl`, `jq`, `netcat-traditional`, `iproute2`) from the runtime image or move them to a debug variant. |
| 2 | Low | Low | Network | Validate URL-resolved IPs a second time at request time in `url_validation.py` to mitigate DNS rebinding (TOCTOU). |
| 3 | Low | Low | Audit | Narrow the `"key"` entry in `REDACTED_KEYS` to avoid false-positive redaction of non-sensitive fields. |
| 4 | Low | Medium | Auth | Add a cleanup job for stale demo user rows. |
| 5 | Low | Low | Cookies | Add `__Host-` prefix to the `cb_session` cookie for additional browser-level protection. |
| 6 | Low | Medium | Rate Limit | Add nginx-level `limit_req` directives as a first line of defence before requests reach the application. |
| 7 | Low | Low | Transport | Add Subject Alternative Names to the self-signed certificate (currently `CN=localhost` only). |
| 8 | Low | Low | Cookies | Mirror `samesite`/`secure`/`httponly` flags on the `clear_auth_cookie_response` deletion header. |

---

## Bottom Line

All High and Medium severity findings from the initial security audit have been resolved in this remediation cycle. The three critical attack vectors — timing-unsafe API token comparison, unrestricted Docker socket mount, and missing HTTP-to-HTTPS redirect — are closed. The secrets layer now includes automated vault key rotation on a configurable schedule and authenticated Redis. Transport security is hardened with mandatory HTTPS redirect, `'strict-dynamic'` CSP, and a `Permissions-Policy` header. The container runs on a read-only filesystem with explicit tmpfs carve-outs, and Docker socket access is opt-in only.

The remaining 8 items are all Low severity defence-in-depth improvements. None represent exploitable vulnerabilities in a typical deployment. The security posture is now appropriate for small-to-mid enterprise deployments, and the project is well-positioned for a v1.0 security certification once the Low-severity items are addressed and a formal penetration test is conducted.
