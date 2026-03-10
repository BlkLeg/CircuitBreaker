

|  Shawn P \<ogcarlton@gmail.com\>  | 9:59 PM (0 minutes ago) |  |  |
| :---- | ----: | ----: | ----: |
|  to me  |  |  |  |

\# Circuit Breaker \- Security & Architecture Audit Report

\*\*Date:\*\* 2026-03-10

\*\*Version Audited:\*\* v0.2.0-beta (commit \`54e37bd\`)

\*\*Methodology:\*\* Automated multi-agent static analysis across 6 domains

\*\*Scope:\*\* Full codebase — backend (Python/FastAPI), frontend (React), infrastructure (Docker/CI/CD), integrations

\---

\#\# Executive Summary

Circuit Breaker is a self-hosted homelab infrastructure visualization platform with a FastAPI backend, React frontend, PostgreSQL database, and NATS message bus. The codebase demonstrates solid security foundations — non-root containers, Argon2 password hashing, RBAC, parameterized SQL queries, and httpOnly session cookies. However, this audit identified \*\*8 critical\*\*, \*\*14 high\*\*, \*\*18 medium\*\*, and \*\*12 low\*\* severity findings across authentication, input validation, infrastructure, and architecture domains.

The most urgent issues are \*\*command injection vectors\*\* in nmap/SNMP integration, \*\*SSRF in webhooks and Proxmox\*\*, \*\*JWT audience validation bypass\*\*, and \*\*unencrypted NATS communication\*\*. These should be remediated before any production or internet-facing deployment.

| Severity | Count | Key Areas |

|----------|-------|-----------|

| CRITICAL | 8 | Command injection, JWT bypass, SSRF, default credentials |

| HIGH | 14 | Session cache, WebSocket races, credential exposure, Docker socket |

| MEDIUM | 18 | CSRF gaps, file uploads, audit log integrity, pool exhaustion |

| LOW/INFO | 12 | Logging, type hints, documentation gaps |

\---

\#\# Table of Contents

1\. \[Critical Findings\](\#1-critical-findings)

2\. \[High Severity Findings\](\#2-high-severity-findings)

3\. \[Medium Severity Findings\](\#3-medium-severity-findings)

4\. \[Low / Informational Findings\](\#4-low--informational-findings)

5\. \[Architecture Review\](\#5-architecture-review)

6\. \[Strengths\](\#6-strengths)

7\. \[Remediation Roadmap\](\#7-remediation-roadmap)

8\. \[Secure Deployment Checklist\](\#8-secure-deployment-checklist)

\---

\#\# 1\. Critical Findings

\#\#\# C-01: Command Injection via Nmap Arguments

\*\*Files:\*\* \`apps/backend/src/app/services/discovery\_service.py:246,390-410\`, \`apps/backend/src/app/api/discovery.py:246\`

User-supplied \`nmap\_arguments\` are passed to \`nm.scan()\`, which internally constructs a shell command. The \`\_sanitise\_nmap\_args\_for\_unpriv()\` function (lines 372-387) only removes specific flags but does \*\*not\*\* block shell metacharacters (\`; | $() \\\`\`).

\`\`\`python

\# User-controlled input flows to shell execution

await loop.run\_in\_executor(None, lambda: nm.scan(hosts=cidr, arguments=effective\_args))

\`\`\`

A payload like \`-oX /tmp/evil.sh && id\` could execute arbitrary commands.

\*\*Impact:\*\* Remote code execution by any admin user.

\*\*Fix:\*\*

\- Implement an allowlist of safe nmap flags (\`-sT\`, \`-sV\`, \`-p\`, \`-T0-5\`, \`-F\`, \`--open\`)

\- Parse arguments with \`shlex.split()\` and validate each token

\- Reject any argument containing \`;\`, \`|\`, \`$\`, \`\` \` \`\`, \`(\`, \`)\`, \`\>\`, \`\<\`

\- Add \`max\_length=256\` constraint on the schema field

\---

\#\#\# C-02: Command Injection in SNMP Community String

\*\*Files:\*\* \`apps/backend/src/app/integrations/snmp\_generic.py:4-14\`, \`apps/backend/src/app/integrations/idrac.py:13-23\`

SNMP community strings from telemetry config are passed unsanitized to \`subprocess.run()\`:

\`\`\`python

r \= subprocess.run(

    \["snmpget", "-v2c", "-c", community, "-Oqv", host, oid\], ...

)

\`\`\`

While using a list (not a shell string) mitigates basic shell injection, the \`community\` parameter is not validated against allowed characters. Certain values could still cause unexpected behavior depending on the SNMP tool version.

\*\*Impact:\*\* Potential code execution on the backend server via crafted community strings.

\*\*Fix:\*\* Validate community strings against \`^\[a-zA-Z0-9\_.-\]+$\`. Use \`shlex.quote()\` as defense-in-depth.

\---

\#\#\# C-03: JWT Audience Validation Bypass (Legacy Token Fallback)

\*\*File:\*\* \`apps/backend/src/app/core/security.py:242-255\`

JWT validation falls back to \`verify\_aud=False\` for legacy tokens:

\`\`\`python

payload \= jwt.decode(

    raw\_token, cfg.jwt\_secret, algorithms=\["HS256"\],

    options={"verify\_aud": False} \# Disables audience validation entirely

)

\`\`\`

This allows tokens issued for one purpose (password reset \`aud: cb:change-password\`, MFA challenge) to be used as session tokens.

\*\*Impact:\*\* Token confusion attacks — password reset or MFA tokens can authenticate as full sessions.

\*\*Fix:\*\* Remove the \`verify\_aud=False\` fallback. Require explicit \`aud\` claims on all JWTs. Migrate legacy tokens via a one-time rotation.

\---

\#\#\# C-04: Hardcoded Fallback JWT Secret

\*\*File:\*\* \`apps/backend/src/app/core/users.py:24-26\`

\`\`\`python

\_FALLBACK\_SECRET \= (

    os.environ.get("CB\_VAULT\_KEY") or os.environ.get("CB\_API\_TOKEN") or secrets.token\_hex(32)

)

\`\`\`

If neither environment variable is set, a random secret is generated at import time. This means:

\- All JWTs are invalidated on every restart

\- No persistent secret exists — sessions break silently

\- The fallback shares the vault encryption key as the JWT signing key (if \`CB\_VAULT\_KEY\` is set), creating a single point of compromise

\*\*Impact:\*\* Denial of service (sessions lost on restart), or total auth compromise if vault key leaks.

\*\*Fix:\*\* Require an explicit, dedicated JWT secret. Never auto-generate at runtime. Separate JWT signing key from vault encryption key.

\---

\#\#\# C-05: Unencrypted OAuth Access Tokens in Database

\*\*File:\*\* \`apps/backend/src/app/api/auth\_oauth.py:224,381,462,569\`

\`\`\`python

user.oauth\_tokens \= json.dumps(oauth\_tokens) \# Plaintext in DB

\`\`\`

OAuth access tokens (GitHub, Google, OIDC) are stored as plaintext JSON. These are long-lived credentials granting access to external systems.

\*\*Impact:\*\* Database breach exposes all linked OAuth accounts. Attacker can impersonate users on external providers.

\*\*Fix:\*\* Encrypt \`oauth\_tokens\` using the credential vault (\`vault.encrypt()\`) before storage. Add a migration to encrypt existing plaintext tokens.

\---

\#\#\# C-06: Default Database Password "breaker"

\*\*Files:\*\* \`docker/docker-compose.yml:18\`, \`docker/docker-compose.prod.yml:30\`

\`\`\`yaml

POSTGRES\_PASSWORD=${CB\_DB\_PASSWORD:-breaker}

\`\`\`

The fallback \`breaker\` is used in both development and production compose files. Many deployments will run with this default.

\*\*Impact:\*\* Any exposed PostgreSQL port is trivially compromisable.

\*\*Fix:\*\* Remove the \`:-breaker\` fallback. Require explicit \`CB\_DB\_PASSWORD\`. Generate a strong random password during \`install.sh\` first run.

\---

\#\#\# C-07: SSRF in Webhook URL Dispatch

\*\*Files:\*\* \`apps/backend/src/app/workers/webhook\_worker.py:111-116\`, \`apps/backend/src/app/api/webhooks.py:304\`

Webhook URLs are validated for format (Pydantic \`HttpUrl\`) but not for target — no SSRF protection:

\`\`\`python

resp \= await [client.post](http://client.post/)(rule.target\_url, content=body\_bytes, ...)

\`\`\`

An attacker can configure webhooks targeting \`[http://localhost:5432/\`](http://localhost:5432/), \`[http://169.254.169.254/\`](http://169.254.169.254/) (cloud metadata), or any internal service.

\*\*Impact:\*\* Internal service enumeration, credential theft from cloud metadata, lateral movement.

\*\*Fix:\*\* Add IP range validation blocking loopback, link-local, and RFC1918 ranges before dispatching. Apply the same check in the test webhook endpoint.

\---

\#\#\# C-08: SSRF in Proxmox Integration

\*\*Files:\*\* \`apps/backend/src/app/schemas/proxmox.py:14\`, \`apps/backend/src/app/services/proxmox\_service.py:126,151\`

Proxmox \`config\_url\` uses a plain \`str\` field — no URL type validation, no SSRF protection:

\`\`\`python

config\_url: str \= Field(..., min\_length=1) \# No HttpUrl, no IP check

\`\`\`

\*\*Impact:\*\* Same as C-07 — internal network scanning and credential theft via admin-configured URLs.

\*\*Fix:\*\* Change to \`HttpUrl\` type. Apply SSRF IP range validation. Reject localhost and private IPs.

\---

\#\# 2\. High Severity Findings

\#\#\# H-01: Unauthenticated NATS Message Bus

\*\*Files:\*\* \`docker/docker-compose.yml:28-38\`, \`apps/backend/src/app/core/nats\_client.py:37-73\`

NATS runs with no authentication and no TLS. Any container on \`cb\_net\` can publish/subscribe to all topics. Management port 8222 is also exposed internally.

\`\`\`yaml

command: \['--jetstream', '-m', '8222'\] \# No \--auth, no \--tls

\`\`\`

\*\*Impact:\*\* Message injection, eavesdropping on discovery/webhook/notification events, fake event injection.

\*\*Fix:\*\* Enable NATS authentication and TLS. Restrict management port access.

\---

\#\#\# H-02: WebSocket Connection Manager Race Condition

\*\*File:\*\* \`apps/backend/src/app/core/ws\_manager.py:74-89\`

\`disconnect()\` is not protected by the async lock:

\`\`\`python

def disconnect(self, ws: WebSocket) \-\> None:

    self.\_connections.discard(ws) \# NOT under \_lock

    meta \= self.\_meta.pop(ws, None)

\`\`\`

Concurrent \`broadcast()\` and \`disconnect()\` calls can corrupt the connection set.

\*\*Impact:\*\* Connection leaks, stale \`\_ip\_counts\`, potential DoS under high WebSocket churn.

\*\*Fix:\*\* Wrap \`disconnect()\` body in \`async with self.\_lock\`.

\---

\#\#\# H-03: Thread-Unsafe Session Validation Cache

\*\*File:\*\* \`apps/backend/src/app/core/security.py:29-62\`

Plain dict with manual locking, no automatic eviction, 2000-entry max with oldest-eviction on overflow:

\`\`\`python

\_session\_cache: dict\[str, tuple\[int, float\]\] \= {}

\`\`\`

60-second TTL means revoked sessions remain valid for up to 60 seconds after logout.

\*\*Impact:\*\* Memory leak potential, session revocation delay, cache corruption under burst load.

\*\*Fix:\*\* Use \`cachetools.TTLCache(maxsize=2000, ttl=10)\`. Reduce TTL to 5-10 seconds. Add cache invalidation on explicit logout.

\---

\#\#\# H-04: Docker Socket Mounted in Backend

\*\*File:\*\* \`docker/docker-compose.yml:75-77\`

\`\`\`yaml

volumes:

  \- /var/run/docker.sock:/var/run/docker.sock:ro

\`\`\`

Even read-only socket access allows enumerating all containers, images, volumes, and labels (which may contain secrets).

\*\*Impact:\*\* Compromised backend gains full visibility into Docker host.

\*\*Fix:\*\* Use a dedicated read-only Docker API proxy (e.g., Tecnativa/docker-socket-proxy). Require explicit opt-in via settings.

\---

\#\#\# H-05: On-Demand TLS Certificate Generation Unbounded

\*\*File:\*\* \`docker/Caddyfile:27-32\`

\`\`\`caddyfile

on\_demand\_tls {

    ask [http://backend:8000/api/v1/health](http://backend:8000/api/v1/health)

}

\`\`\`

Any IP connecting to port 443 triggers certificate issuance if the health endpoint responds 200\. No limit on certificates generated.

\*\*Impact:\*\* DoS via certificate storage exhaustion. Uncontrolled certificate issuance.

\*\*Fix:\*\* Add \`max\_certificates 10\` or disable on-demand TLS in production. Use pre-provisioned certificates.

\---

\#\#\# H-06: No Network Segmentation Between Services

\*\*File:\*\* \`docker/docker-compose.yml:3-6\`

All services (backend, workers, NATS, Postgres, Caddy) share a single bridge network. A compromised worker can directly connect to Postgres.

\*\*Impact:\*\* Unrestricted lateral movement after any single service compromise.

\*\*Fix:\*\* Separate into \`frontend\`, \`backend-api\`, and \`workers\` networks with explicit inter-network links.

\---

\#\#\# H-07: Silent Vault Initialization Failure

\*\*File:\*\* \`apps/backend/src/app/main.py:274-278\`

\`\`\`python

except Exception as \_ve:

    \_logger.warning("Vault init failed during startup: %s", \_ve)

    \# App continues running without vault\!

\`\`\`

If the vault fails to initialize, the app runs without encryption. Encrypted credentials become inaccessible but the failure is only a warning.

\*\*Impact:\*\* Silent degradation — integrations fail mysteriously. No fail-fast behavior.

\*\*Fix:\*\* \`raise SystemExit(1)\` on vault initialization failure.

\---

\#\#\# H-08: Weak WebSocket Authentication

\*\*Files:\*\* \`apps/backend/src/app/api/ws\_discovery.py:94-157\`, \`ws\_topology.py:201-258\`

Token sent as plaintext first WebSocket message. No enforcement of WSS. No token rotation during connection lifetime.

\*\*Impact:\*\* Token interception on non-TLS connections. Session hijacking.

\*\*Fix:\*\* Enforce WSS only. Prefer cookie-based auth. Remove legacy "token as first message" method.

\---

\#\#\# H-09: API Token Hash Not Salted

\*\*File:\*\* \`apps/backend/src/app/api/auth.py:359-360\`

\`\`\`python

token\_hash \= hashlib.sha256(raw\_token.encode()).hexdigest() \# No salt

\`\`\`

\*\*Impact:\*\* Rainbow table attacks if token database leaks.

\*\*Fix:\*\* Use HMAC-SHA256 with a per-token salt, or bcrypt.

\---

\#\#\# H-10: MFA Backup Codes Not Rate Limited

\*\*File:\*\* \`apps/backend/src/app/api/auth.py:872-940\`

MFA verification endpoint accepts both TOTP and backup codes with no per-attempt rate limiting. Only 8 backup codes exist.

\*\*Impact:\*\* Brute-force of backup codes by attacker with intercepted \`mfa\_token\`.

\*\*Fix:\*\* Lock account after 3-5 failed MFA attempts. Add per-user rate limiting on \`/auth/mfa/verify\`.

\---

\#\#\# H-11: Masquerade Token Not Audited

\*\*File:\*\* \`apps/backend/src/app/api/admin\_users.py:351-376\`

Admin masquerade creates a 15-minute token with no audit log entry and no notification to the target user.

\*\*Impact:\*\* Undetectable admin impersonation of any user.

\*\*Fix:\*\* Log masquerade events. Notify the impersonated user. Include masquerade flag in JWT payload.

\---

\#\#\# H-12: Path Traversal in Profile Photo Upload

\*\*File:\*\* \`apps/backend/src/app/services/auth\_service.py:\~171\`

\`\`\`python

filename \= f"{[user.id](http://user.id/)}-{profile\_photo.filename or 'photo.' \+ ext}"

((\_PROFILES\_DIR) / filename).write\_bytes(data)

\`\`\`

Filename from upload used directly — \`1-../../etc/cron.d/evil.png\` writes outside the upload directory.

\*\*Impact:\*\* Arbitrary file write to filesystem.

\*\*Fix:\*\* Use hash-based filenames: \`f"{[user.id](http://user.id/)}-{hashlib.sha256(data).hexdigest()\[:12\]}.{ext}"\`. Reject any filename containing \`/\` or \`..\`.

\---

\#\#\# H-13: Connection Pool Exhaustion Under Load

\*\*File:\*\* \`apps/backend/src/app/db/session.py:29-35\`

Default pool: 10 connections \+ 10 overflow \= 20 max. The \`main.py\` lifespan creates 15+ SessionLocal instances at startup for scheduled jobs, consuming a significant portion before handling any requests.

\*\*Impact:\*\* 21st concurrent request blocks indefinitely.

\*\*Fix:\*\* Increase defaults to \`DB\_POOL\_SIZE=20, DB\_MAX\_OVERFLOW=20\`. Use context managers in scheduled jobs instead of long-lived sessions.

\---

\#\#\# H-14: Credential Exposure in Telemetry Configuration

\*\*File:\*\* \`apps/backend/src/app/api/telemetry.py:54-82\`

SNMP community strings and iDRAC/iLO passwords are encrypted at rest but transmitted in plaintext if HTTPS is not enforced. API responses may include decrypted credentials.

\*\*Impact:\*\* Credential interception. Lateral movement to out-of-band management systems.

\*\*Fix:\*\* Enforce HTTPS-only for telemetry endpoints. Mask secrets in API responses (return \`"\*\*\*\*"\`).

\---

\#\# 3\. Medium Severity Findings

\#\#\# M-01: dangerouslySetInnerHTML Without Sanitization

\*\*Files:\*\* \`apps/frontend/src/components/MarkdownViewer.jsx:7\`, \`apps/frontend/src/components/Map/Sidebar.jsx:133-135\`

Backend-rendered HTML (\`body\_html\`) is inserted directly via \`dangerouslySetInnerHTML\` with no client-side sanitization.

\*\*Fix:\*\* Apply DOMPurify before rendering. Verify backend sanitizes HTML with bleach or equivalent.

\---

\#\#\# M-02: No Content Security Policy Headers

\*\*File:\*\* Backend/Caddy configuration

No CSP headers are set. Allows inline scripts, eval(), and external resource loading.

\*\*Fix:\*\* Add via Caddy: \`Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' wss:; frame-ancestors 'none'\`

\---

\#\#\# M-03: No CSRF Tokens (Relies on SameSite Only)

Frontend uses httpOnly cookies with no explicit CSRF token. Depends entirely on \`SameSite\` cookie attribute.

\*\*Fix:\*\* Verify backend sets \`SameSite=Strict\`. Consider adding explicit CSRF token for defense-in-depth.

\---

\#\#\# M-04: Permissive CORS Configuration

\*\*File:\*\* \`apps/backend/src/app/main.py:731-736\`

\`\`\`python

allow\_origins=settings.cors\_origins, \# Defaults to \["\*"\]

allow\_credentials=True, \# Dangerous with "\*"

\`\`\`

\*\*Fix:\*\* Default to \`allow\_origins=\[\]\` (same-origin only). Document production override.

\---

\#\#\# M-05: Unauthenticated IP Check Endpoint

\*\*File:\*\* \`apps/backend/src/app/api/ip\_check.py:27-43\`

Intentionally unauthenticated, reveals all IP addresses and port bindings in the system. No rate limiting.

\*\*Fix:\*\* Add rate limiting (\`10/minute\` per IP). Consider requiring authentication.

\---

\#\#\# M-06: Audit Log Integrity Not Verified

\*\*File:\*\* \`apps/backend/src/app/db/models.py\` (Log model)

Audit logs have no HMAC/signature, no hash chain, and no tamper detection. Database admins can silently modify logs.

\*\*Fix:\*\* Implement hash-chain verification. Consider append-only storage.

\---

\#\#\# M-07: SSL Verification Disabled by Default for Proxmox

\*\*File:\*\* \`apps/backend/src/app/schemas/proxmox.py:18\`

\`\`\`python

verify\_ssl: bool \= False \# Default

\`\`\`

\*\*Fix:\*\* Change default to \`True\`. Show warning when disabled.

\---

\#\#\# M-08: Unbounded N+1 Query in Network Matching

\*\*File:\*\* \`apps/backend/src/app/services/discovery\_service.py:26-36,39-72\`

For each discovered IP, all networks are fetched and iterated. 1000 IPs x 100 networks \= 100K containment checks.

\*\*Fix:\*\* Use PostgreSQL INET operators (\`cidr \>\> ip\`) for single-query matching. Cache network list.

\---

\#\#\# M-09: Unbounded NATS Publish Buffer (Silent Drop)

\*\*File:\*\* \`apps/backend/src/app/core/nats\_client.py:31\`

\`deque(maxlen=200)\` silently drops oldest messages when full. No logging of dropped messages.

\*\*Fix:\*\* Log each dropped message. Alert when buffer is consistently at capacity.

\---

\#\#\# M-10: Global Circuit Breaker Dict Never Evicted

\*\*File:\*\* \`apps/backend/src/app/core/circuit\_breaker.py:104-112\`

\`\`\`python

\_breakers: dict\[str, CircuitBreaker\] \= {} \# Grows forever

\`\`\`

\*\*Fix:\*\* Add max-age eviction or use \`WeakValueDictionary\`.

\---

\#\#\# M-11: Rate Limiter Queries DB Per Request

\*\*File:\*\* \`apps/backend/src/app/core/rate\_limit.py:35-48\`

Every rate-limited request queries the database for the current profile.

\*\*Fix:\*\* Cache profile in memory with 5-10 minute TTL.

\---

\#\#\# M-12: Missing Cron Validation at Profile Creation

\*\*File:\*\* \`apps/backend/src/app/main.py:441-453\`

Invalid cron expressions are caught at scheduler startup but not at profile creation. Users get no immediate feedback.

\*\*Fix:\*\* Validate cron syntax at creation time. Return 400 immediately.

\---

\#\#\# M-13: Session Lifecycle Not Properly Closed in Scheduled Jobs

\*\*File:\*\* \`apps/backend/src/app/main.py:515-642\`

Multiple scheduler jobs create \`SessionLocal()\` instances. If subtasks outlive the coroutine, sessions are used after close.

\*\*Fix:\*\* Use explicit context managers. Add exception logging before re-raising.

\---

\#\#\# M-14: Synchronous SMTP on Async Event Loop (No Timeout)

\*\*File:\*\* \`apps/backend/src/app/workers/notification\_worker.py:60-67\`

\`run\_in\_executor\` wraps sync SMTP but has no timeout. A hung SMTP server blocks a thread pool worker indefinitely.

\*\*Fix:\*\* Wrap with \`asyncio.wait\_for(..., timeout=30.0)\`. Consider using \`aiosmtplib\`.

\---

\#\#\# M-15: Password Reset Token in URL Query Parameter

\*\*File:\*\* \`apps/frontend/src/pages/ResetPasswordPage.jsx:66\`

Reset token is passed via \`?token=...\` — logged in browser history, server logs, and referrer headers.

\*\*Fix:\*\* Use POST-based flow with token in request body.

\---

\#\#\# M-16: File Uploads Lack Backend Re-validation

\*\*Files:\*\* Multiple upload endpoints across \`auth.py\`, \`branding.js\`, \`DocEditor.jsx\`

Client-side MIME type and size checks exist, but backend must independently validate file type (magic bytes), scan content, and enforce size limits.

\*\*Fix:\*\* Validate with PIL/Pillow for images. Check magic bytes. Re-encode to strip metadata.

\---

\#\#\# M-17: No Scan Resource Limits

\*\*File:\*\* \`apps/backend/src/app/api/discovery.py:230-263\`

No maximum CIDR size validation. An admin could scan \`/1\` (2 billion IPs). No concurrent scan limit.

\*\*Fix:\*\* Enforce max CIDR size (e.g., \`/12\`). Limit concurrent scans per user to 2\.

\---

\#\#\# M-18: Demo User Expiration Not Strictly Enforced

\*\*File:\*\* \`apps/backend/src/app/api/auth.py:136-171\`

Demo sessions have \`demo\_expires\` but no token refresh prevention and no automatic cleanup.

\*\*Fix:\*\* Block token refresh for demo users. Auto-delete expired demo accounts.

\---

\#\# 4\. Low / Informational Findings

| ID | Finding | File |

|----|---------|------|

| L-01 | Unpinned \`cloudflare/cloudflared:latest\` image | \`docker/docker-compose.yml:225\` |

| L-02 | \`curl \\| bash\` install pattern (supply chain risk) | \`install.sh:9-10\` |

| L-03 | Cloudflare tunnel token in CLI args (visible in \`ps\`) | \`docker/docker-compose.yml:236\` |

| L-04 | No structured logging (string formatting, not JSON) | Throughout backend |

| L-05 | Missing type hints on worker functions | \`workers/discovery.py\`, \`notification\_worker.py\` |

| L-06 | Hardcoded health file path \`/tmp/worker.healthy\` | \`workers/webhook\_worker.py:18\` |

| L-07 | No log rotation configured in Docker | Docker Compose files |

| L-08 | User email enumeration via login endpoint timing | \`api/auth.py:206\` |

| L-09 | Gravatar hash exposed in unauthenticated context | \`api/auth.py:469-495\` |

| L-10 | Frontend doesn't respect \`Retry-After\` on 429 | \`apps/frontend/src/api/client.jsx:64-73\` |

| L-11 | Source maps set to \`hidden\` (good) but no SRI hashes | \`vite.config.ts:45\` |

| L-12 | No branch protection rules documented for CI/CD | \`.github/workflows/\` |

\---

\#\# 5\. Architecture Review

\#\#\# Structural Assessment

The codebase follows a layered architecture: \`api/\` (route handlers) \-\> \`services/\` (business logic) \-\> \`db/\` (data access), with \`core/\` providing cross-cutting concerns (auth, rate limiting, WebSocket management).

\*\*Positive patterns:\*\*

\- Clean error hierarchy (\`AppError\` base class with status codes)

\- Circuit breaker pattern for external integrations (Proxmox, iDRAC, iLO)

\- WebSocket manager with per-IP connection limits

\- Audit logging middleware across all mutation endpoints

\- Graceful degradation when NATS is unavailable

\*\*Architectural concerns:\*\*

| Area | Issue | Impact |

|------|-------|--------|

| Async/sync boundary | Many sync services called from async handlers via \`run\_sync\_with\_retry\` | Cognitive overhead, potential thread starvation |

| Global mutable state | Session cache, circuit breakers, NATS buffer all use module-level dicts | Memory leaks, test isolation issues |

| Missing pagination | Several queries use \`.all()\` without limits | OOM on large datasets |

| Worker architecture | Workers share same DB pool as API server | Pool contention under load |

| Frontend state | Client-side RBAC checks are UX-only | Must be enforced server-side (which it is) |

\#\#\# Dependency Health

| Layer | Package Management | Pinning | Status |

|-------|-------------------|---------|--------|

| Backend | Poetry \-\> requirements.txt | Fully pinned | Good |

| Frontend | npm \+ package-lock.json | Lock file present | Good |

| Docker | Base images | All pinned except cloudflared | Mostly good |

| CI/CD | GitHub Actions | \`@v4\`/\`@v5\` tags | Good |

\---

\#\# 6\. Strengths

The audit identified several well-implemented security measures:

\- \*\*Password hashing:\*\* Argon2 with proper verification

\- \*\*SQL injection protection:\*\* All queries use parameterized statements via SQLAlchemy ORM

\- \*\*Session cookies:\*\* httpOnly, SameSite, Secure flags

\- \*\*RBAC:\*\* Role hierarchy with FastAPI dependency injection

\- \*\*Client-side password hashing:\*\* SHA-256 pre-hash before transmission (defense-in-depth)

\- \*\*Axios interceptor:\*\* Strips accidental plaintext passwords from API payloads

\- \*\*Multi-stage Docker build:\*\* Compiler tooling excluded from runtime image

\- \*\*Privilege dropping:\*\* Container starts as root only for \`chown\`, then drops to UID 1000 via \`gosu\`

\- \*\*Health checks:\*\* Python stdlib-based (no curl/wget needed in image)

\- \*\*Security headers:\*\* HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy set via Caddy

\- \*\*Source maps:\*\* Hidden in production builds

\- \*\*Dependency scanning:\*\* Snyk \+ Trivy in CI/CD pipeline

\---

\#\# 7\. Remediation Roadmap

\#\#\# Immediate (before any production deployment)

| Priority | ID | Action | Effort |

|----------|----|--------|--------|

| 1 | C-01 | Allowlist nmap arguments, block shell metacharacters | 2h |

| 2 | C-02 | Validate SNMP community strings against safe regex | 30m |

| 3 | C-03 | Remove \`verify\_aud=False\` fallback in JWT validation | 1h |

| 4 | C-07 | Add SSRF IP range validation to webhook dispatch | 2h |

| 5 | C-08 | Add SSRF IP range validation to Proxmox URLs | 1h |

| 6 | C-06 | Remove default DB password, require explicit config | 30m |

| 7 | H-12 | Fix path traversal in profile photo upload | 30m |

| 8 | H-07 | Fail-fast on vault initialization failure | 15m |

\#\#\# Short-term (next 2 sprints)

| Priority | ID | Action | Effort |

|----------|----|--------|--------|

| 9 | C-04 | Separate JWT signing key from vault key | 2h |

| 10 | C-05 | Encrypt OAuth tokens with vault before storage | 3h |

| 11 | H-01 | Enable NATS authentication and TLS | 4h |

| 12 | H-02 | Fix WebSocket disconnect race condition | 30m |

| 13 | H-03 | Replace session cache with \`cachetools.TTLCache\` | 1h |

| 14 | H-06 | Implement Docker network segmentation | 2h |

| 15 | H-09 | Salt API token hashes | 2h |

| 16 | H-10 | Rate limit MFA verification endpoint | 1h |

| 17 | H-11 | Add audit logging for admin masquerade | 1h |

| 18 | M-01 | Add DOMPurify for \`dangerouslySetInnerHTML\` | 1h |

| 19 | M-04 | Change CORS default from \`\["\*"\]\` to \`\[\]\` | 15m |

| 20 | M-17 | Add max CIDR size and concurrent scan limits | 2h |

\#\#\# Medium-term (this quarter)

| Priority | ID | Action | Effort |

|----------|----|--------|--------|

| 21 | M-02 | Add CSP headers via Caddy | 2h |

| 22 | M-06 | Implement audit log hash chain | 4h |

| 23 | M-08 | Optimize N+1 network matching with INET operators | 3h |

| 24 | H-13 | Increase default pool size, refactor scheduled job sessions | 3h |

| 25 | M-11 | Cache rate limiter profile lookup | 1h |

| 26 | H-04 | Replace Docker socket with API proxy | 4h |

| 27 | H-05 | Limit on-demand TLS certificates | 30m |

| 28 | L-04 | Implement structured JSON logging | 4h |

\---

\#\# 8\. Secure Deployment Checklist

\`\`\`

Pre-deployment:

\[ \] Set strong CB\_DB\_PASSWORD (32+ characters, generated)

\[ \] Set dedicated CB\_JWT\_SECRET (separate from CB\_VAULT\_KEY)

\[ \] Set strong CB\_VAULT\_KEY (Fernet.generate\_key())

\[ \] Configure NATS authentication credentials

\[ \] Review and restrict CORS\_ORIGINS

\[ \] Pin cloudflare/cloudflared to specific version

\[ \] Run \`pip audit\` and \`npm audit\` against dependencies

Network:

\[ \] Bind Caddy to specific interfaces (not 0.0.0.0)

\[ \] Configure host firewall (UFW/iptables)

\[ \] Verify HTTPS is enforced (no plain HTTP API access)

\[ \] Restrict Docker socket access or use API proxy

\[ \] Segment Docker networks (frontend/backend/workers)

Runtime:

\[ \] Verify vault initializes successfully (check logs for warnings)

\[ \] Confirm session cookie has SameSite=Strict, Secure, HttpOnly

\[ \] Test that demo users cannot access admin endpoints

\[ \] Verify WebSocket connections use WSS only

\[ \] Confirm audit logging is active for auth events

\[ \] Set up log rotation (max-size: 100m, max-file: 5\)

Monitoring:

\[ \] Alert on repeated auth failures (brute force detection)

\[ \] Monitor NATS buffer utilization

\[ \] Track DB connection pool usage

\[ \] Set up certificate expiry monitoring

\`\`\`

\---  
