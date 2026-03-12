# Discovery Test Async/Sync Mismatch Report

## Summary

The error `AttributeError: 'coroutine' object has no attribute 'id'` occurs when `create_scan_job` is **async** but callers (tests and helpers) treat it as sync and do not `await` it. The returned coroutine object is then passed to `_make_result()`, which accesses `job.id` at line 66 and fails.

---

## 1. Function Signature of `create_scan_job`

**Current state (in `apps/backend/src/app/services/discovery_service.py`):**

```python
def create_scan_job(
    db: Session,
    target_cidr: str | None = None,
    scan_types: list[str] | None = None,
    vlan_ids: list[int] | None = None,
    profile_id: int | None = None,
    label: str | None = None,
    nmap_arguments: str | None = None,
    triggered_by: str = "api",
) -> ScanJob:
```

**Conclusion:** In the current codebase, `create_scan_job` is **synchronous** (no `async` keyword). If it were changed to `async def create_scan_job(...)`, it would return a coroutine and all sync callers would receive a coroutine instead of a `ScanJob`.

---

## 2. Test Helper Code at Line ~66

**File:** `tests/integration/test_discovery.py`

**Helper `_make_job` (lines 58–59):**

```python
def _make_job(db, cidr=CIDR_DEFAULT, scan_types=None) -> ScanJob:
    return create_scan_job(db, cidr, scan_types or ["nmap"])
```

**Helper `_make_result` (lines 61–79) — error at line 66:**

```python
def _make_result(db, job, *, ip=IP_RESULT_DEFAULT, mac=None,
                 state="new", merge_status="pending",
                 open_ports_json=None, matched_entity_id=None,
                 matched_entity_type=None) -> ScanResult:
    r = ScanResult(
        scan_job_id=job.id,   # <-- LINE 66: fails if job is a coroutine
        ip_address=ip,
        mac_address=mac,
        ...
    )
```

If `create_scan_job` is async, `_make_job` returns a coroutine. Any test that does `job = _make_job(db)` and then passes `job` to `_make_result(db, job, ...)` will fail when `_make_result` accesses `job.id`.

---

## 3. Affected Tests

All tests that use `_make_job` or call `create_scan_job` directly are affected:

| Test | Line | How it uses create_scan_job |
|------|------|-----------------------------|
| `test_create_scan_job_valid` | 116 | `job = _make_job(db, CIDR_LAN)` |
| `test_create_scan_job_stores_normalised_cidr` | 122 | `job = create_scan_job(db, CIDR_HOST_BITS, ["nmap"])` |
| `test_create_scan_job_invalid_cidr_raises` | 128 | `create_scan_job(db, "bad-input", ["nmap"])` |
| `test_upsert_result_new_host` | 135 | `job = _make_job(db)` |
| `test_upsert_result_matched_host` | 142 | `job = _make_job(db)` |
| `test_upsert_result_conflict` | 150 | `job = _make_job(db)` |
| `test_auto_merge_disabled_by_default` | 163 | `job = _make_job(db)` |
| `test_auto_merge_creates_hardware` | 174 | `job = _make_job(db)` |
| `test_merge_accept_new_creates_hardware` | 187 | `job = _make_job(db)` |
| `test_merge_accept_returns_ports` | 203 | `job = _make_job(db)` |
| `test_merge_accept_unknown_port_is_misc` | 215 | `job = _make_job(db)` |
| `test_merge_reject` | 222 | `job = _make_job(db)` |
| `test_merge_already_accepted_returns_409` | 232 | `job = _make_job(db)` |
| `test_merge_conflict_with_overrides` | 241 | `job = _make_job(db)` |
| `test_bulk_merge_skips_conflicts` | 256 | `job = _make_job(db)` |
| `test_bulk_merge_reject_all` | 269 | `job = _make_job(db)` |
| `test_emit_result_processed_event_accept` | 326 | `job = _make_job(db)` |
| `test_emit_result_processed_event_reject` | 345 | `job = _make_job(db)` |
| `test_emit_result_processed_event_exception_handling` | 366 | `job = _make_job(db)` |

---

## 4. Other Discovery Service Functions Used by Tests

| Function | Sync/Async | Used by tests |
|----------|------------|---------------|
| `create_scan_job` | **Sync** | Yes — many tests |
| `merge_scan_result` | Sync | Yes |
| `bulk_merge_results` | Sync | Yes |
| `purge_old_scan_results` | Sync | Yes |
| `_validate_cidr` | Sync | Yes |
| `_arp_available` | Sync | Yes |
| `_emit_result_processed_event` | **Async** | Yes — async tests only, and they `await` it |

No other discovery service functions called by the tests have async/sync mismatches. The only problematic one is `create_scan_job` if it is made async.

---

## 5. Recommended Fix

**Option A: Keep `create_scan_job` synchronous (recommended)**

`create_scan_job` only does DB work (queries, inserts, commits). It does not perform I/O that benefits from async. Keeping it sync is the simplest and most consistent with the rest of the discovery service API used by tests.

**Option B: If `create_scan_job` must be async — make tests async and await**

1. Convert `_make_job` to async and await `create_scan_job`:

```python
async def _make_job(db, cidr=CIDR_DEFAULT, scan_types=None) -> ScanJob:
    return await create_scan_job(db, cidr, scan_types or ["nmap"])
```

2. Convert all affected tests to async and use `await _make_job(db)`:

```python
@pytest.mark.asyncio
async def test_create_scan_job_valid(db):
    job = await _make_job(db, CIDR_LAN)
    assert job.id is not None
    ...
```

3. For tests that call `create_scan_job` directly, await it:

```python
@pytest.mark.asyncio
async def test_create_scan_job_stores_normalised_cidr(db):
    job = await create_scan_job(db, CIDR_HOST_BITS, ["nmap"])
    assert job.target_cidr == CIDR_DEFAULT
```

4. Ensure `conftest.py` provides a `db` fixture compatible with async tests (the current `db` fixture is sync; async tests can still use it if they only await async service calls and do not use async DB drivers).

**Option C: Sync wrapper (not recommended)**

Add a sync wrapper that runs the async function in an event loop. This adds complexity and can cause issues with existing event loops (e.g. in FastAPI/TestClient). Prefer Option A or B.

---

## 6. Code Snippets for Option B (if async is required)

**Helper change:**

```python
# tests/integration/test_discovery.py

async def _make_job(db, cidr=CIDR_DEFAULT, scan_types=None) -> ScanJob:
    return await create_scan_job(db, cidr, scan_types or ["nmap"])
```

**Example test conversions (sync → async):**

```python
@pytest.mark.asyncio
async def test_create_scan_job_valid(db):
    job = await _make_job(db, CIDR_LAN)
    assert job.id is not None
    assert job.status == "queued"
    assert job.target_cidr == CIDR_LAN

@pytest.mark.asyncio
async def test_upsert_result_new_host(db):
    job = await _make_job(db)
    r = _make_result(db, job, ip=IP_RESULT_NEW)
    assert r.state == "new"
    assert r.merge_status == "pending"
```

**Note:** The async tests at the end (`test_emit_result_processed_event_*`) already use `@pytest.mark.asyncio` and `_make_job(db)`. They would need to be updated to `await _make_job(db)`.

---

## 7. Callers Outside Tests

If `create_scan_job` is made async, these callers must also be updated:

| Location | Usage |
|----------|-------|
| `apps/backend/src/app/api/discovery.py` | Lines 199, 233 — `job = discovery_service.create_scan_job(...)` in async endpoints; would need `await` |
| `apps/backend/src/app/services/discovery_service.py` | Line 1485 — `job = create_scan_job(...)` inside `_run_profile_job_async`; already async, would need `await` |
| `apps/backend/src/app/services/prober_service.py` | Line 39 — `job = create_scan_job(...)`; sync context, would need `asyncio.run()` or similar |

---

## Conclusion

- **Current state:** `create_scan_job` is sync; tests should pass.
- **If `create_scan_job` is made async:** Either keep it sync (recommended) or update all callers (tests, API, prober, profile job) to await it and convert sync tests to async where needed.
