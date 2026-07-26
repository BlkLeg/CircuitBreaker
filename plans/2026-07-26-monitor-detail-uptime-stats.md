# Monitor Detail Uptime Stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show Total Uptime, Last Polled, and 24h/7d/30d/365d availability on the monitor detail page (`/monitors/:id`).

**Architecture:** 24h/7d/30d are computed directly from raw `telemetry_timeseries` (existing `_uptime_pct_map`, unchanged). 365d/Total require data older than the 90-day raw retention window, so the existing hardware-only daily rollup (`DailyUptimeStats` / `rollup_worker.py`) is generalized to cover every monitor target type, keyed by `item_id` instead of `hardware_id`. The `/monitors/{id}/uptime` endpoint returns all five percentages plus `last_polled_at` in one response; the detail page's existing stat block grows from one uptime entry to six.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), React + Vitest/RTL (frontend), Postgres/TimescaleDB.

## Global Constraints

- Spec: `specs/2026-07-26-monitor-detail-uptime-stats-design.md`.
- Fresh-install migration convention: any renamed/new table that already exists in `models.py` must be added to `_EXCLUDED_TABLES` in `apps/backend/migrations/versions/0001_init.py`, or fresh installs double-create it. Verify the migration on a fresh-volume mono boot before considering Task 1 done.
- No retroactive backfill of rollup history — existing rows in the old hardware-only table are cleared during the migration rather than remapped (see Task 1, they can't be faithfully attributed to one `item_id`).
- `pct_365d`/`pct_total` return `None` when no rollup rows exist yet; the frontend renders `—` for `null`, matching the existing 24h-null convention.

---

### Task 1: Generalize the daily rollup to every monitor target type

**Files:**
- Modify: `apps/backend/src/app/db/models.py:300-318` (rename `DailyUptimeStats` → `MonitorDailyStats`)
- Modify: `apps/backend/src/app/workers/rollup_worker.py` (drop the hardware-only filter, roll up by `item_id` directly)
- Modify: `apps/backend/src/app/api/admin.py:404` (rename the model reference in the wipe-all-data list)
- Modify: `apps/backend/migrations/versions/0001_init.py:27` (exclusion list entry `daily_uptime_stats` → `monitor_daily_stats`)
- Create: `apps/backend/migrations/versions/0087_monitor_daily_stats.py`
- Test: `apps/backend/tests/services/test_rollup_worker.py`

**Interfaces:**
- Produces: `MonitorDailyStats` model (`item_id: int`, `date: str` ISO `YYYY-MM-DD`, `total_minutes: int`, `uptime_minutes: int`), table `monitor_daily_stats`, unique on `(item_id, date)`. Task 2 sums these columns for `pct_365d`/`pct_total`.
- Produces: `calculate_daily_rollups(db, target_date)` — same signature as today, now rolls up every `MonitorItem` instead of only `target_type == "hardware"` ones.

- [ ] **Step 1: Write the failing test for the generalized rollup**

```python
# apps/backend/tests/services/test_rollup_worker.py
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import MonitorDailyStats, MonitorItem, TelemetryTimeseries
from app.workers.rollup_worker import calculate_daily_rollups


def _make_item(db_session, **overrides):
    item = MonitorItem(
        name="w",
        host="192.0.2.30",
        check_type="icmp",
        interval_secs=60,
        last_status="up",
        next_due_at=datetime.now(UTC),
        **overrides,
    )
    db_session.add(item)
    db_session.flush()
    return item


def test_rollup_covers_non_hardware_target_types(db_session):
    item = _make_item(db_session, target_type="service", target_id=5)
    day = datetime(2026, 7, 20, tzinfo=UTC)
    db_session.add_all(
        [
            TelemetryTimeseries(
                entity_type="service", entity_id=5, item_id=item.id, metric="avail",
                value=1.0, ts=day + timedelta(minutes=m),
            )
            for m in range(0, 60, 10)
        ]
    )
    db_session.commit()

    calculate_daily_rollups(db_session, "2026-07-20")

    stat = db_session.scalar(
        select(MonitorDailyStats).where(
            MonitorDailyStats.item_id == item.id, MonitorDailyStats.date == "2026-07-20"
        )
    )
    assert stat is not None
    assert stat.total_minutes == 1440
    assert stat.uptime_minutes >= 1


def test_rollup_covers_standalone_monitor(db_session):
    item = _make_item(db_session, target_type=None, target_id=None)
    day = datetime(2026, 7, 20, tzinfo=UTC)
    db_session.add(
        TelemetryTimeseries(
            entity_type="monitor", entity_id=0, item_id=item.id, metric="avail",
            value=0.0, ts=day,
        )
    )
    db_session.commit()

    calculate_daily_rollups(db_session, "2026-07-20")

    stat = db_session.scalar(
        select(MonitorDailyStats).where(
            MonitorDailyStats.item_id == item.id, MonitorDailyStats.date == "2026-07-20"
        )
    )
    assert stat is not None
    assert stat.uptime_minutes == 0


def test_rollup_upserts_on_rerun(db_session):
    item = _make_item(db_session)
    calculate_daily_rollups(db_session, "2026-07-20")
    calculate_daily_rollups(db_session, "2026-07-20")
    count = db_session.scalar(
        select(func.count())
        .select_from(MonitorDailyStats)
        .where(MonitorDailyStats.item_id == item.id, MonitorDailyStats.date == "2026-07-20")
    )
    assert count == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/backend && pytest tests/services/test_rollup_worker.py -v`
Expected: FAIL — `ImportError: cannot import name 'MonitorDailyStats'` (the model doesn't exist yet).

- [ ] **Step 3: Rename the model in `models.py`**

Replace lines 300-318 (`class DailyUptimeStats`) with:

```python
class MonitorDailyStats(Base):
    """Daily aggregated uptime rollup for a monitor, across every target type."""

    __tablename__ = "monitor_daily_stats"
    __table_args__ = (
        UniqueConstraint("item_id", "date", name="uq_monitor_daily_stats_item_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monitor_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[str] = mapped_column(String, nullable=False)  # ISO date string YYYY-MM-DD
    total_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uptime_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
```

(Drops the `hardware` relationship entirely — `MonitorEvent`, the closest analog, has no back-relationship either, just the FK column.)

- [ ] **Step 4: Rewrite `rollup_worker.py` to roll up every monitor by `item_id`**

Replace `calculate_daily_rollups` (lines 19-80) with:

```python
def calculate_daily_rollups(db: Session, target_date: str) -> None:
    """Calculate and upsert daily uptime stats for every monitor using telemetry."""
    item_ids = db.scalars(select(MonitorItem.id)).all()

    dt_start = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=UTC)
    dt_end = dt_start + timedelta(days=1)

    for item_id in item_ids:
        query = text("""
            SELECT count(*) as up_minutes
            FROM (
                SELECT time_bucket('1 minute', ts) as minute_bucket, max(value) as max_avail
                FROM telemetry_timeseries
                WHERE item_id = :item_id
                  AND metric = 'avail'
                  AND ts >= :start_ts AND ts < :end_ts
                GROUP BY minute_bucket
            ) sub
            WHERE max_avail > 0
        """)

        up_minutes = (
            db.scalar(query, {"item_id": item_id, "start_ts": dt_start, "end_ts": dt_end}) or 0
        )

        total_minutes = 24 * 60

        stat = db.scalar(
            select(MonitorDailyStats).where(
                MonitorDailyStats.item_id == item_id,
                MonitorDailyStats.date == target_date,
            )
        )

        if not stat:
            stat = MonitorDailyStats(
                item_id=item_id,
                date=target_date,
                total_minutes=total_minutes,
                uptime_minutes=int(up_minutes),
            )
            db.add(stat)
        else:
            stat.total_minutes = total_minutes
            stat.uptime_minutes = int(up_minutes)
            stat.updated_at = datetime.now(UTC)

    db.commit()
```

Update the import at the top of the file:
```python
from app.db.models import MonitorDailyStats, MonitorItem
```

Update the module docstring (lines 1-5) to:
```python
"""Worker to aggregate daily uptime stats.

Runs periodically to aggregate raw telemetry into MonitorDailyStats
for efficient long-range uptime reporting (365d, all-time).
"""
```

And the audit-log call in `_run_rollup_job_impl`'s except block — change `entity_type="daily_uptime_stats"` to `entity_type="monitor_daily_stats"`.

- [ ] **Step 5: Update the admin wipe-all-data reference**

In `apps/backend/src/app/api/admin.py:404`, change `models.DailyUptimeStats,` to `models.MonitorDailyStats,`.

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd apps/backend && pytest tests/services/test_rollup_worker.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Write the migration**

Create `apps/backend/migrations/versions/0087_monitor_daily_stats.py`:

```python
"""Generalize daily uptime rollup to every monitor target type.

Revision ID: 0087_monitor_daily_stats
Revises: 0086_native_monitors
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0087_monitor_daily_stats"
down_revision = "0086_native_monitors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "daily_uptime_stats" not in set(insp.get_table_names()):
        return

    # Existing rows aggregate every monitor on a hardware node into one row;
    # that can't be faithfully remapped to per-item granularity. Rollups
    # regenerate daily going forward, so clear stale rows rather than migrate.
    op.execute("DELETE FROM daily_uptime_stats")

    for fk in insp.get_foreign_keys("daily_uptime_stats"):
        if "hardware_id" in fk["constrained_columns"]:
            op.drop_constraint(fk["name"], "daily_uptime_stats", type_="foreignkey")
    for uq in insp.get_unique_constraints("daily_uptime_stats"):
        if "hardware_id" in uq["column_names"]:
            op.drop_constraint(uq["name"], "daily_uptime_stats", type_="unique")
    for idx in insp.get_indexes("daily_uptime_stats"):
        if "hardware_id" in idx["column_names"]:
            op.drop_index(idx["name"], table_name="daily_uptime_stats")

    op.drop_column("daily_uptime_stats", "hardware_id")
    op.rename_table("daily_uptime_stats", "monitor_daily_stats")

    op.add_column(
        "monitor_daily_stats",
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("monitor_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_monitor_daily_stats_item_id", "monitor_daily_stats", ["item_id"], if_not_exists=True
    )
    op.create_unique_constraint(
        "uq_monitor_daily_stats_item_date", "monitor_daily_stats", ["item_id", "date"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "monitor_daily_stats" not in set(insp.get_table_names()):
        return

    op.execute("DELETE FROM monitor_daily_stats")
    op.drop_constraint("uq_monitor_daily_stats_item_date", "monitor_daily_stats", type_="unique")
    op.drop_index("ix_monitor_daily_stats_item_id", table_name="monitor_daily_stats")
    op.drop_column("monitor_daily_stats", "item_id")

    op.add_column(
        "monitor_daily_stats", sa.Column("hardware_id", sa.Integer(), nullable=False)
    )
    op.rename_table("monitor_daily_stats", "daily_uptime_stats")

    op.create_foreign_key(
        "daily_uptime_stats_hardware_id_fkey",
        "daily_uptime_stats",
        "hardware",
        ["hardware_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_daily_uptime_stats_hardware_id", "daily_uptime_stats", ["hardware_id"], unique=False
    )
    op.create_unique_constraint(
        "daily_uptime_stats_hardware_id_date_key", "daily_uptime_stats", ["hardware_id", "date"]
    )
```

- [ ] **Step 8: Update the fresh-install exclusion list**

In `apps/backend/migrations/versions/0001_init.py`, in `_EXCLUDED_TABLES` (around line 27), change `"daily_uptime_stats",` to `"monitor_daily_stats",`.

- [ ] **Step 9: Run the full backend monitor test suite**

Run: `cd apps/backend && pytest tests/services/test_rollup_worker.py tests/services/test_monitor_service.py tests/api/test_monitor_api.py -v`
Expected: PASS (pre-existing tests still pass; Task 2/3 haven't touched `get_uptime` yet so no new failures here).

- [ ] **Step 10: Verify the migration on a fresh-volume mono boot**

Per this repo's fresh-install convention: use throwaway secrets and a scratch `CB_DATA_DIR`, run `docker compose up -d --build`, and confirm the stack reaches `healthy` with `restarts=0`. This confirms `0001_init`'s updated exclusion list and the new migration don't collide on a brand-new database.

- [ ] **Step 11: Commit**

```bash
git add apps/backend/src/app/db/models.py apps/backend/src/app/workers/rollup_worker.py \
  apps/backend/src/app/api/admin.py apps/backend/migrations/versions/0001_init.py \
  apps/backend/migrations/versions/0087_monitor_daily_stats.py \
  apps/backend/tests/services/test_rollup_worker.py
git commit -m "feat(monitors): generalize daily uptime rollup to all target types"
```

---

### Task 2: Expand `get_uptime()` to compute all five windows

**Files:**
- Modify: `apps/backend/src/app/services/monitor_service.py:16-24` (import), `:331-332` (`get_uptime`)
- Test: `apps/backend/tests/services/test_monitor_service.py`

**Interfaces:**
- Consumes: `MonitorDailyStats` (Task 1) — columns `item_id`, `date`, `total_minutes`, `uptime_minutes`.
- Consumes: `_uptime_pct_map(db, item_ids, hours=24)` (existing, unchanged) — returns `{item_id: pct}`.
- Produces: `get_uptime(db, monitor_id) -> dict` with keys `pct_24h`, `pct_7d`, `pct_30d`, `pct_365d`, `pct_total`, `last_polled_at`. Task 3's API route returns this dict directly.

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/services/test_monitor_service.py`:

```python
from datetime import UTC, datetime, timedelta

from app.db.models import MonitorDailyStats, TelemetryTimeseries


def test_get_uptime_short_windows_from_telemetry(db_session):
    created = monitor_service.create_monitor(
        db_session, MonitorCreate(name="w", check_type="icmp", host="192.0.2.20", config={})
    )
    now = datetime.now(UTC)
    db_session.add_all(
        [
            TelemetryTimeseries(
                entity_type="monitor", entity_id=0, item_id=created["id"], metric="avail",
                value=1.0, ts=now - timedelta(hours=1),
            ),
            TelemetryTimeseries(
                entity_type="monitor", entity_id=0, item_id=created["id"], metric="avail",
                value=0.0, ts=now - timedelta(hours=2),
            ),
        ]
    )
    db_session.commit()

    uptime = monitor_service.get_uptime(db_session, created["id"])
    assert uptime["pct_24h"] == 50.0
    assert uptime["pct_7d"] == 50.0
    assert uptime["pct_30d"] == 50.0


def test_get_uptime_long_windows_from_rollups(db_session):
    created = monitor_service.create_monitor(
        db_session, MonitorCreate(name="r", check_type="icmp", host="192.0.2.21", config={})
    )
    today = datetime.now(UTC).date()
    db_session.add_all(
        [
            MonitorDailyStats(
                item_id=created["id"],
                date=(today - timedelta(days=1)).isoformat(),
                total_minutes=1440,
                uptime_minutes=1440,
            ),
            MonitorDailyStats(
                item_id=created["id"],
                date=(today - timedelta(days=2)).isoformat(),
                total_minutes=1440,
                uptime_minutes=720,
            ),
        ]
    )
    db_session.commit()

    uptime = monitor_service.get_uptime(db_session, created["id"])
    assert uptime["pct_365d"] == 75.0
    assert uptime["pct_total"] == 75.0


def test_get_uptime_no_data_is_none(db_session):
    created = monitor_service.create_monitor(
        db_session, MonitorCreate(name="n", check_type="icmp", host="192.0.2.22", config={})
    )
    uptime = monitor_service.get_uptime(db_session, created["id"])
    assert uptime == {
        "pct_24h": None,
        "pct_7d": None,
        "pct_30d": None,
        "pct_365d": None,
        "pct_total": None,
        "last_polled_at": None,
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/backend && pytest tests/services/test_monitor_service.py -v -k uptime`
Expected: FAIL — `KeyError: 'pct_7d'` (current `get_uptime` only returns `pct_24h`).

- [ ] **Step 3: Implement the expanded `get_uptime`**

Add `MonitorDailyStats` to the model import block at the top of `monitor_service.py` (line 16-24):

```python
from app.db.models import (
    ComputeUnit,
    ExternalNode,
    Hardware,
    MonitorDailyStats,
    MonitorEvent,
    MonitorItem,
    Service,
    TelemetryTimeseries,
)
```

Replace `get_uptime` (lines 331-332) with:

```python
def _rollup_pct(db: Session, item_id: int, *, since_date: str | None = None) -> float | None:
    query = select(
        func.sum(MonitorDailyStats.uptime_minutes), func.sum(MonitorDailyStats.total_minutes)
    ).where(MonitorDailyStats.item_id == item_id)
    if since_date is not None:
        query = query.where(MonitorDailyStats.date >= since_date)
    up, total = db.execute(query).one()
    if not total:
        return None
    return round(up / total * 100, 1)


def get_uptime(db: Session, monitor_id: int) -> dict:
    item = db.get(MonitorItem, monitor_id)
    since_365d = (datetime.now(UTC) - timedelta(days=365)).strftime("%Y-%m-%d")
    return {
        "pct_24h": _uptime_pct_map(db, [monitor_id], hours=24).get(monitor_id),
        "pct_7d": _uptime_pct_map(db, [monitor_id], hours=24 * 7).get(monitor_id),
        "pct_30d": _uptime_pct_map(db, [monitor_id], hours=24 * 30).get(monitor_id),
        "pct_365d": _rollup_pct(db, monitor_id, since_date=since_365d),
        "pct_total": _rollup_pct(db, monitor_id),
        "last_polled_at": item.last_polled_at if item else None,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/backend && pytest tests/services/test_monitor_service.py -v -k uptime`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/monitor_service.py apps/backend/tests/services/test_monitor_service.py
git commit -m "feat(monitors): compute 7d/30d/365d/total uptime in get_uptime"
```

---

### Task 3: Expose the new fields on `GET /monitors/{id}/uptime`

**Files:**
- Modify: `apps/backend/src/app/schemas/monitor.py` (new `MonitorUptimeRead` schema)
- Modify: `apps/backend/src/app/api/monitor.py:10-20` (import), `:226-230` (route)
- Modify: `apps/backend/tests/api/test_monitor_api.py:67-73` (existing shape assertion)

**Interfaces:**
- Consumes: `monitor_service.get_uptime(db, monitor_id)` (Task 2) — dict with keys `pct_24h`, `pct_7d`, `pct_30d`, `pct_365d`, `pct_total`, `last_polled_at`.
- Produces: `MonitorUptimeRead` schema, used as `response_model` on `GET /monitors/{id}/uptime`. Task 4's frontend consumes this exact shape via `getMonitorUptime()`.

- [ ] **Step 1: Write the failing API test**

Replace `test_uptime_and_history_empty_ok` in `apps/backend/tests/api/test_monitor_api.py:67-73` with:

```python
@pytest.mark.asyncio
async def test_uptime_and_history_empty_ok(client, auth_headers):
    mid = (await _create(client, auth_headers)).json()["id"]
    uptime = await client.get(f"/api/v1/monitors/{mid}/uptime", headers=auth_headers)
    assert uptime.json() == {
        "pct_24h": None,
        "pct_7d": None,
        "pct_30d": None,
        "pct_365d": None,
        "pct_total": None,
        "last_polled_at": None,
    }
    history = await client.get(f"/api/v1/monitors/{mid}/history", headers=auth_headers)
    assert history.json() == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/backend && pytest tests/api/test_monitor_api.py -v -k test_uptime_and_history_empty_ok`
Expected: FAIL — response is currently `{"pct_24h": None}`, missing the other keys.

- [ ] **Step 3: Add the response schema**

In `apps/backend/src/app/schemas/monitor.py`, add after `MonitorCheckPoint` (after line 145, before `MonitorOverview`):

```python
class MonitorUptimeRead(BaseModel):
    """Availability across every window the detail page renders."""

    pct_24h: float | None = None
    pct_7d: float | None = None
    pct_30d: float | None = None
    pct_365d: float | None = None
    pct_total: float | None = None
    last_polled_at: datetime | None = None
```

- [ ] **Step 4: Wire it into the route**

In `apps/backend/src/app/api/monitor.py`, add `MonitorUptimeRead` to the import block (lines 10-20):

```python
from app.schemas.monitor import (
    MonitorCreate,
    MonitorEventRead,
    MonitorHistoryPoint,
    MonitorOverview,
    MonitorRead,
    MonitorUpdate,
    MonitorUptimeRead,
    TargetMonitorCreate,
    TargetMonitorSummary,
    TargetType,
)
```

Update the route (lines 226-230):

```python
@router.get("/{monitor_id}/uptime", response_model=MonitorUptimeRead)
def get_uptime(monitor_id: int, db: Session = Depends(get_db)) -> Any:
    if not monitor_service.get_monitor(db, monitor_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor_service.get_uptime(db, monitor_id)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd apps/backend && pytest tests/api/test_monitor_api.py -v -k test_uptime_and_history_empty_ok`
Expected: PASS.

- [ ] **Step 6: Run the full backend test suite for this app**

Run: `cd apps/backend && pytest tests/ -v`
Expected: PASS (no regressions elsewhere).

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/app/schemas/monitor.py apps/backend/src/app/api/monitor.py \
  apps/backend/tests/api/test_monitor_api.py
git commit -m "feat(monitors): return all uptime windows from GET /monitors/{id}/uptime"
```

---

### Task 4: Render the six stats on the monitor detail page

**Files:**
- Modify: `apps/frontend/src/pages/MonitorDetailPage.jsx`
- Test: Create `apps/frontend/src/__tests__/monitor-detail-page.test.jsx`

**Interfaces:**
- Consumes: `getMonitorUptime(id)` (existing, `apps/frontend/src/api/monitor.js:17`) — now resolves `{ data: { pct_24h, pct_7d, pct_30d, pct_365d, pct_total, last_polled_at } }` per Task 3.

- [ ] **Step 1: Write the failing frontend tests**

Create `apps/frontend/src/__tests__/monitor-detail-page.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ id: '7' }),
}));

vi.mock('../api/monitor', () => ({
  getMonitor: vi.fn(),
  getMonitorEvents: vi.fn().mockResolvedValue({ data: [] }),
  getMonitorHistory: vi.fn().mockResolvedValue({ data: [] }),
  getMonitorUptime: vi.fn(),
  pauseMonitor: vi.fn().mockResolvedValue({ data: {} }),
  resumeMonitor: vi.fn().mockResolvedValue({ data: {} }),
  runCheck: vi.fn().mockResolvedValue({ data: {} }),
}));

vi.mock('../hooks/useMonitorStream', () => ({
  useMonitorStream: () => ({ statuses: new Map() }),
}));

const mockToast = { success: vi.fn(), error: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));
vi.mock('../components/monitors/LatencyChart', () => ({ default: () => <div>chart</div> }));
vi.mock('../components/monitors/CheckHistoryBar', () => ({ default: () => <div>history</div> }));
vi.mock('../components/monitors/StatusPill', () => ({ default: () => <div>status</div> }));

import { getMonitor, getMonitorUptime } from '../api/monitor';
import MonitorDetailPage from '../pages/MonitorDetailPage.jsx';

const monitor = {
  id: 7,
  name: 'edge web',
  check_type: 'http',
  host: '192.0.2.7',
  config: { url: 'https://192.0.2.7/health' },
  status: 'up',
  enabled: true,
  interval_secs: 60,
  last_polled_at: '2026-07-26T18:00:00Z',
};

beforeEach(() => {
  vi.clearAllMocks();
  getMonitor.mockResolvedValue({ data: monitor });
});

describe('MonitorDetailPage uptime stats', () => {
  it('shows all six availability stats once loaded', async () => {
    getMonitorUptime.mockResolvedValue({
      data: {
        pct_24h: 99.8,
        pct_7d: 99.5,
        pct_30d: 98.9,
        pct_365d: 99.1,
        pct_total: 99.3,
        last_polled_at: '2026-07-26T18:05:00Z',
      },
    });
    render(<MonitorDetailPage />);
    await waitFor(() => expect(screen.getByText('Total Uptime')).toBeTruthy());
    expect(screen.getByText('Last Polled')).toBeTruthy();
    expect(screen.getByText('24 Hour')).toBeTruthy();
    expect(screen.getByText('7-Day')).toBeTruthy();
    expect(screen.getByText('30-Day')).toBeTruthy();
    expect(screen.getByText('365-Day')).toBeTruthy();
    expect(screen.getByText('99.8%')).toBeTruthy();
    expect(screen.getByText('99.5%')).toBeTruthy();
    expect(screen.getByText('98.9%')).toBeTruthy();
    expect(screen.getByText('99.1%')).toBeTruthy();
    expect(screen.getByText('99.3%')).toBeTruthy();
  });

  it('renders — for stats with no data yet', async () => {
    getMonitorUptime.mockResolvedValue({
      data: {
        pct_24h: null,
        pct_7d: null,
        pct_30d: null,
        pct_365d: null,
        pct_total: null,
        last_polled_at: null,
      },
    });
    render(<MonitorDetailPage />);
    await waitFor(() => expect(screen.getByText('Total Uptime')).toBeTruthy());
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(5);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-detail-page.test.jsx`
Expected: FAIL — `screen.getByText('Total Uptime')` not found (page still shows "Uptime (24h)"/"Last check" only).

- [ ] **Step 3: Update `MonitorDetailPage.jsx`**

Replace the `setUptime(up.data.pct_24h);` line (currently line 39) with:

```jsx
    setUptime(up.data);
```

Replace the stat block's uptime/last-check entries (currently lines 93-96):

```jsx
        <dt className="text-muted">Uptime (24h)</dt>
        <dd>{uptime != null ? `${uptime}%` : '—'}</dd>
        <dt className="text-muted">Last check</dt>
        <dd>{monitor.last_polled_at ? new Date(monitor.last_polled_at).toLocaleString() : '—'}</dd>
```

with:

```jsx
        <dt className="text-muted">Total Uptime</dt>
        <dd>{uptime?.pct_total != null ? `${uptime.pct_total}%` : '—'}</dd>
        <dt className="text-muted">Last Polled</dt>
        <dd>
          {(uptime?.last_polled_at ?? monitor.last_polled_at)
            ? new Date(uptime?.last_polled_at ?? monitor.last_polled_at).toLocaleString()
            : '—'}
        </dd>
        <dt className="text-muted">24 Hour</dt>
        <dd>{uptime?.pct_24h != null ? `${uptime.pct_24h}%` : '—'}</dd>
        <dt className="text-muted">7-Day</dt>
        <dd>{uptime?.pct_7d != null ? `${uptime.pct_7d}%` : '—'}</dd>
        <dt className="text-muted">30-Day</dt>
        <dd>{uptime?.pct_30d != null ? `${uptime.pct_30d}%` : '—'}</dd>
        <dt className="text-muted">365-Day</dt>
        <dd>{uptime?.pct_365d != null ? `${uptime.pct_365d}%` : '—'}</dd>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-detail-page.test.jsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full frontend monitor test suite**

Run: `cd apps/frontend && npx vitest run src/__tests__ -t monitor`
Expected: PASS (no regressions in `MonitorsPage`, `MonitorCardDetail`, etc.).

- [ ] **Step 6: Start the dev server and check the real page**

Run the app (see the `run` skill/pattern this repo uses), open a monitor's detail page in a browser, and confirm all six stats render with sensible values (or `—` for a freshly created monitor) alongside the existing Type/Target/Interval fields, Recent checks, Latency chart, and Events table.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/pages/MonitorDetailPage.jsx apps/frontend/src/__tests__/monitor-detail-page.test.jsx
git commit -m "feat(monitors): show total/24h/7d/30d/365d uptime on the detail page"
```
