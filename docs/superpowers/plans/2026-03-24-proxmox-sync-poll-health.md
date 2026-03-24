# Proxmox Sync & Poll Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Proxmox scheduled sync and telemetry poll observable — persist outcomes to the DB and surface sync errors (amber) and poll errors (indigo) in the Proxmox UI tab.

**Architecture:** Two new DB columns (`last_sync_error`, `last_poll_error`) on `integration_configs` are written by two new sync helpers (`_record_sync_health`, `_record_poll_health`) in `main.py`. The three telemetry service functions change their return type from `None` to `dict[int, Exception | None]` so the wrappers can call `_record_poll_health`. The API status endpoint and Pydantic schema expose both fields; the UI renders them as distinct colour-coded blocks.

**Tech Stack:** Python 3.12, SQLAlchemy mapped columns, Alembic migrations, FastAPI, React + inline styles

---

## File Map

| File | Change |
|---|---|
| `apps/backend/migrations/versions/0063_proxmox_sync_health.py` | **Create** — adds `last_sync_error` + `last_poll_error` columns |
| `apps/backend/src/app/db/models.py` | **Modify** — two new fields on `IntegrationConfig` (line 1042) |
| `apps/backend/src/app/main.py` | **Modify** — module-level `IntegrationConfig` import, `_record_sync_health()`, `_record_poll_health()`, wire into `_proxmox_full_sync()` + three poll wrappers |
| `apps/backend/src/app/services/proxmox_telemetry.py` | **Modify** — return type + `poll_outcomes` dict in all three poll functions |
| `apps/backend/src/app/services/proxmox_queries.py` | **Modify** — `get_sync_status()` return dict gains two new keys (lines 90-99) |
| `apps/backend/src/app/schemas/proxmox.py` | **Modify** — `ProxmoxSyncStatus` schema gains two new optional fields (line 127) |
| `apps/frontend/src/components/proxmox/ProxmoxIntegrationSection.jsx` | **Modify** — `STATUS_BADGE_MAP` partial entry, `relativeTime()` helper, sync + poll error blocks |

---

### Task 1: Migration — add `last_sync_error` and `last_poll_error`

**Files:**
- Create: `apps/backend/migrations/versions/0063_proxmox_sync_health.py`

- [ ] **Step 1: Create the migration file**

```python
"""Add last_sync_error and last_poll_error to integration_configs."""

import sqlalchemy as sa
from alembic import op

revision = "0063_proxmox_sync_health"
down_revision = "0062_native_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_configs",
        sa.Column("last_sync_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "integration_configs",
        sa.Column("last_poll_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integration_configs", "last_poll_error")
    op.drop_column("integration_configs", "last_sync_error")
```

- [ ] **Step 2: Run migration to verify it applies cleanly**

```bash
cd apps/backend && make migrate
```
Expected: `Running upgrade 0062_native_monitoring -> 0063_proxmox_sync_health`

---

### Task 2: Model — add fields to `IntegrationConfig`

**Files:**
- Modify: `apps/backend/src/app/db/models.py:1042`

- [ ] **Step 1: Add two new mapped columns after `last_sync_status` (line 1042)**

Current:
```python
    last_sync_status: Mapped[str | None] = mapped_column(String, nullable=True)
    extra_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

New:
```python
    last_sync_status: Mapped[str | None] = mapped_column(String, nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_poll_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

`Text` is already imported in `models.py` (used elsewhere). No new imports needed.

- [ ] **Step 2: Verify ruff passes**

```bash
cd apps/backend && ruff check src/app/db/models.py
```
Expected: no output (clean)

---

### Task 3: Sync health helper — `_record_sync_health()` in `main.py`

**Files:**
- Modify: `apps/backend/src/app/main.py`

- [ ] **Step 1: Add module-level `IntegrationConfig` import**

`IntegrationConfig` is currently imported only inside `lifespan()` (inside a `with get_session_context()` block). Add it at module level alongside the other `app.db` imports at the top of the file:

```python
from app.db.models import IntegrationConfig
```

- [ ] **Step 2: Add `_record_sync_health()` as a module-level function**

Add this function near the top of the module (before `lifespan()`), after the imports block:

```python
def _record_sync_health(
    config_id: int,
    result: dict | None = None,
    exc: Exception | None = None,
) -> None:
    """Persist sync outcome to IntegrationConfig. Opens its own session — safe after rollbacks."""
    try:
        with get_session_context() as _hdb:
            cfg = _hdb.get(IntegrationConfig, config_id)
            if not cfg:
                return
            if exc is not None:
                cfg.last_sync_status = "error"
                cfg.last_sync_error = str(exc)[:512]
            elif result is not None:
                errors = result.get("errors") or []
                if not result.get("ok", True):
                    # discover_and_import caught a hard failure internally (e.g. ValueError),
                    # already wrote "error" to the DB and returned ok=False — preserve "error".
                    cfg.last_sync_status = "error"
                    cfg.last_sync_error = (
                        "\n".join(str(e) for e in errors[:5]) if errors else "Sync failed"
                    )
                else:
                    cfg.last_sync_status = "partial" if errors else "ok"
                    cfg.last_sync_error = (
                        "\n".join(str(e) for e in errors[:5]) if errors else None
                    )
            cfg.last_sync_at = utcnow()
            _hdb.commit()
    except Exception:
        _logger.exception("Failed to record sync health for config %s", config_id)
```

`get_session_context` and `utcnow` are already imported at module level. `IntegrationConfig` is now available from Step 1.

- [ ] **Step 3: Verify ruff passes**

```bash
cd apps/backend && ruff check src/app/main.py
```
Expected: no output (clean)

---

### Task 4: Poll health helper — `_record_poll_health()` in `main.py`

**Files:**
- Modify: `apps/backend/src/app/main.py`

- [ ] **Step 1: Add `_record_poll_health()` as a module-level function alongside `_record_sync_health()`**

```python
def _record_poll_health(poll_outcomes: dict[int, Exception | None]) -> None:
    """Write last_poll_error to IntegrationConfig for each config in poll_outcomes."""
    for config_id, exc in poll_outcomes.items():
        try:
            with get_session_context() as _hdb:
                cfg = _hdb.get(IntegrationConfig, config_id)
                if not cfg:
                    continue
                cfg.last_poll_error = str(exc)[:512] if exc is not None else None
                _hdb.commit()
        except Exception:
            _logger.exception("Failed to record poll health for config %s", config_id)
```

- [ ] **Step 2: Verify ruff passes**

```bash
cd apps/backend && ruff check src/app/main.py
```
Expected: no output (clean)

---

### Task 5: Wire `_record_sync_health()` into `_proxmox_full_sync()`

**Files:**
- Modify: `apps/backend/src/app/main.py:815-827`

- [ ] **Step 1: Update the inner loop to capture result and call `_record_sync_health()`**

Current (lines 815-827):
```python
    async def _proxmox_full_sync():
        try:
            async with asyncio.timeout(270):
                with get_session_context() as _pdb:
                    configs = list_integrations(_pdb)
                    for cfg in configs:
                        if cfg.auto_sync:
                            try:
                                await discover_and_import(_pdb, cfg, queue_for_review=False)
                            except Exception as exc:
                                _logger.warning("Proxmox full sync failed for %d: %s", cfg.id, exc)
        except TimeoutError:
            _logger.warning("proxmox_full_sync timed out (270s) — skipping cycle")
```

New:
```python
    async def _proxmox_full_sync():
        try:
            async with asyncio.timeout(270):
                with get_session_context() as _pdb:
                    configs = list_integrations(_pdb)
                    for cfg in configs:
                        if cfg.auto_sync:
                            try:
                                result = await discover_and_import(_pdb, cfg, queue_for_review=False)
                                _record_sync_health(cfg.id, result=result)
                            except Exception as exc:
                                _logger.warning("Proxmox full sync failed for %d: %s", cfg.id, exc)
                                _record_sync_health(cfg.id, exc=exc)
        except TimeoutError:
            _logger.warning("proxmox_full_sync timed out (270s) — skipping cycle")
```

- [ ] **Step 2: Verify ruff passes**

```bash
cd apps/backend && ruff check src/app/main.py
```
Expected: no output (clean)

---

### Task 6: Service return types — `proxmox_telemetry.py`

**Files:**
- Modify: `apps/backend/src/app/services/proxmox_telemetry.py:100,252,372`

Three functions need return type changes and a `poll_outcomes` dict. Note: `poll_node_telemetry` has a circuit breaker; the other two do not. Apply the correct pattern for each.

**Important naming:** `poll_node_telemetry` already uses a local variable named `results` (line 143, for `asyncio.gather`). Use `poll_outcomes` for the new per-config dict to avoid shadowing.

- [ ] **Step 1: Update `poll_node_telemetry` (lines 100-249)**

Change the signature:
```python
async def poll_node_telemetry(db: AsyncSession) -> dict[int, Exception | None]:
```

After the `configs` query (line 113), add:
```python
    poll_outcomes: dict[int, Exception | None] = {}
```

Inside the `for config in configs:` loop, the existing structure is:
```
if breaker.is_open(): continue          # line 120-124
try:
    ... poll logic ...
    await db.commit()
    breaker.record_success()            # line 246
except Exception as e:
    breaker.record_failure()            # line 248
    _logger.warning(...)                # line 249
```

Add `poll_outcomes[config_id] = None` **after** `breaker.record_success()` (on success), and `poll_outcomes[config_id] = e` **after** `breaker.record_failure()` (on failure). Do NOT set `poll_outcomes[config_id]` before the `breaker.is_open()` check — breaker-skipped configs are intentionally absent so their stale error persists until real recovery.

At the end of the function, add:
```python
    return poll_outcomes
```

- [ ] **Step 2: Update `poll_rrd_telemetry` (lines 252-369)**

Change the signature:
```python
async def poll_rrd_telemetry(db: AsyncSession) -> dict[int, Exception | None]:
```

After the `configs` query (line 266), add:
```python
    poll_outcomes: dict[int, Exception | None] = {}
```

Inside `for config in configs:`, the existing structure is:
```
try:
    ... poll logic ...
    await db.commit()           # line 366
except Exception as e:
    _logger.warning(...)        # line 368
    await db.rollback()         # line 369
```

Add `poll_outcomes[config.id] = None` after `await db.commit()`, and `poll_outcomes[config.id] = e` after `_logger.warning(...)` (before `await db.rollback()`).

At the end of the function, add:
```python
    return poll_outcomes
```

- [ ] **Step 3: Update `poll_vm_telemetry` (lines 372-506)**

Change the signature:
```python
async def poll_vm_telemetry(db: AsyncSession) -> dict[int, Exception | None]:
```

After the `configs` query (line 385), add:
```python
    poll_outcomes: dict[int, Exception | None] = {}
```

Inside `for config in configs:`, the existing structure is:
```
try:
    ... poll logic ...
    await db.commit()           # line 504
except Exception as e:
    _logger.warning(...)        # line 506
```

Add `poll_outcomes[config_id] = None` after `await db.commit()`, and `poll_outcomes[config_id] = e` after `_logger.warning(...)`.

At the end of the function, add:
```python
    return poll_outcomes
```

- [ ] **Step 4: Verify ruff passes**

```bash
cd apps/backend && ruff check src/app/services/proxmox_telemetry.py
```
Expected: no output (clean)

---

### Task 7: Wire `_record_poll_health()` into poll wrappers (`main.py`)

**Files:**
- Modify: `apps/backend/src/app/main.py:799-813,865-871`

Note structural difference: `_proxmox_node_poll` and `_proxmox_vm_poll` are defined **before** `if has_proxmox:` (lines 799-813). `_proxmox_rrd_poll` is defined **inside** `if has_proxmox:` (line 865). Update each in-place at its existing scope.

- [ ] **Step 1: Update `_proxmox_node_poll` (line 799)**

Current:
```python
    async def _proxmox_node_poll():
        try:
            async with asyncio.timeout(25):
                async with AsyncSessionLocal() as _pdb:
                    await poll_node_telemetry(_pdb)
        except TimeoutError:
            _logger.warning("proxmox_node_poll timed out (25s) — skipping cycle")
```

New:
```python
    async def _proxmox_node_poll():
        try:
            async with asyncio.timeout(25):
                async with AsyncSessionLocal() as _pdb:
                    poll_outcomes = await poll_node_telemetry(_pdb)
                    _record_poll_health(poll_outcomes)
        except TimeoutError:
            _logger.warning("proxmox_node_poll timed out (25s) — skipping cycle")
```

- [ ] **Step 2: Update `_proxmox_vm_poll` (line 807)**

Current:
```python
    async def _proxmox_vm_poll():
        try:
            async with asyncio.timeout(100):
                async with AsyncSessionLocal() as _pdb:
                    await poll_vm_telemetry(_pdb)
        except TimeoutError:
            _logger.warning("proxmox_vm_poll timed out (100s) — skipping cycle")
```

New:
```python
    async def _proxmox_vm_poll():
        try:
            async with asyncio.timeout(100):
                async with AsyncSessionLocal() as _pdb:
                    poll_outcomes = await poll_vm_telemetry(_pdb)
                    _record_poll_health(poll_outcomes)
        except TimeoutError:
            _logger.warning("proxmox_vm_poll timed out (100s) — skipping cycle")
```

- [ ] **Step 3: Update `_proxmox_rrd_poll` (line 865, inside `if has_proxmox:`)**

Current:
```python
            async def _proxmox_rrd_poll():
                try:
                    async with asyncio.timeout(270):
                        async with AsyncSessionLocal() as _pdb:
                            await poll_rrd_telemetry(_pdb)
                except TimeoutError:
                    _logger.warning("proxmox_rrd_poll timed out (270s) — skipping cycle")
```

New:
```python
            async def _proxmox_rrd_poll():
                try:
                    async with asyncio.timeout(270):
                        async with AsyncSessionLocal() as _pdb:
                            poll_outcomes = await poll_rrd_telemetry(_pdb)
                            _record_poll_health(poll_outcomes)
                except TimeoutError:
                    _logger.warning("proxmox_rrd_poll timed out (270s) — skipping cycle")
```

- [ ] **Step 4: Verify ruff passes**

```bash
cd apps/backend && ruff check src/app/main.py
```
Expected: no output (clean)

---

### Task 8: API — expose `last_sync_error` and `last_poll_error`

Three files form the API response path: schema → query → endpoint.

**Files:**
- Modify: `apps/backend/src/app/schemas/proxmox.py:127`
- Modify: `apps/backend/src/app/services/proxmox_queries.py:90-99`

- [ ] **Step 1: Extend `ProxmoxSyncStatus` schema (`schemas/proxmox.py:127`)**

After `storage_count: int = 0` (line 127), add:

```python
    last_sync_error: str | None = None
    last_poll_error: str | None = None
```

- [ ] **Step 2: Add both fields to the `get_sync_status()` return dict (`proxmox_queries.py:90-99`)**

Current return dict:
```python
    return {
        "integration_id": config.id,
        "last_sync_at": config.last_sync_at,
        "last_sync_status": config.last_sync_status,
        "cluster_name": config.cluster_name,
        "nodes_count": nodes_count,
        "vms_count": vms_count,
        "cts_count": cts_count,
        "storage_count": storage_count,
    }
```

New:
```python
    return {
        "integration_id": config.id,
        "last_sync_at": config.last_sync_at,
        "last_sync_status": config.last_sync_status,
        "last_sync_error": config.last_sync_error,
        "last_poll_error": config.last_poll_error,
        "cluster_name": config.cluster_name,
        "nodes_count": nodes_count,
        "vms_count": vms_count,
        "cts_count": cts_count,
        "storage_count": storage_count,
    }
```

- [ ] **Step 3: Verify ruff passes**

```bash
cd apps/backend && ruff check src/app/schemas/proxmox.py src/app/services/proxmox_queries.py
```
Expected: no output (clean)

---

### Task 9: UI — status badge, relative time, error blocks

**Files:**
- Modify: `apps/frontend/src/components/proxmox/ProxmoxIntegrationSection.jsx`

- [ ] **Step 1: Add `"partial"` to `STATUS_BADGE_MAP` (line 20-24)**

Current:
```js
const STATUS_BADGE_MAP = new Map([
  ['ok', { color: '#22c55e', bg: 'rgba(34,197,94,0.12)', label: 'Connected' }],
  ['error', { color: '#ef4444', bg: 'rgba(239,68,68,0.1)', label: 'Error' }],
  ['syncing', { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', label: 'Syncing' }],
]);
```

New:
```js
const STATUS_BADGE_MAP = new Map([
  ['ok', { color: '#22c55e', bg: 'rgba(34,197,94,0.12)', label: 'Connected' }],
  ['partial', { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', label: 'Partial' }],
  ['error', { color: '#ef4444', bg: 'rgba(239,68,68,0.1)', label: 'Error' }],
  ['syncing', { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', label: 'Syncing' }],
]);
```

- [ ] **Step 2: Add `relativeTime()` helper after `STATUS_BADGE_MAP`**

Add immediately after the closing `]);` of `STATUS_BADGE_MAP`:

```js
function relativeTime(iso) {
  if (!iso) return null;
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}
```

- [ ] **Step 3: Replace `toLocaleString()` with `relativeTime()`**

Find (line 422-424):
```jsx
                {c.last_sync_at && (
                  <span>Last sync: {new Date(c.last_sync_at).toLocaleString()}</span>
                )}
```

Replace with:
```jsx
                {c.last_sync_at && (
                  <span>Last sync: {relativeTime(c.last_sync_at)}</span>
                )}
```

- [ ] **Step 4: Add sync error block immediately after the `last_sync_at` span**

```jsx
                {status?.last_sync_error && (
                  <div style={{
                    marginTop: 6,
                    fontSize: 11,
                    padding: '6px 10px',
                    borderRadius: 5,
                    background: 'rgba(245,158,11,0.08)',
                    color: '#f59e0b',
                    whiteSpace: 'pre-wrap',
                  }}>
                    ⚠ {status.last_sync_error}
                  </div>
                )}
```

- [ ] **Step 5: Add poll error block immediately after the sync error block**

```jsx
                {status?.last_poll_error && (
                  <div style={{
                    marginTop: 4,
                    fontSize: 11,
                    padding: '6px 10px',
                    borderRadius: 5,
                    background: 'rgba(99,102,241,0.08)',
                    color: '#818cf8',
                    whiteSpace: 'pre-wrap',
                  }}>
                    ⚡ Telemetry: {status.last_poll_error}
                  </div>
                )}
```

- [ ] **Step 6: Verify the frontend builds without errors**

```bash
cd apps/frontend && npm run build 2>&1 | tail -20
```
Expected: build completes with no errors

---

## Verification Checklist

After all tasks are complete:

| Check | Command / Action | Expected |
|---|---|---|
| Migration applies | `make migrate` | `0063_proxmox_sync_health` in output |
| ruff clean | `ruff check src/app/main.py src/app/db/models.py src/app/services/proxmox_telemetry.py src/app/services/proxmox_queries.py src/app/schemas/proxmox.py` | No output |
| Frontend build | `cd apps/frontend && npm run build` | No errors |
| Successful sync | Trigger discovery → check `integration_configs.last_sync_status` | `"ok"`, `last_sync_error` NULL |
| Sync with VM failure | Cause one VM to fail import → check DB | `"partial"`, `last_sync_error` set |
| Unreachable host | Point config at wrong host → wait for scheduled sync | `"error"`, `last_sync_error` = exception message |
| Internal ValueError (bad token) | Invalid API token → `discover_and_import` returns `ok=False` | `"error"` (not downgraded to `"partial"`), `last_sync_error` set |
| Poll failure | Check DB after a failed node poll | `last_poll_error` set for that config |
| Poll recovery | Poll succeeds after failure | `last_poll_error` cleared to NULL |
| UI badge | Open Proxmox tab after successful sync | Green "Connected" badge + "Xm ago" |
| UI partial badge | Partial sync → open tab | Amber "Partial" badge + amber error block |
| UI poll error | Poll failure recorded → open tab | Indigo "⚡ Telemetry:" block |
