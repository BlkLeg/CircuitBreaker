# CircuitBreaker — Silent errors, logic bugs, and implementation gaps

**Date:** 2026-04-06  
**Scope:** Read-only review of backend (`apps/backend`), frontend (`apps/frontend`), and tests.  
**Method:** Static analysis (pattern search, targeted file reads). No runtime profiling or full test suite execution.

---

## Executive summary

The codebase generally follows explicit logging for many failure paths, but there are recurring patterns of **broad `except Exception` with `pass` or minimal handling**, **frontend promise chains that swallow errors**, and a few **data-shape / transport behaviors** that can hide problems from operators and users. Multi-tenant UX sends an **`X-Tenant-ID` header that the backend tenant middleware does not read**; combined with JWT claims and DB RLS configuration, tenant isolation behavior deserves explicit verification in each deployment.

---

## Critical / high priority

### 1. Frontend `X-Tenant-ID` is not consumed by tenant middleware

The Axios client attaches `X-Tenant-ID` from `localStorage` on mutating and read requests:

```92:96:apps/frontend/src/api/client.jsx
  const activeTenantId = localStorage.getItem('cb_active_tenant_id');
  if (activeTenantId) {
    config.headers['X-Tenant-ID'] = activeTenantId;
  }
```

`TenantMiddleware` only derives `tenant_id` from the Bearer JWT payload (`tenant_id` claim) or, if unset, `request.state.user.tenant_id`. It does **not** read `X-Tenant-ID`:

```31:51:apps/backend/src/app/middleware/tenant_middleware.py
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                ...
                payload = decode_access_token(raw_token, secret=secret)
                tenant_id = payload.get("tenant_id")
            except Exception:  # noqa: BLE001
                pass

        if tenant_id is None:
            user = getattr(request.state, "user", None)
            if user is not None:
                tenant_id = getattr(user, "tenant_id", None)
```

**Gap:** Documentation and UI imply the header drives active-tenant context, but RLS session variable wiring (`app.current_tenant` on connection checkout) follows the ContextVar set here, not the header. If JWTs do not carry `tenant_id` and `request.state.user` is not populated when this middleware runs, `tenant_id` may be `None` regardless of the header.

**RLS note:** Migration `0040_rls_policies.py` attempts `ALTER ROLE breaker SET row_security = off`. If that succeeds, the application DB role may **bypass RLS** entirely, masking tenant bugs until a stricter role is used.

**Recommendation:** Either document that only JWT/`User.tenant_id` matter and remove or repurpose the header, or validate `X-Tenant-ID` against membership and set tenant context authoritatively (and ensure middleware order aligns with auth).

---

### 2. SSE DB fallback: failed seed can replay log history

In `_db_poll_generator`, if `_seed()` fails, the `except` block is empty and `last_log_id` stays `0`:

```93:98:apps/backend/src/app/api/events.py
        try:
            max_id = await loop.run_in_executor(None, _seed)
            if max_id:
                last_log_id = max_id
        except Exception:
            pass
```

On the next poll, `Log.id > 0` can return a large batch of historical rows, causing **duplicate notifications**, **heavy DB load**, and misleading UI activity. Failures are silent at default log levels.

**Recommendation:** Log at `warning`/`error`, set `last_log_id` from a safe default or disable polling until seed succeeds.

---

### 3. Audit / log pipeline: failures easy to miss

`write_log` catches all exceptions and prints to stderr (not the app logger); inner branches also swallow errors:

```227:229:apps/backend/src/app/services/log_service.py
    except Exception as exc:  # noqa: BLE001
        print(f"[audit] write_log failed (action={action!r}): {exc}", file=sys.stderr)
```

Redis publish for audit stream fails silently:

```261:267:apps/backend/src/app/services/log_service.py
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_pub())
        except RuntimeError:
            pass
    except Exception:
        pass
```

**Risk:** Audit loss without structured logs or metrics; operators relying on log aggregation may miss `stderr` in some deployments.

**Recommendation:** Use module `logger.exception` / `logger.warning`, and consider a metric or counter for audit write failures.

---

## Medium priority

### 4. Silent drops of domain data

**Discovery scan results:** Validated results are appended inside `try/except` with bare `pass` on failure — individual bad rows disappear from the API response with no counter or log:

```619:623:apps/backend/src/app/services/discovery_service.py
            try:
                results_out.append(ScanResultOut.model_validate(_scan_res).model_dump())
            except Exception:
                pass
```

**Graph layout save:** Invalid `layout_data` JSON becomes `{}` without surfacing validation error to the client:

```1172:1175:apps/backend/src/app/api/graph.py
        try:
            parsed_layout: dict = json.loads(data.layout_data)
        except (json.JSONDecodeError, TypeError):
            parsed_layout = {}
```

**Settings / theme:** Invalid `custom_colors` JSON is swallowed in `build_theme_colors`; `parse_map_default_filters` returns `None` on parse failure (`schemas/settings.py`), which may confuse callers expecting a dict.

**Recommendation:** Log at least at debug with entity id; for user-facing writes, return `422` when JSON is malformed.

---

### 5. Tenant middleware: silent failure on decode / settings load

Any failure while opening DB, loading settings, or decoding the token is swallowed:

```33:46:apps/backend/src/app/middleware/tenant_middleware.py
            try:
                ...
                payload = decode_access_token(raw_token, secret=secret)
                tenant_id = payload.get("tenant_id")
            except Exception:  # noqa: BLE001
                pass
```

Transient DB errors are indistinguishable from invalid tokens without logging.

**Recommendation:** Log `warning` with exception type (no token payload), or narrow exception types.

---

### 6. `_get_jwt_secret()` swallows DB errors

```180:194:apps/backend/src/app/core/users.py
def _get_jwt_secret() -> str:
    """Read jwt_secret from AppSettings at call time, with fallback."""
    try:
        ...
    except Exception:
        pass

    env_secret = os.environ.get(CB_JWT_SECRET_ENV)
```

If the DB is temporarily unavailable, the code silently falls through to env or empty string, which can cause confusing auth failures elsewhere.

**Recommendation:** Log once per failure path at `warning`.

---

### 7. NATS SSE: malformed messages become empty objects

```157:161:apps/backend/src/app/api/events.py
        async def _nats_cb(msg: Any) -> None:
            try:
                data = json.loads(msg.data.decode())
            except Exception:
                data = {}
```

Downstream clients receive empty payloads with no indication of parse failure.

**Recommendation:** Log debug + optional `event: error` or drop with metric.

---

### 8. Queue backpressure silently drops events

```176:179:apps/backend/src/app/api/events.py
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                pass  # Drop if backpressure — client too slow
```

This is a deliberate tradeoff but **silent** from the client’s perspective.

**Recommendation:** Document; optionally increment a metric or log at throttled `warning`.

---

## Lower priority / frontend

### 9. Empty `.catch(() => {})` handlers

These suppress network/parse errors and leave UI in an inconsistent state without user feedback:

| Location | Issue |
|----------|--------|
| `apps/frontend/src/components/common/IconPickerModal.jsx` (~1043) | Silent failure |
| `apps/frontend/src/components/common/SecurityBanner.jsx` (~34) | Silent failure |
| `apps/frontend/src/pages/InviteAcceptPage.jsx` (~35) | Silent failure |
| `apps/frontend/src/pages/DocsPage.jsx` (~963) | Silent failure |
| `apps/frontend/src/components/ipam/IPAddressesTab.jsx` (~52) | Silent failure |
| `apps/frontend/src/pages/ServicesPage.jsx` (~202, ~206) | Silent failure |

**Recommendation:** At minimum `logger.error` or user-visible toast; keep error in Sentry if used.

---

### 10. WebSocket / telemetry tests document known issues

`apps/frontend/src/__tests__/ws-reconnect.test.js` comments reference incorrect `ws.close()` usage and zombie sockets — worth tracking as technical debt.

---

## Test and CI gaps

### 11. Placeholder / skipped stress test

```17:19:apps/backend/tests/stress/test_event_loop.py
async def test_ws_concurrency(live_server, tabs):
    # Open N WS connections, assert responsive after 60s load
    pass
```

The test provides **no coverage** for the stated goal.

### 12. Integration test skipped

`tests/integration/test_phase3_realtime.py` is marked `@pytest.mark.skip` (unreachable port / slow). Realtime paths may lack automated regression coverage.

### 13. Frontend unit test debt

`tests/unit/SettingsPage.test.jsx` notes skipped tests due to import-tree / open-handle issues.

---

## Patterns that are mostly acceptable but worth consistency review

- **WebSocket cleanup:** `except Exception: pass` around `close()` and task joins in `ws_telemetry.py` / `ws_status.py` is common to avoid secondary failures; low risk if primary errors are logged earlier.
- **Graph CTE preload:** `graph.py` logs debug and falls back to per-table queries on CTE failure — acceptable degradation.
- **ETag helper:** Catching exceptions and substituting `none` for missing aggregates is intentional for resilience; could hide schema issues if not monitored.

---

## Positive observations

- **Axios client** centralizes retries, 429 handling, and user-facing error messages (`apps/frontend/src/api/client.jsx`).
- **Logging middleware** generally uses `_logger.debug(..., exc_info=True)` on parse failures rather than bare `pass`.
- **SSE** documents NATS vs DB fallback; degraded modes are intentional.
- **Security-sensitive JWT path** documents unverified decode restrictions (`decode_access_token` in `core/security.py`).

---

## Suggested next steps (for a follow-up change set)

1. Align multi-tenant contract: header vs JWT vs `User.tenant_id` vs RLS role behavior; add integration tests for tenant switch + data visibility.  
2. Harden SSE DB fallback seed path and NATS parse path with logging/metrics.  
3. Replace `print` in `write_log` with structured logging; narrow `except Exception` where feasible.  
4. Remove or implement `test_ws_concurrency` and reduce empty frontend catches.  

---

*This report is static analysis only; it does not assert exploitability or production configuration. Validate findings against your deployment (DB role, JWT claims, log sinks).*
