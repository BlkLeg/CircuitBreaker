# Security Patch Summary

**Audit reference:** [Security Report.md](Security%20Report.md) (2026-03-10, v0.2.0-beta)  
**Patch scope:** Critical, High, and Medium severity findings addressed in code and configuration.

---

## Overview

This document summarizes security fixes applied to Circuit Breaker in response to the multi-domain security audit. Implemented changes reduce risk from command injection, SSRF, JWT misuse, default credentials, and several high/medium issues in authentication, input validation, and infrastructure.

---

## Critical Fixes

| ID | Finding | Fix |
|----|---------|-----|
| **C-01** | Command injection via Nmap arguments | Allowlist of safe nmap flags; `shlex.split` + token validation; rejection of shell metacharacters; schema `max_length=256` on `nmap_arguments`. Validation in discovery service, worker, and API. |
| **C-02** | Command injection in SNMP community string | New `validate_snmp_community()` (regex `^[a-zA-Z0-9_.-]+$`, max 64 chars). Applied in SNMP generic, iDRAC, APC UPS integrations and monitor service. |
| **C-03** | JWT audience validation bypass | Removed `verify_aud=False` fallback. Session tokens use fixed audience `fastapi-users:auth`; decode requires audience. Single decode path in `get_optional_user` and logging middleware. |
| **C-04** | Hardcoded/fallback JWT secret | No runtime-generated secret. JWT secret from DB or `CB_JWT_SECRET_ENV` only; empty string if unset. Vault/API token no longer used as JWT fallback. |
| **C-05** | Unencrypted OAuth tokens in DB | OAuth tokens encrypted with credential vault before storage. Read path supports legacy plaintext for migration. |
| **C-06** | Default database password | Removed `:-breaker` from dev and prod Compose. `POSTGRES_PASSWORD` and `CB_DB_URL` require explicit `CB_DB_PASSWORD`. |
| **C-07** | SSRF in webhook URL dispatch | New `reject_ssrf_url()` blocks loopback, link-local, and private IPs. Applied on webhook create/update, test endpoint, and worker before HTTP dispatch. |
| **C-08** | SSRF in Proxmox `config_url` | `config_url` validated with `reject_ssrf_url_proxmox()` (allows private IPs for LAN). Schema uses `HttpUrl` and validator; trailing slash stripped. |

---

## High Severity Fixes

| ID | Finding | Fix |
|----|---------|-----|
| **H-02** | WebSocket disconnect race condition | `disconnect()` made async and wrapped in connection manager lock in `ws_manager`, topology, and status WebSocket handlers. |
| **H-03** | Thread-unsafe session validation cache | Session cache TTL reduced to 10s for faster revocation; explicit invalidation on logout retained. |
| **H-05** | Unbounded on-demand TLS issuance | Caddyfile comment added: recommend limiting cert issuance via `ask` endpoint or using pre-provisioned certs (Caddy has no direct `max_certificates`). |
| **H-07** | Silent vault initialization failure | On vault init failure: critical log, DB close, and `raise SystemExit(1)` so the app does not run without encryption. |
| **H-09** | API token hash not salted | API tokens hashed with HMAC-SHA256 using server JWT secret; lookup uses same hash. Existing SHA256 tokens require re-issue. |
| **H-10** | MFA verify not rate limited | `mfa_verify` added to rate-limit profiles (e.g. 5/15 minutes). Decorator applied on MFA verify endpoint. |
| **H-11** | Masquerade not audited | Masquerade action logged via `log_audit()` with admin and target user details; `Request` injected for context. |
| **H-12** | Path traversal in profile photo upload | Filename rejected if it contains `/` or `..`. Saved name: `{user_id}-{sha256(data)[:12]}.{ext}`; path resolved and checked to stay under profiles directory. |
| **H-13** | Connection pool exhaustion | Default pool size and max overflow increased (e.g. 20/20). Session lifecycle in scheduled jobs unchanged in this patch; pool sizing reduces blocking under load. |
| **H-14** | Credential exposure in telemetry API | Confirmed telemetry GET returns profile metadata only, not raw credentials; no code change. Masking guidance retained for any future credential fields. |

**Deferred / environment-dependent (not implemented in this patch):**

- **H-01** NATS auth + TLS — optional; enable via NATS config and network policy.
- **H-04** Docker socket — use read-only proxy or explicit opt-in; deployment concern.
- **H-06** Network segmentation — separate Compose networks; deployment/ops.
- **H-08** WebSocket cookie auth + WSS-only — larger auth refactor; document WSS in production.

---

## Medium Severity Fixes

| ID | Finding | Fix |
|----|---------|-----|
| **M-01** | XSS via `dangerouslySetInnerHTML` | DOMPurify added; MarkdownViewer and Map Sidebar sanitize HTML before rendering. |
| **M-02** | No Content-Security-Policy | CSP header added in Caddy: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' wss:; frame-ancestors 'none'`. |
| **M-03** | CSRF (SameSite only) | Verified session cookie uses `SameSite=Strict`; no change. |
| **M-04** | Permissive CORS | Default `cors_origins` set to `[]` (same-origin). Env `CORS_ORIGINS` can set JSON array or comma-separated list for production. |
| **M-05** | Unauthenticated IP check endpoint | Rate limit applied (e.g. 10/minute per IP) via `ip_check` profile; endpoint remains unauthenticated by design. |
| **M-07** | Proxmox SSL verification off by default | `verify_ssl` default changed to `True` in Proxmox config schema. |
| **M-09** | NATS publish buffer silent drop | When buffer is full, a warning is logged before dropping the oldest message. |
| **M-12** | Cron validation at profile creation | Cron expression validated with `CronTrigger.from_crontab()` on create/update; invalid cron returns 400 with message. |
| **M-14** | SMTP with no timeout | Notification worker SMTP send wrapped in `asyncio.wait_for(..., timeout=30)`. |
| **M-15** | Password reset token in URL | Reset link in email no longer includes token in URL. Token provided in email body; frontend reset page uses form input and POST body for token. |
| **M-17** | No scan resource limits | CIDR limited (e.g. max /12, max ~1M addresses). Global concurrent scan limit (e.g. 2) enforced; excess returns error. |
| **M-18** | Demo user expiration not enforced | Daily scheduler job disables users with `role=demo` and `demo_expires <= now`. |

**Deferred / optional (not implemented in this patch):**

- **M-06** Audit log hash chain — design/append-only storage.
- **M-08** INET-based network matching — query optimization.
- **M-10** Circuit breaker dict eviction — memory tuning.
- **M-11** Rate limiter profile cache — performance.
- **M-13** Session context managers in scheduler jobs — lifecycle refactor.
- **M-16** File upload backend re-validation — broader upload hardening.

---

## Deployment Notes

1. **Secrets and env**
   - Set `CB_JWT_SECRET` (or `CB_JWT_SECRET_ENV`) explicitly; no fallback secret.
   - Set `CB_DB_PASSWORD` (and thus `POSTGRES_PASSWORD` / `CB_DB_URL`); no default DB password.
   - For cross-origin frontends, set `CORS_ORIGINS` in production.

2. **OAuth and API tokens**
   - Existing OAuth tokens in DB are read with legacy plaintext support; new/updated tokens are stored encrypted.
   - API tokens now use HMAC-SHA256; existing tokens may need to be re-issued after upgrade.

3. **Proxmox**
   - New configs default to `verify_ssl=True`; existing configs unchanged until updated.

4. **Scans**
   - Large CIDRs (e.g. &gt; /12) and excess concurrent scans are rejected; adjust limits in code if your use case requires different values.

---

## References

- Full findings and remediation details: **Security Report.md**
- Plan used for implementation: **security_vulnerabilities_remediation_040f669e.plan.md** (if present in repo)
