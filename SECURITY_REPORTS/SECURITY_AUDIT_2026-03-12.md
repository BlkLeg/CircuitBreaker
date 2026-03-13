# Circuit Breaker Security Audit

Date: 2026-03-12

Scope: backend API, frontend exposure points, auth/session handling, upload paths, reverse proxy config, repository hygiene, and the automated scan output from `make security-scan`.

Methodology:
- Manual code review of high-risk paths in `apps/backend/src/app`, `apps/frontend/src`, and `docker/`
- Review of the latest automated scan run: Bandit, Semgrep, Gitleaks, ESLint security, Hadolint, Checkov, Trivy, and npm audit
- Triage by exploitability, blast radius, and confidence

Raw tool output:
- `security_scan_report.md` contains the full automated scan output from the latest run

## Executive Summary

The application is not broadly broken, but it does have several real security issues that should be addressed before treating the deployment surface as hardened.

The highest-confidence issue is repository secret exposure in scan results and tracked runtime artifacts. The next tier is operational hardening: debug traceback exposure if `dev_mode` is enabled, pre-bootstrap settings disclosure, and avoidable upload-path resource exhaustion. There are also a few medium-risk configuration issues in the nginx/FastAPI boundary that weaken intended protections.

## Triage Summary

| Severity | Count | Notes |
|---|---:|---|
| Critical | 1 | Confirmed secret exposure risk in repository history / tracked artifacts |
| High | 1 | High-impact information disclosure if debug mode is enabled in production |
| Medium | 5 | Confirmed hardening gaps with realistic abuse cases |
| Low | 4 | Defense-in-depth issues and noisy scan findings with limited exploitability |

## Critical Findings

### 1. Secret Material Present In Repository History / Tracked Artifacts

Evidence:
- Latest `make security-scan` run reported 4 Gitleaks hits
- One hit is a real-looking JWT secret in tracked runtime log history: `docker/circuitbreaker-data/backend_api_err.log`
- Additional hits include placeholders and Alembic revision strings that look like false positives, but the log-secret finding should be treated as real until proven otherwise

Why this matters:
- If the leaked JWT secret or any adjacent sensitive value was ever active in a deployed environment, an attacker with repo access can forge sessions or replay privileged auth state
- Even if rotated already, committing runtime logs with secrets is a recurring exposure pattern and an incident-response problem

Recommended remediation:
1. Rotate all potentially exposed secrets immediately: JWT secret, vault key, Redis password, NATS token, DB password, OAuth secrets if any were present in logs.
2. Remove tracked runtime logs from version control and add durable ignore rules for runtime output directories.
3. Purge the leaked material from git history if the repository is shared externally or with contractors.
4. Add a CI gate for Gitleaks on pull requests.

## High Findings

### 2. Full Traceback Disclosure If `dev_mode` Is Enabled In Production

Files:
- `apps/backend/src/app/main.py`

Evidence:
- The global exception handler returns `detail` and `traceback.format_exc()` whenever `settings.dev_mode` is true

Abuse path:
- Any unhandled exception becomes a remote disclosure of stack traces, code paths, local file layout, and potentially sensitive values embedded in exception messages
- This is especially dangerous during partial outages, migration drift, or malformed request handling where attackers can intentionally trigger failures

Why this is high and not critical:
- It is gated behind deployment configuration rather than always-on behavior
- If `dev_mode` flips on in production, the impact is severe

Recommended remediation:
1. Never return tracebacks to clients, even in dev mode; log them server-side only.
2. Return a correlation ID instead of raw exception detail.
3. Add a startup guard that refuses to run with `dev_mode=true` outside local/dev environments.

## Medium Findings

### 3. Pre-Bootstrap Settings Endpoint Discloses Internal Configuration

Files:
- `apps/backend/src/app/api/settings.py`

Evidence:
- `GET /api/v1/settings` permits anonymous access until `settings.jwt_secret` exists
- That response model can expose deployment metadata before auth is fully established

Likely disclosure surface:
- SMTP host/port and mail configuration state
- OAuth and SSO integration metadata
- CORS configuration and feature flags
- Operational defaults that reduce attacker guesswork during initial setup windows

Recommended remediation:
1. Split a minimal bootstrap-safe public endpoint from the full settings document.
2. Require auth for the full settings payload unconditionally.
3. If unauthenticated bootstrap is required, return only the exact fields needed by OOBE.

### 4. Upload Endpoints Enforce Size Only After Reading The Entire Body Into Memory

Files:
- `apps/backend/src/app/api/assets.py`

Evidence:
- Both upload handlers call `await file.read()` before enforcing `_MAX_ICON_BYTES`

Abuse path:
- An attacker can send repeated oversized requests and force application workers to buffer request bodies in memory before rejection
- nginx currently limits request size to 10 MB in `docker/nginx.mono.conf`, which bounds the worst case, but does not remove the amplification effect under concurrency

Recommended remediation:
1. Enforce request-size limits before full buffering using `Content-Length` and streaming reads.
2. Keep reverse-proxy body-size limits aligned with backend limits.
3. Apply endpoint-specific rate limiting to upload routes.

### 5. Clickjacking Header Policy Is Inconsistent Across nginx And FastAPI

Files:
- `docker/nginx.mono.conf`
- `apps/backend/src/app/middleware/security_headers.py`

Evidence:
- nginx sets `X-Frame-Options: SAMEORIGIN`
- FastAPI sets `X-Frame-Options: DENY`

Impact:
- The effective policy is weaker and ambiguous at the proxy/application boundary
- This is not a trivial exploit by itself, but it is exactly the kind of config drift that causes surprises during future refactors or proxy changes

Recommended remediation:
1. Define the header in one layer only.
2. Prefer `DENY` unless there is a documented framing requirement.
3. Keep CSP `frame-ancestors 'none'` aligned with the same intent.

### 6. CORS Policy Is Broader Than Necessary

Files:
- `apps/backend/src/app/main.py`
- `apps/backend/src/app/core/config.py`

Evidence:
- `allow_credentials=True`
- `allow_methods=["*"]`
- `allow_headers=["*"]`

Assessment:
- This is not an automatic critical issue because origins are still controlled by `settings.cors_origins`
- It does expand the trust surface and makes misconfiguration of allowed origins more dangerous than it needs to be

Recommended remediation:
1. Replace wildcard methods and headers with explicit allow-lists.
2. Add validation rejecting wildcard or malformed `cors_origins` in non-dev environments.
3. Document the exact browser clients that need cross-origin credentialed access.

### 7. User Icon Uploads Allow SVG Content

Files:
- `apps/backend/src/app/api/assets.py`

Evidence:
- `upload_user_icon` allows `image/svg+xml`
- Uploaded files are later served back under `/user-icons/`

Impact:
- Scriptable SVG is a historically fragile content type
- Depending on browser behavior, future proxy changes, or content-disposition handling, this can become a stored-XSS or content-confusion footgun

Recommended remediation:
1. Disallow SVG for user-uploaded icons unless there is a hard requirement.
2. If SVG must remain supported, sanitize server-side and serve with restrictive content-disposition/content-type handling.
3. Keep image allow-lists separate for branding/admin use and user content.

## Low Findings

### 8. Password Reset Service Logs Token Prefixes

Files:
- `apps/backend/src/app/services/password_reset_service.py`

Evidence:
- The service logs the first 8 characters of reset tokens on create, miss, and consume events

Assessment:
- This is not full token disclosure and the tokens are 15-minute, single-use values
- Still, logging token material at all increases forensic sensitivity requirements for logs

Recommended remediation:
- Remove token-prefix logging and replace it with opaque request IDs or user IDs only

### 9. Gravatar MD5 Usage Triggers Static Analysis

Files:
- `apps/backend/src/app/core/security.py`

Evidence:
- `gravatar_hash()` uses MD5, which Bandit flags

Assessment:
- This is expected for Gravatar compatibility and not a password-storage issue
- Treat as accepted risk or suppress with an explicit comment explaining why it is safe in context

### 10. DuckDB Dynamic SQL Uses String Formatting But Table Names Are Validated

Files:
- `apps/backend/src/app/db/duckdb_client.py`

Evidence:
- Semgrep/Bandit flag SQLAlchemy `text(f"...")`
- The code validates table names against a strict identifier regex before interpolation

Assessment:
- This is not a confirmed SQL injection in the current implementation
- It remains a maintenance-sensitive area because future contributors may weaken the validation or add more interpolated fragments

Recommended remediation:
- Keep table-name validation centralized and heavily tested

### 11. Excessive `except Exception: pass` Patterns Reduce Security Observability

Files:
- Multiple locations across backend services and websocket handlers, also reflected in Bandit output

Impact:
- Silent failure is not a direct exploit, but it makes security events, auth failures, and degraded protections harder to detect during incidents

Recommended remediation:
- Replace silent exception swallowing with scoped exceptions and structured warning logs where failure matters

## Automated Scan Notes

### Tool outputs worth actioning now

- Gitleaks: actionable because it indicates actual secret exposure risk
- Bandit / Semgrep findings around debug behavior, logging, and broad exception swallowing: useful and mostly aligned with manual review
- ESLint security warnings on new frontend code are mostly hygiene issues, not top-tier security defects in the currently reviewed attack paths

### Findings likely to be noisy or context-dependent

- nginx `missing-internal` findings on normal reverse-proxy locations
- h2c-smuggling rules on websocket upgrade paths without additional evidence of unsafe upstream behavior
- `subprocess` warnings where commands are invoked without shell expansion and arguments are validated or fixed

## Recommended Remediation Order

1. Rotate exposed secrets and stop tracking runtime logs.
2. Remove traceback responses from client-facing error handling.
3. Lock down anonymous pre-bootstrap settings exposure.
4. Fix upload buffering and align proxy/backend size enforcement.
5. Unify frame protection headers and tighten CORS allow-lists.
6. Remove or sanitize SVG uploads for user icons.
7. Reduce sensitive logging and silent exception swallowing.

## Bottom Line

The app does not show evidence of a single catastrophic always-on auth bypass, SQL injection, or broken password reset flow in the reviewed paths. The biggest current risks are repository hygiene, operational misconfiguration exposure, and several medium-grade hardening gaps that make exploitation easier when the environment is stressed or misconfigured.

If this system is internet-exposed or shared outside a tightly trusted network, the critical and medium findings above should be addressed before calling the deployment security review complete.