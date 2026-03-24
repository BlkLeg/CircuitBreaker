# Proxmox Discovery — Reliability & Observability Design

**Date:** 2026-03-24
**Status:** Draft
**Area:** Proxmox integration, topology map, discovery pipeline

---

## Problem

Proxmox discovery is Circuit Breaker's primary data pipeline for the topology map — nodes, VMs, and containers all flow through it. Yet it has no observable health state:

- `IntegrationConfig.last_sync_status` exists in the DB but the Proxmox scheduler never writes to it — it's always NULL.
- Sync errors log to the server console and disappear. Users get no signal when a sync fails.
- Per-entity import failures (a VM that can't be resolved to a parent node) are caught and returned in `result["errors"]` for manual discovery runs, but are silently swallowed on every scheduled sync.
- The Proxmox tab shows a "Not synced" badge perpetually, even after successful syncs.
- The three telemetry polling functions (`poll_node_telemetry`, `poll_vm_telemetry`, `poll_rrd_telemetry`) catch per-config exceptions internally and log them, but return `None` — the wrappers in `main.py` have no per-config identity and cannot surface poll failures to the UI.

**Result:** Users can't tell if their topology map is fresh, stale, or broken without SSHing into the server and tailing logs.

---

## Goals

1. Every scheduled sync writes its outcome (status + any errors) to the DB.
2. The Proxmox tab surfaces last-sync time, status (ok / partial / error), and error detail.
3. Partial failures ("3 of 5 VMs failed to import") are distinguished from total failures ("couldn't connect").
4. Telemetry poll failures are surfaced per-config in the UI, separate from sync health.
5. Zero new external dependencies; changes are backward-compatible.

---

## Non-Goals

- New retry logic — `discover_and_import()` already uses `INTEGRATION_RETRY_ATTEMPTS` with exponential backoff for API-level errors; the 120s VM poll already keeps VM statuses current.
- Event-driven Proxmox webhooks — polling interval is sufficient for homelab use.
- Per-VM error history — only the most recent sync's errors are retained.
- Per-poll-cycle error history — only the most recent poll's errors are retained.

---

## Architecture

### Sync health: `_record_sync_health()`

A single function (`main.py`) that the full-sync path calls after each per-config attempt. It takes the result dict OR an exception, classifies the outcome, and writes to `IntegrationConfig`:

```
_proxmox_full_sync()  ──→  _record_sync_health(cfg.id, result=..., exc=...)
  (per-config loop)               │
                                  └──→  IntegrationConfig.last_sync_status
                                        IntegrationConfig.last_sync_error
                                        IntegrationConfig.last_sync_at
```

**Status classification:**

| Condition | `last_sync_status` |
|---|---|
| Sync completed, no errors | `"ok"` |
| Sync completed, some entities failed | `"partial"` |
| Sync threw uncaught exception | `"error"` |
| Never synced | `None` |

### Poll health: `_record_poll_health()`

A companion function (`main.py`) called by each polling wrapper after the service function returns. The service functions now return `dict[int, Exception | None]` — a map of `config_id → exception_or_none` — instead of `None`. The wrapper passes this dict to `_record_poll_health()`, which writes `last_poll_error` for each config.

```
_proxmox_node_poll()  ──→  poll_node_telemetry() → dict[int, exc|None]
_proxmox_vm_poll()    ──→  poll_vm_telemetry()  → dict[int, exc|None]  ──→  _record_poll_health(results)
_proxmox_rrd_poll()   ──→  poll_rrd_telemetry() → dict[int, exc|None]       │
                                                                              └──→  IntegrationConfig.last_poll_error
```

Sync health and poll health are **intentionally separate signals**: sync health reflects topology import quality; poll health reflects live telemetry collection quality. They run at different cadences (full sync: configurable interval; node poll: 30s; VM poll: 120s; RRD poll: 300s) and are displayed as separate blocks in the UI.

### New DB columns

Both columns land in migration 0063:

- `last_sync_error: Text | None` — up to 5 per-entity error strings (joined with newline), or the exception message for hard failures. Truncated at 512 chars.
- `last_poll_error: Text | None` — the most recent per-config poll failure message. Null when all polls are clean. Truncated at 512 chars.

### API addition

`GET /integrations/proxmox/{id}/status` — add both fields to its response:
```python
"last_sync_error": config.last_sync_error,
"last_poll_error": config.last_poll_error,
```

### UI changes (ProxmoxIntegrationSection.jsx)

The component already renders:
- `StatusBadge` using `c.last_sync_status` (but always blank currently)
- `Last sync: <timestamp>` using `c.last_sync_at`

Changes needed:
1. Add `"partial"` to `STATUS_BADGE_MAP` (amber color, label "Partial")
2. Replace `toLocaleString()` on `last_sync_at` with a relative time display ("2m ago")
3. Add an amber sync error block that renders `status.last_sync_error` when set
4. Add an indigo poll error block that renders `status.last_poll_error` when set (distinct color from sync errors to signal different cadence/severity)

---

## Implementation Plan

### Step 1 — Migration `0063_proxmox_sync_health.py`

```python
down_revision = "<latest migration>"  # e.g. 0062_native_monitoring

def upgrade():
    op.add_column("integration_configs",
        sa.Column("last_sync_error", sa.Text(), nullable=True))
    op.add_column("integration_configs",
        sa.Column("last_poll_error", sa.Text(), nullable=True))

def downgrade():
    op.drop_column("integration_configs", "last_poll_error")
    op.drop_column("integration_configs", "last_sync_error")
```

### Step 2 — `IntegrationConfig` model (`models.py`)

Add after the existing `last_sync_status` column:
```python
last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
last_poll_error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

### Step 3 — `_record_sync_health()` in `main.py`

A standalone helper that opens its own synchronous session so it is safe to call regardless of the caller's session state (e.g. after a rolled-back transaction):

```python
def _record_sync_health(
    config_id: int,
    result: dict | None = None,
    exc: Exception | None = None,
) -> None:
    """Write sync outcome to IntegrationConfig. Opens its own session — safe after rollbacks."""
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
                    # discover_and_import caught a hard failure internally and returned ok=False
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

**Imports:** `get_session_context` and `utcnow` are already imported at module level in `main.py`. `IntegrationConfig` is currently only imported inside a `with get_session_context()` block inside `lifespan()`. Add a new module-level import line:
```python
from app.db.models import IntegrationConfig
```
Place it alongside the other `app.db` imports at the top of the file. This is a new import line (not a hoist of the existing local import) and is required so `_record_sync_health()` and `_record_poll_health()` — both defined at module scope — can reference it.

### Step 4 — `_record_poll_health()` in `main.py`

A companion helper alongside `_record_sync_health()`:

```python
def _record_poll_health(results: dict[int, Exception | None]) -> None:
    """Write poll error summary to IntegrationConfig.last_poll_error for each config."""
    for config_id, exc in results.items():
        try:
            with get_session_context() as db:
                cfg = db.get(IntegrationConfig, config_id)
                if not cfg:
                    continue
                cfg.last_poll_error = str(exc)[:512] if exc is not None else None
                db.commit()
        except Exception:
            _logger.exception("Failed to record poll health for config %s", config_id)
```

No `last_sync_at` update here — that timestamp belongs to the full sync path.

### Step 5 — Wire `_record_sync_health()` into `_proxmox_full_sync()` (`main.py`)

The function loops over all auto-sync configs using a synchronous session. Update the inner loop to capture the result and call `_record_sync_health()`:

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

**`ProxmoxDiscoverRun` note:** Manual/API-triggered discovery runs continue to write `ProxmoxDiscoverRun` rows (with JSONB `errors`). Scheduled syncs do not create `ProxmoxDiscoverRun` rows — `IntegrationConfig.last_sync_error` is the canonical health signal for the scheduler path. The two stores serve different consumers and are intentionally separate.

### Step 6 — Service return type changes (`proxmox_telemetry.py`)

Update all three polling service functions to return `dict[int, Exception | None]` instead of `None`. The three functions are **not symmetric** — `poll_node_telemetry` has a circuit breaker while `poll_vm_telemetry` and `poll_rrd_telemetry` do not. Apply the correct pattern for each.

**`poll_node_telemetry` (has circuit breaker):**

`results[config.id] = None` is set only on a **genuinely successful poll** (inside the `try` block, after the actual API call completes). Do NOT set it before the `if breaker.is_open(): continue` check. Configs skipped by an open breaker are intentionally absent from the dict — `_record_poll_health()` will not touch them, leaving any stale `last_poll_error` in place until a real successful poll clears it.

```python
async def poll_node_telemetry(db: AsyncSession) -> dict[int, Exception | None]:
    results: dict[int, Exception | None] = {}
    configs = ...  # existing query unchanged
    for config in configs:
        if breaker.is_open():              # existing open-breaker check — no results entry
            continue
        try:
            # ... existing poll logic ...
            results[config.id] = None      # set only after successful completion
            breaker.record_success()       # existing (if present)
        except Exception as e:
            results[config.id] = e         # failure
            breaker.record_failure()       # existing
            _logger.warning(...)           # existing
    return results
```

**`poll_vm_telemetry` and `poll_rrd_telemetry` (no circuit breaker):**

These functions have a simpler per-config `try/except` with no breaker. Add `results` with the same success/failure pattern but without any breaker references:

```python
async def poll_vm_telemetry(db: AsyncSession) -> dict[int, Exception | None]:
    results: dict[int, Exception | None] = {}
    configs = ...  # existing query unchanged
    for config in configs:
        try:
            # ... existing poll logic ...
            results[config.id] = None
        except Exception as e:
            results[config.id] = e
            _logger.warning(...)           # existing
    return results

# Same pattern for poll_rrd_telemetry
```

### Step 7 — Wire `_record_poll_health()` into polling wrappers (`main.py`)

Update the three wrapper closures to capture the service return value. **Note structural difference:** `_proxmox_node_poll` and `_proxmox_vm_poll` are defined at the top of the `lifespan()` block (before the `if has_proxmox:` check), while `_proxmox_rrd_poll` is defined **inside** the `if has_proxmox:` block. Update each wrapper in-place at its existing scope — do not promote `_proxmox_rrd_poll` out of the conditional.

```python
# Defined before if has_proxmox: — update in place
async def _proxmox_node_poll():
    try:
        async with asyncio.timeout(25):
            async with AsyncSessionLocal() as _pdb:
                results = await poll_node_telemetry(_pdb)
                _record_poll_health(results)
    except TimeoutError:
        _logger.warning("proxmox_node_poll timed out (25s) — skipping cycle")

async def _proxmox_vm_poll():
    try:
        async with asyncio.timeout(100):
            async with AsyncSessionLocal() as _pdb:
                results = await poll_vm_telemetry(_pdb)
                _record_poll_health(results)
    except TimeoutError:
        _logger.warning("proxmox_vm_poll timed out (100s) — skipping cycle")

# Defined inside if has_proxmox: — update in place at that indent level
async def _proxmox_rrd_poll():
    try:
        async with asyncio.timeout(270):
            async with AsyncSessionLocal() as _pdb:
                results = await poll_rrd_telemetry(_pdb)
                _record_poll_health(results)
    except TimeoutError:
        _logger.warning("proxmox_rrd_poll timed out (270s) — skipping cycle")
```

### Step 8 — API response (`api/proxmox.py`)

Locate the `GET /integrations/proxmox/{id}/status` response dict and add both new fields:
```python
"last_sync_error": config.last_sync_error,
"last_poll_error": config.last_poll_error,
```

### Step 9 — UI (`ProxmoxIntegrationSection.jsx`)

**A) Extend STATUS_BADGE_MAP:**
```js
['partial', { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', label: 'Partial' }],
```

**B) Add relative time helper:**
```js
function relativeTime(iso) {
  if (!iso) return null;
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}
```
Replace the `new Date(c.last_sync_at).toLocaleString()` display with `relativeTime(c.last_sync_at)`, preserving the existing `{c.last_sync_at && ...}` null guard.

**C) Sync error display** — after the existing metadata row (URL, cluster, counts, last sync), add:
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

**D) Poll error display** — immediately after the sync error block:
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

Indigo distinguishes telemetry poll failures from the amber sync failures — different cadence, lower urgency.

---

## Verification

| Test | Expected |
|---|---|
| Successful discovery run | `last_sync_status = "ok"`, `last_sync_error = NULL`, `last_sync_at` updated; UI shows green "Connected" badge + "Xm ago" |
| Discovery with one failing VM | `last_sync_status = "partial"`, `last_sync_error` lists the VM error; UI shows amber "Partial" badge + error block |
| Unreachable Proxmox host | `last_sync_status = "error"`, `last_sync_error` = exception message; UI shows red "Error" badge |
| Server restart (no sync yet) | `last_sync_status = NULL`; UI shows "Not synced" as before |
| Node poll failure for one config | `last_poll_error` set for that config; UI shows indigo "⚡ Telemetry:" block |
| All polls succeed | `last_poll_error = NULL` for all configs; no telemetry error block shown |
| Poll fails, breaker opens (node poll only) | `last_poll_error` set on failure cycle; while breaker is open, config is absent from `results` dict so `last_poll_error` persists unchanged — error remains visible in UI until recovery |
| Breaker resets, poll succeeds | `results[config.id] = None` written after successful completion; `_record_poll_health()` clears `last_poll_error` to NULL |
| ruff check | `ruff check apps/backend/src/app/main.py apps/backend/src/app/api/proxmox.py apps/backend/src/app/db/models.py apps/backend/src/app/services/proxmox_telemetry.py` passes |

---

## Alternatives Considered

**Register Proxmox as an IntegrationPlugin** — would let it use the generic sync worker's built-in error tracking. Rejected: Proxmox sync is fundamentally different (full topology import, not just status polling). Refactoring to a plugin is high-risk for a reliability sprint and would require significant architectural changes.

**Store full error history** — a separate `proxmox_sync_errors` table with one row per sync. Rejected (YAGNI): the last sync's errors are sufficient for diagnosis; full history adds complexity without clear user value.

**Callback parameter on service functions** — `on_config_error: Callable[[int, Exception], None]` passed into each polling service. Rejected: unusual pattern in this codebase; harder to read and test; mixes async context with sync health writer.

**Move health recording into the service layer** — `proxmox_telemetry.py` calls `_record_poll_health()` directly as a side effect. Rejected: violates separation of concerns; the telemetry service shouldn't own health DB writes; creates tight coupling between telemetry and integration config table.
