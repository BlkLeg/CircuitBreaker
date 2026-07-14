# CircuitBreaker — Deep Security Analysis

**Date:** 2026-07-13
**Version:** 0.3.1 (commit `0a791ecf`, branch `main`)
**Scope:** Full backend/frontend/deployment review. Focus on authentication, authorization,
tenant isolation, SSRF, deployment hardening, and logic errors.
**Analyst note:** This report supersedes the prior reports in `SECURITY_REPORTS/`
(`SECURITY_STANDING-1/2`, `SECURITY_AUDIT_2026-03-12`, Gemini/Trivy runs), which are outdated.
Findings below were verified against current source, not prior report state.

Prior audits closed out the well-known hardening items (timing-safe token comparison, security
headers, Docker socket isolation, read-only container, Redis `requirepass`, mandatory secrets,
one-way `auth_enabled`, WebSocket JWT validation). Those all still hold on `main` — see
"Verified-Good" at the end. The findings below are issues those audits did **not** cover, centered
on **multi-tenant data isolation**, which is the most serious gap in the current codebase.

I also checked `origin/dev`: its commits are migration/startup/dependency fixes and do **not**
touch any of the files implicated below, so none of these findings are already resolved there.

---

## Severity summary

| # | Severity | Finding |
|---|----------|---------|
| 1 | **Critical** | Cross-tenant data access (IDOR): RLS bypassed for the app role *and* no app-layer tenant filtering |
| 2 | High | RLS tenant variable set with transaction-local scope at pool checkout — mechanism is non-functional even if re-enabled |
| 3 | Medium | MFA can be bypassed through the `force_password_change` login branch |
| 4 | Medium | Webhook SSRF via DNS rebinding (validate-then-reresolve TOCTOU) |
| 5 | Medium | Rate limiting is in-memory + per-worker, keyed on proxy address — weak brute-force protection |
| 6 | Low | Account lockout not enforced on the force-change / MFA-challenge login branches |
| 7 | Low | Public status page discloses internal monitor URLs to anonymous users; no rate limit |
| 8 | Low | Redis can start without `requirepass` if the password file is empty (supervisord fallback) |
| 9 | Low | Branding SVG upload stores active content (mitigated by CSP) |
| 10 | Info | Pre-OOBE window grants unauthenticated admin-equivalent access |
| 11 | Info | Proxmox SSRF check allows unresolved hostnames; OAuth session code passed in URL |

---

## 1. Critical — Cross-tenant data access (broken multi-tenant isolation)

CircuitBreaker presents itself as multi-tenant: migration `0038` renamed *teams → tenants*, there
is a `tenant_members` table, a `TenantMiddleware`, and RLS policies in migration `0040`. In
practice, **tenant isolation is not enforced at any layer.**

**Layer 1 — Row-Level Security is disabled for the application role.**
`apps/backend/migrations/versions/0040_rls_policies.py` enables RLS and creates
`tenant_isolation_*` policies, but then does:

```python
op.execute(sa.text("ALTER ROLE breaker SET row_security = off"))
```

The `breaker` role is the role the application connects as. With `row_security = off`, Postgres
skips every RLS policy for that role. The policies exist but are never evaluated for real traffic.

**Layer 2 — Application queries do not filter by tenant.**
With RLS inert, isolation would have to come from `WHERE tenant_id = ...` in the ORM layer. It is
largely absent. Example (`apps/backend/src/app/services/hardware_service.py:127` and `:158`):

```python
def list_hardware(db, *, tag=None, role=None, q=None):
    stmt = select(Hardware)          # no tenant predicate
    ...

def get_hardware(db, hardware_id):
    hw = db.get(Hardware, hardware_id)   # primary-key fetch, no tenant check
```

The endpoints require only authentication/read scope, which every role (including `viewer` and
`demo`) holds — `apps/backend/src/app/api/hardware.py:18` (`dependencies=[require_scope("read", "*")]`).
The same pattern applies to writes: `delete_hardware` (`hardware.py:138`) calls
`hardware_service.delete_hardware(db, hardware_id)` with no tenant scoping behind `require_write_auth`.

Only three modules were found to reference tenant filtering at all (`api/tenants.py`,
`api/topologies.py`, `api/ipam.py`); the bulk of resource services (hardware, services, networks,
compute, storage, clusters, external nodes, scan jobs, integrations) do not.

**Impact:** Any authenticated user in tenant A can **read, and with editor/admin role delete or
mutate, any object in tenant B** by iterating integer IDs. This is a classic IDOR/horizontal
privilege escalation and defeats the entire tenant model.

**Recommendation (in priority order):**
1. Remove `ALTER ROLE breaker SET row_security = off` and instead grant the app role normal
   (non-BYPASSRLS) rights, so the policies actually apply. This requires fixing finding #2 first,
   or every query will error/return nothing.
2. Independently, add explicit `tenant_id == current_tenant_id.get()` predicates to all list and
   by-id service functions as defense-in-depth, and reject requests where tenant context is `None`.
3. Add a regression test that logs in as tenant A and asserts `404`/empty on tenant B's object IDs.

---

## 2. High — RLS session variable uses transaction-local scope at connection checkout

Even if #1 is fixed, the enforcement plumbing is broken.
`apps/backend/src/app/db/session.py:51` sets the tenant on the SQLAlchemy **checkout** event:

```python
@event.listens_for(engine, "checkout")
def _set_tenant_on_checkout(dbapi_conn, connection_record, connection_proxy):
    tid = current_tenant_id.get(None)
    cursor.execute("SELECT set_config('app.current_tenant', %s, true)", (str(tid),))  # is_local=True
```

Two problems:

- `set_config(..., is_local=True)` scopes the value to the **current transaction**. It is executed
  at pool checkout, outside/around request transactions; once the first request transaction commits,
  the value resets to empty for the rest of that checked-out connection's lifetime.
- When there is no tenant, it sets the variable to the empty string `''`. The policy casts
  `current_setting('app.current_tenant', true)::int`, and `''::int` raises
  `invalid input syntax for integer`. If RLS were actually on for the app role, unauthenticated /
  tenant-less queries would **error out** rather than return zero rows.

Today this is masked entirely by `row_security = off` (finding #1), which is why nothing errors —
further evidence the RLS layer is dead code.

**Recommendation:** Set the variable per-transaction (e.g. on the `after_begin` / session `begin`
event, or via `SET LOCAL` inside the request-scoped session), use `is_local=True` **within** the
transaction, and set it to a sentinel like `'0'`/`'-1'` (never empty) so the `::int` cast is always
valid and matches no rows. Add a test asserting cross-tenant queries return empty with RLS enabled.

---

## 3. Medium — MFA bypass via the forced-password-change branch

In `apps/backend/src/app/api/auth.py:285`, `login_compat` evaluates `force_password_change`
**before** the MFA challenge:

```python
if user and verify_password(password_or_hash, user.hashed_password) \
   and getattr(user, "force_password_change", False):
    reset_login_attempts(db, user)
    change_token = _jwt.encode({...,"aud":"cb:change-password",...}, cfg.jwt_secret, ...)
    return {"requires_change": True, "change_token": change_token}
# MFA check only runs if the above did not return
if user and getattr(user, "mfa_enabled", False):
    ...
```

`force_change_password` (`auth.py:341`) then redeems that `change_token`, resets the password, and
returns a full session (`_make_token` + cookie) **without ever requiring the TOTP/backup code**.

**Impact:** A user (or an attacker with the password) of an account that has *both*
`mfa_enabled=True` and `force_password_change=True` obtains a fully authenticated session while
skipping the second factor. The exposure is narrow (both flags must be set — e.g. an admin resets
an MFA user's password and forces a change) but it is a real second-factor bypass.

**Recommendation:** If `mfa_enabled`, require MFA *before* honoring the force-change flow (issue an
`mfa_token` first, complete the forced change only after `mfa/verify`), or have
`force_change_password` issue an `mfa_token` instead of a session when the user has MFA enabled.

---

## 4. Medium — Webhook SSRF via DNS rebinding (TOCTOU)

`apps/backend/src/app/workers/webhook_worker.py:166` validates the target and then posts to it:

```python
reject_ssrf_url(rule.target_url)     # resolves DNS, checks for private/loopback/link-local
...
resp = await client.post(rule.target_url, content=body_bytes, headers=headers, timeout=10.0)
```

`reject_ssrf_url` (`core/url_validation.py`) resolves the hostname and rejects private IPs at
validation time, but `httpx` performs a **fresh DNS resolution** at request time. An attacker who
controls DNS for their webhook host can return a public IP during validation and `127.0.0.1` /
`169.254.169.254` / an RFC1918 address during the actual POST — the standard DNS-rebinding SSRF
bypass. Because worker webhooks fire on internal events, this reaches internal-only services.

Mitigating factors: `httpx` does not follow redirects by default (so redirect-based bypass is
closed), and only an authenticated admin/editor can create webhook rules.

**Recommendation:** Resolve the host once, verify the resolved IP is public, and connect to that
pinned IP (passing the original `Host` header), or use an egress proxy / allowlist. Re-checking the
IP `httpx` actually connected to (via a custom transport) also closes the window.

---

## 5. Medium — Rate limiting is in-memory, per-worker, and keyed on the proxy address

`apps/backend/src/app/core/rate_limit.py:16`:

```python
limiter = Limiter(key_func=get_remote_address, headers_enabled=True)
```

- No `storage_uri` is configured, so slowapi uses **in-memory** storage. Limits are per-process:
  with multiple uvicorn workers the effective limit is `N ×` the configured value, and all counters
  reset on restart.
- `get_remote_address` keys on `request.client.host`. Behind the bundled nginx reverse proxy that
  is the proxy's address unless ASGI proxy-header handling is configured, so either every client
  shares one bucket (a single attacker can exhaust the `auth` limit for everyone → login DoS) or the
  limit is ineffective per-client. Either way the intended per-client protection is not what runs.

The real brute-force protection is the DB-backed account lockout, which is sound — but the network
rate limit is weaker than it appears.

**Recommendation:** Back slowapi with Redis (already available and authenticated in-container) via
`storage_uri`, and derive the client key from the validated `X-Forwarded-For` left-most hop (nginx
already sets it). Confirm uvicorn/Starlette proxy-header trust is scoped to the local proxy only.

---

## 6. Low — Lockout not enforced on the force-change / MFA-challenge login branches

In `login_compat` (`auth.py:285`, `:304`) the `force_password_change` and `requires_mfa` branches
call `verify_password` and return a challenge token, but neither checks `user.locked_until`. The
lockout check lives only in `auth_service.login` (`auth_service.py:886`), which those branches
return before reaching. A locked-out account can still be probed for a valid password (the response
differs between valid and invalid credentials on these paths) and, combined with #3, can complete
login while locked.

**Recommendation:** Evaluate `locked_until` at the top of `login_compat` before any branch, or route
all three branches through a shared pre-check.

---

## 7. Low — Public status page leaks internal monitor URLs; unauthenticated & unthrottled

`apps/backend/src/app/api/public_status.py:90` (`GET /status/{slug}`) is unauthenticated and returns
`PublicMonitor.url = m.url` for every monitor on a public page (`public_status.py:135`). Monitor
URLs are frequently internal hostnames/IPs (`http://10.0.0.5:8006`, etc.), disclosing internal
topology to anyone with the slug. The endpoint also has no `@limiter.limit`, and each call issues
several joined queries — a cheap anonymous DoS/enumeration vector.

**Recommendation:** Omit or redact `url` in the public schema (show only display name + status), and
add a rate limit to the public route.

---

## 8. Low — Redis may start without authentication if the password file is empty

`docker/supervisord.mono.conf:65` starts Redis with `--requirepass "$PASS"` **only** when
`/data/.redis_pass` is non-empty; otherwise it falls back to launching Redis with no password:

```sh
PASS=$(cat /data/.redis_pass 2>/dev/null || echo "");
if [ -n "$PASS" ]; then exec redis-server ... --requirepass "$PASS"; else exec redis-server ...; fi
```

`docker/entrypoint-mono.sh` does generate and `chmod 600` the file before supervisor starts, so the
happy path is safe. But an empty/truncated file (interrupted first boot, disk full, manual edit)
silently yields an unauthenticated Redis. Redis binds `127.0.0.1` with `protected-mode yes`, so the
blast radius is in-container, but the fail-open is undesirable.

**Recommendation:** Have supervisord treat a missing/empty password as fatal (exit) rather than
launching Redis unauthenticated, or generate the password in the supervisord command itself.

---

## 9. Low — Branding logo accepts SVG (active content); mitigated by CSP

`apps/backend/src/app/api/branding.py:31` allows `.svg` login logos and `verify_image_magic_bytes(..., allow_svg=True)`
skips binary validation for SVG (it is treated as trusted text). SVGs can embed `<script>`, and the
login logo is rendered on the unauthenticated login page. Direct navigation to the stored
`login-logo.svg` would render it as a document.

Mitigation: `SecurityHeadersMiddleware` and nginx attach `Content-Security-Policy: script-src 'self'`
to responses, which blocks inline script execution in the served SVG; branding upload is admin-only.
Impact is therefore low, but SVG remains an unnecessary active-content type.

**Recommendation:** Drop SVG from branding uploads, or sanitize on upload (e.g. strip scripts /
serve with `Content-Disposition: attachment` and `Content-Security-Policy: sandbox`).

---

## 10. Info — Pre-OOBE unauthenticated admin window

`resolve_optional_user_id_sync` (`core/security.py:342`) returns `0` (service-account/admin
sentinel) when `cfg.auth_enabled` is `False`, and RBAC materializes a synthetic admin for user 0
(`core/rbac.py:45`, `:131`). `auth_enabled` is a one-way OOBE marker (correctly excluded from
`AppSettingsUpdate`, so it cannot be flipped back), but **between container start and OOBE
completion the entire API is open at admin level**. If a deployment is reachable before the operator
finishes first-run setup, an attacker can complete OOBE themselves and seize the instance.

**Recommendation:** Document that the instance must not be network-exposed until OOBE completes, and
consider binding OOBE to a first-request token or localhost-only until bootstrap finishes.

---

## 11. Info — Smaller items

- **Proxmox SSRF allows unresolved hosts.** `reject_ssrf_url_proxmox` (`core/url_validation.py:52`)
  is called with `allow_unresolved_hostname=True`, returning success when DNS fails to resolve —
  intentionally permissive for LAN Proxmox, but it means a name that fails to resolve at check time
  is allowed through.
- **OAuth session code in URL.** `auth_oauth.py:483` redirects with `?cb_auth_code=<code>`; the code
  maps to a full session token. Codes in URLs can leak via `Referer` and browser history. It is
  short-lived and single-use (acceptable), but consider a POST/fragment exchange.
- **Session validation cache TTL (10s).** `core/security.py:33` caches token→uid for 10s, so a
  revoked session can remain valid for up to 10s. Documented and low-risk; noted for completeness.
- **`get_me` 401 detail leaks token presence.** `auth.py:632` returns different detail strings
  depending on whether a token was supplied — minor, aids enumeration only marginally.

---

## Verified-Good (previously-audited controls that still hold on `main`)

These were checked and remain correctly implemented — no action needed:

- Timing-safe comparisons via `hmac.compare_digest` for API/CSRF/legacy tokens
  (`core/security.py`, `middleware/csrf.py`, `middleware/legacy_token.py`).
- `auth_enabled` is a one-way OOBE marker, absent from `AppSettingsUpdate` — auth cannot be disabled
  post-bootstrap (`schemas/settings.py:359`).
- WebSocket handlers validate JWT (signature + `aud`) and reject when no `jwt_secret`; no anonymous
  sentinel (`ws_discovery.py`, `ws_telemetry.py`).
- URL scheme allowlist blocks `file://`/`gopher://`/etc. before IP checks (`core/url_validation.py:12`).
- Full security-header set present in both middleware and nginx; CSP `script-src` even dropped
  `'unsafe-inline'` (stronger than the documented baseline); `frame-ancestors 'none'`,
  `X-Frame-Options: DENY` intact.
- nginx: port-80 → 301 HTTPS redirect (health endpoint exempt), TLS on 8443.
- Docker: socket not mounted by default, `read_only: true` + tmpfs, `no-new-privileges`,
  `cap_drop: ALL` with a documented minimal `cap_add`, secrets use `${VAR:?}` fail-fast, JWT/vault
  key distinctness and length enforced in `entrypoint-mono.sh`.
- Password change revokes other sessions and writes a `password_changed` audit entry
  (`auth.py:814`).
- Constant-time login (`_DUMMY_HASH` path) prevents email enumeration; DB-backed account lockout
  works on the primary login path.

---

## Suggested remediation order

1. **Finding #1 + #2 together** — restore real tenant isolation (fix the RLS variable scope, drop
   `row_security = off`, add app-layer `tenant_id` predicates, add cross-tenant regression tests).
   This is the only Critical and should gate the next release.
2. **#3** MFA-before-force-change; **#4** pin webhook egress IP; **#5** Redis-backed rate limiting.
3. **#6–#9** hardening cleanups.
4. **#10–#11** documentation and minor tightening.
