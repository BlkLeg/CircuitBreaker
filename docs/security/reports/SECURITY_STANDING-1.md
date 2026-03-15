# Circuit Breaker — Security Standing

**Date:** 2026-03-11
**Scope:** Backend (FastAPI/SQLAlchemy), Frontend (React/Vite), Docker mono-image deployment
**Version:** v0.2.0 (dev branch) - Pending v0.2.2
**Time:** 10:50 AM MST

---

## Executive Summary

Circuit Breaker implements a layered security model with defense-in-depth across authentication, authorization, encryption, network controls, and container hardening. The system provides RBAC with four roles and granular scopes, TOTP-based MFA, Fernet-encrypted credential storage, hash-chained append-only audit logs, and a three-tier network ACL for scan targets. Transport security includes conditional HSTS, a Content-Security-Policy, and TLS termination at nginx. Container hardening drops all Linux capabilities except a minimal required set, mandates NATS authentication, and runs application services as a non-root user. The primary residual risks are the mounted Docker socket (which can bypass all container isolation), the use of `==` instead of constant-time comparison for the `CB_API_TOKEN` check, and the absence of HTTP-to-HTTPS redirect at the nginx layer. Overall, the security posture is strong for a self-hosted homelab product and approaching production-grade for small enterprise deployments.

---

## 1. Authentication and Authorization

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| JWT sessions | `core/security.py` | HS256 tokens with audience segregation (`fastapi-users:auth`, `cb:mfa-challenge`, `cb:change-password`). Tokens are extracted from Bearer header or `cb_session` HttpOnly cookie. |
| RBAC | `core/rbac.py` | Four roles: `viewer`, `editor`, `admin`, `demo`. Scope-based authorization with wildcard matching (`action:resource`). Endpoints use `require_role()` / `require_scope()` FastAPI dependencies. |
| MFA | `api/auth.py` | Full TOTP lifecycle: setup, activate (8 backup codes), verify, disable. Challenge tokens are audience-scoped with a 5-minute TTL. Backup codes are bcrypt-hashed. |
| Session management | `api/auth.py`, `services/auth_service.py` | DB-backed sessions (`UserSession` table) with hash-based token storage, explicit revocation, and an in-memory cache (10s TTL, 2048 max entries). |
| API tokens | `api/auth.py` | Admin-created, shown once, stored as HMAC-SHA256 hashes. Scoped to the creating admin. |
| Cookie security | `core/auth_cookie.py` | `cb_session` cookie: `HttpOnly`, `SameSite=Strict`, `Secure` auto-detected per request. |
| Password policy | `services/auth_service.py` | 8+ characters, must include uppercase, lowercase, digit, and special character. ReDoS mitigation via input length caps before regex. |
| Account lockout | `services/auth_service.py` | Configurable `login_lockout_attempts` and `login_lockout_minutes` via AppSettings. |

### Known limitations

- `CB_API_TOKEN` is compared with `==` (not constant-time) in `core/security.py:215` — susceptible to timing side-channels.
- When auth is disabled and no `CB_API_TOKEN` is set, all requests receive synthetic admin access.
- The session validation cache is per-process — in a multi-worker deployment, a revoked session may be accepted for up to 10 seconds by another worker.
- `change_password` does not revoke existing sessions (unlike `reset_local_user_password`, which does).
- Demo users are created as real DB rows without a cleanup job.

---

## 2. Secrets Management

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| Fernet vault | `services/credential_vault.py` | Lazy-initialising singleton wrapping `cryptography.Fernet` (AES-128-CBC + HMAC-SHA256). All integration credentials (`Credential` model) are encrypted at rest. |
| Vault key lifecycle | `db/models.py` (AppSettings) | `vault_key`, `vault_key_hash` (SHA-256), `vault_key_rotation_days` (default 90), `vault_key_rotated_at` fields exist on AppSettings. |
| NATS auth | `docker/supervisord.mono.conf` | NATS requires `NATS_AUTH_TOKEN` at startup; hard-fails if unset. |
| Redis isolation | `docker/supervisord.mono.conf` | Bound to `127.0.0.1` with `protected-mode yes`. No external access. |
| Credential redaction | `services/log_service.py` | Recursive key-matching redaction (`password`, `secret`, `token`, `key`, `credential`, `community`, etc.) before any audit log write. |

### Known limitations

- Vault key rotation schema exists but no automated rotation logic is implemented.
- `CB_VAULT_KEY`, `CB_DB_PASSWORD`, and `NATS_AUTH_TOKEN` are passed as environment variables, visible in `docker inspect` and `/proc/*/environ`.
- Redis has no `requirepass` — any process inside the container can read/write the cache.
- The Fernet key is used directly (no per-record salt or key derivation function).
- `AppSettings.vault_key` stores the plaintext key in the database as a fallback.

---

## 3. Network and Scanning Safeguards

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| Air-gap mode | `core/network_acl.py`, `core/config.py` | `CB_AIRGAP` env var or `AppSettings.airgap_mode` flag. When active, all network scans are rejected with HTTP 403. |
| CIDR ACL | `core/network_acl.py`, `db/models.py` | `AppSettings.scan_allowed_networks` (default: RFC 1918 ranges). Scan targets must be a subnet of at least one allowed network. |
| RFC 1918 enforcement | `core/network_acl.py` | Public (non-RFC 1918) IP ranges are blocked from scanning, even if the ACL is wide. |
| CIDR size limits | `services/discovery_service.py` | Maximum 1M addresses per target, minimum /12 prefix length for IPv4, /0 rejected. |
| Nmap arg sanitiser | `core/nmap_args.py` | Allowlist-only validation: only `-sT`, `-sV`, `-F`, `--open`, `-T0`–`-T5`, and `-p <spec>` are accepted. Shell metacharacters are rejected. Max 256 chars. |
| SNMP community validator | `core/validation.py` | Regex allowlist (`[a-zA-Z0-9_.\-]+`), 64-char limit. Communities encrypted via vault before storage. |
| SSRF protection | `core/url_validation.py` | DNS resolution before IP check. Two policies: strict (webhooks — blocks all private IPs) and relaxed (Proxmox — allows RFC 1918). Checks all resolved addresses. |
| Scan concurrency | `services/discovery_service.py` | Hard limit of 2 concurrent scan jobs. |

### Known limitations

- SSRF validation is TOCTOU-vulnerable: the resolved IP at validation time may differ from the IP connected to later (DNS rebinding).
- No URL scheme validation in `url_validation.py` — does not reject `file://`, `gopher://`, etc.
- `is_ip_in_cidrs` treats an empty list as "allow all" (permissive default for WS whitelist).
- No IPv6 support: `is_rfc1918` returns `False` for all IPv6; ULA ranges (`fc00::/7`) are not covered.
- The `"docker"` sentinel value bypasses all CIDR and ACL validation.

---

## 4. Transport Security

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| TLS termination | `docker/nginx.mono.conf` | Nginx terminates HTTPS on port 443. Self-signed RSA-4096 cert auto-generated if none exists. |
| HSTS | `middleware/security_headers.py`, `docker/nginx.mono.conf` | Both nginx and the backend middleware set `Strict-Transport-Security: max-age=63072000; includeSubDomains` (conditional on HTTPS in the middleware). |
| Content-Security-Policy | `middleware/security_headers.py` | `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https://www.gravatar.com; connect-src 'self' ws: wss: https://geocoding-api.open-meteo.com https://api.open-meteo.com; frame-ancestors 'none';` |
| X-Frame-Options | `middleware/security_headers.py` | `DENY` |
| X-Content-Type-Options | `middleware/security_headers.py` | `nosniff` |
| Referrer-Policy | `middleware/security_headers.py` | `strict-origin-when-cross-origin` |
| WSS enforcement | `core/auth_cookie.py` | Optional `CB_WS_REQUIRE_WSS=true` flag rejects plain-text WebSocket connections. |

### Known limitations

- CSP allows `'unsafe-inline'` for both scripts and styles, weakening XSS protection. Nonce-based CSP would be stronger.
- No HTTP-to-HTTPS redirect at the nginx layer — port 80 serves content directly.
- No `Permissions-Policy` header to restrict browser APIs (camera, microphone, geolocation).
- Self-signed cert uses `CN=localhost` with no Subject Alternative Names.

---

## 5. Container and Runtime Hardening

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| Multi-stage build | `Dockerfile.mono` | Three stages: frontend build, backend/pip build, runtime. Build toolchains are discarded. |
| Non-root user | `Dockerfile.mono` | `breaker:1000` with `/sbin/nologin` shell. All app/data directories owned by `breaker`. |
| PID 1 init | `Dockerfile.mono` | `tini` as entrypoint for signal forwarding and zombie reaping. |
| Capability restriction | `docker/docker-compose.yml` | `cap_drop: ALL` with selective `cap_add: [NET_RAW, NET_BIND_SERVICE, CHOWN, SETUID, SETGID, DAC_OVERRIDE]`. |
| Privilege escalation block | `docker/docker-compose.yml` | `security_opt: [no-new-privileges:true]`. |
| Docker socket access | `docker/entrypoint-mono.sh` | Group-based access (matches socket GID, `chmod 660`) instead of world-readable `666`. |
| Process isolation | `docker/supervisord.mono.conf` | Postgres, NATS, Redis, backend, and workers all run as `breaker`. Only nginx and supervisord run as root. |
| Mandatory secrets | `docker/docker-compose.yml` | `CB_DB_PASSWORD`, `CB_VAULT_KEY`, `NATS_AUTH_TOKEN` are fail-fast required (`${VAR:?error}`). |
| Pinned base images | `Dockerfile.mono` | `python:3.12.9-slim-bookworm`, `node:20.19.0-alpine3.21`. |

### Known limitations

- Docker socket is mounted (`/var/run/docker.sock`) — this effectively grants near-root-equivalent access to the host, undermining capability restrictions.
- Supervisord runs as root (required for nginx port binding and child process management).
- Nginx runs as root — could be replaced with `CAP_NET_BIND_SERVICE` on a non-root process.
- No `read_only: true` filesystem flag in docker-compose.
- Debug tools (`curl`, `jq`, `netcat-traditional`, `iproute2`) remain in the runtime image.
- `chmod 1777` on the PostgreSQL socket directory is world-writable within the container.

---

## 6. Audit and Observability

### What exists

| Mechanism | Location | Summary |
|---|---|---|
| Hash-chained audit log | `services/log_service.py` | Every log entry includes a SHA-256 hash of its payload chained to the previous entry's hash. Tampering with or deleting any entry breaks the chain. |
| Credential redaction | `services/log_service.py` | Recursive, deep redaction of values for keys matching sensitive substrings. Applied to diffs, request bodies, and response bodies. |
| Append-only design | `services/log_service.py` | No update or delete API exists for audit logs. |
| Automatic logging | `middleware/logging_middleware.py` | All mutating API operations (POST, PUT, PATCH, DELETE) are automatically logged with actor, entity, status code, and sanitised payloads. Auth paths are explicitly excluded. |
| Redis audit stream | `services/log_service.py` | After writing to Postgres, audit events are published to Redis `audit:stream` channel for real-time consumers. |
| Log retention | `db/models.py` | `AppSettings.audit_log_retention_days` (default 90). |

### Known limitations

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

### Known limitations

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

### Known limitations

- No `__Host-` or `__Secure-` cookie name prefix for defence-in-depth.
- `clear_auth_cookie_response` does not mirror `samesite`/`secure`/`httponly` flags on the deletion Set-Cookie header.

---

## 9. Recommended Improvements

| # | Severity | Effort | Area | Description |
|---|----------|--------|------|-------------|
| 1 | High | Low | Auth | Replace `==` with `hmac.compare_digest` for `CB_API_TOKEN` comparison in `core/security.py:215` to prevent timing attacks. |
| 2 | High | Medium | Docker | Evaluate removing the Docker socket mount or replacing it with a TCP-based Docker API proxy with auth. The socket grants host-equivalent access. |
| 3 | High | Low | Transport | Add an HTTP-to-HTTPS redirect in nginx (separate `server` block on port 80 returning `301` to `https://`). |
| 4 | Medium | Medium | Secrets | Implement vault key rotation logic — the schema fields exist but no automated rotation occurs. |
| 5 | Medium | Low | Secrets | Add `requirepass` to the embedded Redis configuration in `supervisord.mono.conf`. |
| 6 | Medium | Medium | Transport | Replace `'unsafe-inline'` in CSP with nonce-based script/style sources for stronger XSS protection. |
| 7 | Medium | Low | Network | Add URL scheme validation to `url_validation.py` — reject `file://`, `gopher://`, and other non-HTTP(S) schemes. |
| 8 | Medium | Low | Headers | Add a `Permissions-Policy` header to restrict browser APIs (camera, microphone, geolocation, etc.). |
| 9 | Medium | Medium | Auth | Revoke existing sessions in `change_password` (currently only done in `reset_local_user_password`). |
| 10 | Medium | Medium | Docker | Add `read_only: true` to docker-compose and explicitly whitelist writable paths via `tmpfs` mounts. |
| 11 | Low | Low | Docker | Remove debug tools (`curl`, `jq`, `netcat-traditional`, `iproute2`) from the runtime image or move them to a debug variant. |
| 12 | Low | Low | Network | Validate URL-resolved IPs a second time at request time in `url_validation.py` to mitigate DNS rebinding. |
| 13 | Low | Low | Audit | Narrow the `"key"` entry in `REDACTED_KEYS` to avoid false-positive redaction of non-sensitive fields. |
| 14 | Low | Medium | Auth | Add a cleanup job for stale demo user rows. |
| 15 | Low | Low | Cookies | Add `__Host-` prefix to the `cb_session` cookie for additional browser-level protection. |
| 16 | Low | Medium | Rate Limit | Add nginx-level `limit_req` directives as a first line of defence before requests reach the application. |

---

## Bottom Line

Circuit Breaker's security posture is well above average for a self-hosted homelab platform. The combination of RBAC with scopes, MFA, Fernet-encrypted credentials, hash-chained audit logs, air-gap mode, and container capability restrictions forms a solid multi-layer defence. The three highest-priority items to address before any internet-facing deployment are the timing-unsafe API token comparison, the Docker socket mount, and the missing HTTP-to-HTTPS redirect — all of which are low-to-medium effort fixes. With those resolved and the vault key rotation logic implemented, the project would be well-positioned for a v1.0 enterprise-grade security certification.
