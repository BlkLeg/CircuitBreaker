# Error Handling Patch — Summary of Changes

**Date:** 2026-03-11
**Scope:** 47 error handling gaps identified via full-stack audit
**Status:** All fixes applied (Batches 1-7)

---

## 1. File/DB Atomicity (C5, C6)

**Files:** `branding.py`, `compute_units.py`

All file-write-before-commit patterns now wrapped in try/except. If `db.commit()` fails after `dest.write_bytes(data)`, the orphaned file is deleted via `dest.unlink(missing_ok=True)` before re-raising. Applies to:
- `upload_favicon`, `upload_login_logo`, `upload_login_bg` (branding.py — 3 locations)
- Icon upload in compute_units.py (1 location)
- `delete_branding_asset` and `import_theme` have logging-only guards

## 2. Silent Exception Swallowing Eliminated (C1, H2, H6, L1)

**Files:** `proxmox_client.py`, `discovery.py`, `proxmox_service.py`, `logging_middleware.py`

| Location | Before | After |
|----------|--------|-------|
| proxmox_client.py (2 blocks) | `except Exception:` (bare) | `except Exception as exc:` + `_logger.warning(...)` |
| discovery.py `_compute_discovery_status` (2 blocks) | `except Exception: pass` | `_logger.debug(..., exc_info=True)` |
| discovery.py VLAN JSON parse | `except Exception: pass` | `_logger.warning("Malformed VLAN JSON: %s", ...)` |
| proxmox_service.py `_publish` | `except Exception: pass` | `_logger.debug("NATS publish failed", exc_info=True)` |
| logging_middleware.py (10 blocks) | `except Exception: pass` or no logging | `_logger.debug(..., exc_info=True)` on all; `exc_info=True` added to existing warning |

## 3. Auth Flow Hardening (C4, H1, H15)

**Files:** `AuthContext.jsx`, `auth_oauth.py`, `client.jsx`

- **`_upsert_oauth_user`** commit: catch Exception -> log + `HTTPException(502, "Authentication failed")`
- **`_ensure_provider_enabled`** commit: catch Exception -> `_logger.warning(...)` only (non-blocking)
- **AuthContext.jsx**: Settings fetch logs `console.error`; logout logs `console.warn`
- **client.jsx**: Logout catch logs `console.debug` (fire-and-forget by design)
- Auth paths **fail closed**: errors deny access, never silently grant it

## 4. User-Facing Error Feedback (C3, H10-H14)

**Files:** `BulkActionsDrawer.jsx`, `DiscoveryPage.jsx`, `SettingsPage.jsx`, `MapPage.jsx`, `useDiscoveryStream.js`, `useMapMutations.js`

- **BulkActionsDrawer**: Secondary loads (vendor catalog, networks, clusters) now log `console.error`
- **DiscoveryPage**: Host stats polling catch logs `console.error`
- **SettingsPage**: CVE sync catch logs `console.error`
- **MapPage**: Async layout fallback catch logs `console.error`
- **useMapMutations**: Edge unlink loop tracks failures with `edgeFailCount` + `toast.warn`

## 5. DB Commit Integrity — IntegrityError -> 409 (H8, H9, L6)

**Files:** `admin_users.py`, `topologies.py`, `networks.py`

| Endpoint | Error | Response |
|----------|-------|----------|
| `create_user` / `create_local_user` | `IntegrityError` | 409 "User with this email already exists" |
| `create_topology` | `IntegrityError` | 409 "Topology name already exists" |
| `create_network` | `IntegrityError` | 409 "Network with this name already exists" |
| `patch_network` | `IntegrityError` | 409 (duplicate name) |
| `add_peer` | `IntegrityError` | 409 (narrowed from bare `except Exception`) |
| `create_network` | `ValueError` | 400 (validation error) |

## 6. NATS Publish Guards (H4, H6)

**Files:** `hardware.py`, `proxmox_service.py`

Both NATS publish call sites wrapped in try/except -> `_logger.warning("NATS publish failed", exc_info=True)`. DB operations already succeeded; NATS failure does not fail the HTTP request.

## 7. Credential Vault Guard (H5)

**File:** `proxmox_service.py`

`vault.decrypt` failure caught -> raises `ValueError("Cannot decrypt credentials — vault key may have changed")` with descriptive context.

## 8. HTTP Client Guards (H7)

**File:** `ilo.py`

`_get` method wraps HTTP calls with try/except for `requests.ConnectionError` and `requests.HTTPError` -> raises `ConnectionError` with host context.

## 9. Subprocess Error Handling (M7, M8)

**Files:** `idrac.py`, `snmp_generic.py`

Exception clauses expanded to `(subprocess.TimeoutExpired, FileNotFoundError, OSError)` — covers missing binaries and OS-level failures.

## 10. Service-Layer Abstraction (M2)

**File:** `environments_service.py`

Replaced `raise HTTPException(409, ...)` with `raise ConflictError("Environment already exists")` from `app.core.errors`. Services no longer depend on FastAPI HTTP types.

## 11. Async Task Safety (H3)

**File:** `discovery.py`

`asyncio.create_task(run_scan_job(...))` wrapped in try/except -> `_logger.exception(...)` + `HTTPException(500, "Failed to start scan.")`. Applied to both scan endpoints.

## 12. ErrorBoundary Coverage (M20)

**File:** `App.jsx`

Verified: ErrorBoundary already wraps all route-level lazy components at three points: `AppInner`, unauthenticated routes, and authenticated routes. No gaps found.

## 13. Frontend Bulk Silent-Catch Cleanup (M9-M19, L3-L5)

16 files audited. Silent `.catch(() => {})` and bare `} catch {` blocks replaced with contextual logging:

| File | Fixes |
|------|-------|
| LoginPage.jsx | OAuth callback: `console.error` |
| ComputeUnitsPage.jsx | Tags load: `console.error` |
| WebhooksManager.jsx | 4 catches: event toggle, list load, delete, toggle |
| OOBEWizardPage.jsx | 5 catches: state restore, geocoding, OAuth save, photo upload, clipboard |
| LogsPage.jsx | 2 catches: actions load, actors load |
| DiscoveryPage.jsx | Host stats polling |
| SettingsPage.jsx | CVE sync trigger |
| MapPage.jsx | Async layout fallback |

Files already compliant (no changes needed): useDiscoveryStream.js, useMapMutations.js, client.jsx, useMapRealTimeUpdates.js, useMapDataLoad.js, ReviewQueuePanel.jsx, ScanProfilesPanel.jsx.

---

## Security Review

### OWASP Top 10 — Error Handling / Information Leakage

- **No stack traces leak to clients.** All new error responses use generic messages ("Authentication failed", "User with this email already exists"). The `exc_info=True` parameter is server-side logging only.
- **Global exception handlers** remain the last line of defense. Per-endpoint catches provide specific messages; anything uncaught still returns a generic 500 via FastAPI's global handler.

### CWE-754 — Improper Check for Unusual Conditions

- **Addressed:** 10 bare `except: pass` blocks in logging_middleware.py now log with `exc_info=True`. Subprocess calls in idrac.py and snmp_generic.py now catch `OSError`. VLAN JSON parse failures are logged.

### CWE-755 — Improper Handling of Exceptional Conditions

- **Addressed:** File orphan cleanup on commit failure (branding, compute_units). Vault decrypt failure raises descriptive ValueError. NATS publish failures are isolated from HTTP responses. `asyncio.create_task` failures return 500 instead of silently dropping.

### CWE-209 — Error Message Information Exposure

- **Verified safe.** No endpoint returns `str(exc)` for internal exceptions. IntegrityError responses use hardcoded messages, not database error strings. Auth failures return "Authentication failed" without details about which step failed.

### Defense-in-Depth

- **Global handlers intact.** `get_db()` still rolls back on any exception. FastAPI's global exception handler still catches anything not handled per-endpoint. The new per-endpoint handlers are additive, not replacements.

### Fail-Closed vs Fail-Open

- **Auth paths fail closed.** `_upsert_oauth_user` raises 502 on commit failure (denies login). `_ensure_provider_enabled` logs warning but does not block existing provider checks. Frontend AuthContext clears state on any auth error. Logout failure does not leave stale sessions — server-side expiry handles cleanup.
