# Continuous Polling Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sequential, single-process uptime monitor with a durable, horizontally scalable, item-based polling engine that records availability, latency, packet loss, and jitter into the existing TimescaleDB time-series store.

**Architecture:** A singleton scheduler (advisory-lock guarded) atomically claims due `MonitorItem` rows and publishes one poll message per item to a NATS JetStream work-queue. N poll workers consume, run the ICMP/TCP/HTTP collector for the item, and bulk-write samples to `telemetry_timeseries`. Scheduling state lives entirely in `monitor_items.next_due_at`, so process restarts self-heal with no wedged state.

**Tech Stack:** Python 3.11, FastAPI/SQLAlchemy 2.x (Mapped columns), Alembic, PostgreSQL + TimescaleDB, NATS JetStream (`nats-py`), APScheduler (existing), pytest + testcontainers.

## Global Constraints

- **Design reference:** `specs/2026-07-13-continuous-polling-engine-design.md`. Every task implements part of it.
- **Migration numbering:** current Alembic head is `0080_app_role_schema_grants`. New migrations continue from `0081`, each `down_revision` pointing at the previous new migration.
- **NATS subject namespace:** poll messages use subject root **`mon.`** (`mon.poll.item`), NOT `monitor.` — the shared `CB_EVENTS` stream already owns `monitor.>` and overlapping subjects across two streams is a NATS error.
- **Time columns:** new datetime columns use `DateTime(timezone=True)` with the existing `_now` default from `app/db/models.py` (do not copy `HardwareMonitor`'s legacy string timestamps).
- **Overdue policy:** poll-once-now, no backfill. `next_due_at` is advanced at *enqueue* time in the same atomic statement that claims the item.
- **No silent failure:** a failed/timed-out collector emits an `avail=0` sample with an `error_reason`, never zero samples.
- **Tests:** run from `apps/backend/` with `poetry run pytest`. DB tests use the `db_session` and `factories` fixtures in `tests/conftest.py` (sync `SessionLocal`, transaction-rollback per test).
- **Commit style:** end messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

**New files**
- `apps/backend/src/app/services/monitoring/__init__.py` — package marker.
- `apps/backend/src/app/services/monitoring/collectors.py` — `Sample` dataclass + pure collector functions + `COLLECTORS` registry.
- `apps/backend/src/app/services/monitoring/writer.py` — bulk sample writer into `telemetry_timeseries`.
- `apps/backend/src/app/services/monitoring/scheduler.py` — atomic due-item claim + enqueue.
- `apps/backend/src/app/workers/monitor_scheduler.py` — scheduler worker loop (advisory-lock singleton).
- `apps/backend/src/app/workers/monitor_poll_worker.py` — JetStream poll-consumer worker.
- `apps/backend/migrations/versions/0081_monitor_items.py` — `monitor_items` table.
- `apps/backend/migrations/versions/0082_telemetry_item_id.py` — add `item_id` to `telemetry_timeseries`.
- `apps/backend/migrations/versions/0083_migrate_hardware_monitors.py` — data migration from `hardware_monitors`.
- Tests: `tests/services/test_monitor_collectors.py`, `tests/services/test_monitor_writer.py`, `tests/services/test_monitor_scheduler.py`, `tests/services/test_monitor_poll_worker.py`, `tests/integration/test_monitor_engine_e2e.py`.

**Modified files**
- `apps/backend/src/app/db/models.py` — add `MonitorItem`; add `item_id` to `TelemetryTimeseries`.
- `apps/backend/src/app/core/subjects.py` — add `MONITOR_POLL_ITEM` subject.
- `apps/backend/src/app/core/nats_client.py` — add `ensure_monitor_poll_stream()`.
- `apps/backend/src/app/workers/main.py` — register `monitor_scheduler` and `monitor_poll` worker types.
- `apps/backend/src/app/main.py:900-913` — remove the `run_all_monitors_job` APScheduler registration.
- `docker/supervisord.mono.conf` — bump worker `numprocs` and map new types.

---

### Task 1: `MonitorItem` model + migration

**Files:**
- Modify: `apps/backend/src/app/db/models.py` (add class after `HardwareMonitor`, ~line 247)
- Create: `apps/backend/migrations/versions/0081_monitor_items.py`
- Test: `apps/backend/tests/services/test_monitor_model.py`

**Interfaces:**
- Produces: `MonitorItem` ORM model with columns `id:int`, `target_type:str`, `target_id:int|None`, `host:str`, `check_type:str`, `params:dict` (JSONB), `interval_secs:int`, `enabled:bool`, `next_due_at:datetime`, `last_polled_at:datetime|None`, `last_status:str|None`, `consecutive_failures:int`, `created_at:datetime`, `updated_at:datetime`.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/services/test_monitor_model.py
from datetime import UTC, datetime

from app.db.models import MonitorItem


def test_monitor_item_persists_with_defaults(db_session):
    item = MonitorItem(
        target_type="hardware",
        target_id=1,
        host="10.0.0.5",
        check_type="icmp",
        params={"packet_count": 5, "timeout": 1.5},
        interval_secs=60,
        next_due_at=datetime.now(UTC),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    assert item.id is not None
    assert item.enabled is True
    assert item.consecutive_failures == 0
    assert item.params["packet_count"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'MonitorItem'`.

- [ ] **Step 3: Add the model**

Add to `apps/backend/src/app/db/models.py` immediately after the `HardwareMonitor` class:

```python
class MonitorItem(Base):
    """One polled metric-source (Zabbix-style item): a check on a target at an interval."""

    __tablename__ = "monitor_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String, nullable=False)  # hardware|compute_unit|external_node|ip
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    host: Mapped[str] = mapped_column(String, nullable=False)  # resolved ip/hostname to probe
    check_type: Mapped[str] = mapped_column(String, nullable=False)  # icmp|tcp|http
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    interval_secs: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String, nullable=True)  # up|down|error
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (Index("ix_monitor_items_due", "enabled", "next_due_at"),)
```

If `Index` is not already imported at the top of `models.py`, add it to the `from sqlalchemy import (...)` block.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_model.py -v`
Expected: PASS (the `setup_db` fixture calls `Base.metadata.create_all`, so the table exists in tests).

- [ ] **Step 5: Write the Alembic migration**

```python
# apps/backend/migrations/versions/0081_monitor_items.py
"""Create monitor_items table for the continuous polling engine."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0081_monitor_items"
down_revision = "0080_app_role_schema_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitor_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("check_type", sa.String(), nullable=False),
        sa.Column("params", JSONB(), nullable=False, server_default="{}"),
        sa.Column("interval_secs", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_monitor_items_due", "monitor_items", ["enabled", "next_due_at"])


def downgrade() -> None:
    op.drop_index("ix_monitor_items_due", table_name="monitor_items")
    op.drop_table("monitor_items")
```

- [ ] **Step 6: Verify migration applies cleanly**

Run: `cd apps/backend && poetry run alembic upgrade head && poetry run alembic downgrade -1 && poetry run alembic upgrade head`
Expected: no errors; `monitor_items` created, dropped, recreated.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/app/db/models.py apps/backend/migrations/versions/0081_monitor_items.py apps/backend/tests/services/test_monitor_model.py
git commit -m "feat(monitoring): add MonitorItem model and migration"
```

---

### Task 2: `item_id` on `telemetry_timeseries`

**Files:**
- Modify: `apps/backend/src/app/db/models.py` (`TelemetryTimeseries`, ~line 1551)
- Create: `apps/backend/migrations/versions/0082_telemetry_item_id.py`
- Test: `apps/backend/tests/services/test_monitor_model.py` (add a case)

**Interfaces:**
- Produces: `TelemetryTimeseries.item_id: int | None` column (nullable, indexed).

- [ ] **Step 1: Write the failing test**

Append to `apps/backend/tests/services/test_monitor_model.py`:

```python
def test_telemetry_row_accepts_item_id(db_session):
    from datetime import UTC, datetime

    from app.db.models import TelemetryTimeseries

    row = TelemetryTimeseries(
        entity_type="hardware",
        entity_id=1,
        item_id=42,
        metric="packet_loss_pct",
        value=0.0,
        ts=datetime.now(UTC),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    assert row.item_id == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_model.py::test_telemetry_row_accepts_item_id -v`
Expected: FAIL with `TypeError: 'item_id' is an invalid keyword argument`.

- [ ] **Step 3: Add the column**

In `TelemetryTimeseries`, add after the `entity_id` column:

```python
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_model.py -v`
Expected: PASS (both cases).

- [ ] **Step 5: Write the migration**

```python
# apps/backend/migrations/versions/0082_telemetry_item_id.py
"""Add item_id dimension to telemetry_timeseries for monitor-item samples."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0082_telemetry_item_id"
down_revision = "0081_monitor_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("telemetry_timeseries", sa.Column("item_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_telemetry_timeseries_item_id", "telemetry_timeseries", ["item_id", "metric", "ts"]
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_timeseries_item_id", table_name="telemetry_timeseries")
    op.drop_column("telemetry_timeseries", "item_id")
```

- [ ] **Step 6: Verify migration**

Run: `cd apps/backend && poetry run alembic upgrade head`
Expected: column added, no error.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/app/db/models.py apps/backend/migrations/versions/0082_telemetry_item_id.py apps/backend/tests/services/test_monitor_model.py
git commit -m "feat(monitoring): add item_id dimension to telemetry_timeseries"
```

---

### Task 3: Collectors (ICMP loss/jitter, TCP, HTTP)

**Files:**
- Create: `apps/backend/src/app/services/monitoring/__init__.py` (empty)
- Create: `apps/backend/src/app/services/monitoring/collectors.py`
- Test: `apps/backend/tests/services/test_monitor_collectors.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Sample: metric: str; value: float; error_reason: str | None = None`
  - `def collect_icmp(host: str, params: dict) -> list[Sample]`
  - `def collect_tcp(host: str, params: dict) -> list[Sample]`
  - `def collect_http(host: str, params: dict) -> list[Sample]`
  - `COLLECTORS: dict[str, Callable[[str, dict], list[Sample]]]` keyed by check_type.
  - Every collector always returns a list containing at least an `avail` sample (1.0 up / 0.0 down); on hard failure it returns `avail=0.0` with `error_reason` set.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/services/test_monitor_collectors.py
from unittest.mock import patch

from app.services.monitoring.collectors import (
    COLLECTORS,
    Sample,
    collect_http,
    collect_icmp,
    collect_tcp,
)


def _metric(samples, name):
    return next(s.value for s in samples if s.metric == name)


def test_icmp_all_replies_zero_loss():
    # 5 replies of 10,12,11,13,10 ms
    with patch("app.services.monitoring.collectors._ping_once", side_effect=[10.0, 12.0, 11.0, 13.0, 10.0]):
        samples = collect_icmp("10.0.0.5", {"packet_count": 5, "timeout": 1.0})
    assert _metric(samples, "avail") == 1.0
    assert _metric(samples, "packet_loss_pct") == 0.0
    assert _metric(samples, "latency_ms") == 11.2  # mean
    assert _metric(samples, "latency_min_ms") == 10.0
    assert _metric(samples, "latency_max_ms") == 13.0


def test_icmp_partial_loss():
    with patch("app.services.monitoring.collectors._ping_once", side_effect=[10.0, None, 12.0, None, 14.0]):
        samples = collect_icmp("10.0.0.5", {"packet_count": 5, "timeout": 1.0})
    assert _metric(samples, "avail") == 1.0
    assert _metric(samples, "packet_loss_pct") == 40.0
    assert _metric(samples, "latency_ms") == 12.0  # mean of replies only


def test_icmp_total_loss_is_down():
    with patch("app.services.monitoring.collectors._ping_once", side_effect=[None, None, None]):
        samples = collect_icmp("10.0.0.5", {"packet_count": 3, "timeout": 1.0})
    assert _metric(samples, "avail") == 0.0
    assert _metric(samples, "packet_loss_pct") == 100.0


def test_icmp_missing_tool_reports_error_reason():
    with patch("app.services.monitoring.collectors._ping_once", side_effect=FileNotFoundError("ping")):
        samples = collect_icmp("10.0.0.5", {"packet_count": 3})
    avail = next(s for s in samples if s.metric == "avail")
    assert avail.value == 0.0
    assert avail.error_reason == "icmp_unavailable"


def test_tcp_up_when_any_port_connects():
    with patch("app.services.monitoring.collectors._tcp_connect", side_effect=[(False, None), (True, 5.0)]):
        samples = collect_tcp("10.0.0.5", {"ports": [22, 443], "timeout": 1.0})
    assert _metric(samples, "avail") == 1.0
    assert _metric(samples, "latency_ms") == 5.0


def test_http_status_class_recorded():
    with patch("app.services.monitoring.collectors._http_head", return_value=(200, 8.0)):
        samples = collect_http("10.0.0.5", {"url": "http://10.0.0.5/", "timeout": 2.0})
    assert _metric(samples, "avail") == 1.0
    assert _metric(samples, "http_status_class") == 2.0


def test_registry_maps_check_types():
    assert COLLECTORS["icmp"] is collect_icmp
    assert COLLECTORS["tcp"] is collect_tcp
    assert COLLECTORS["http"] is collect_http
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_collectors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.monitoring'`.

- [ ] **Step 3: Implement the collectors**

Create `apps/backend/src/app/services/monitoring/__init__.py` (empty file).

Create `apps/backend/src/app/services/monitoring/collectors.py`:

```python
"""Pure collector functions for the polling engine.

Each collector runs blocking network I/O and returns a list of Samples. It must
NEVER raise for an unreachable host — it returns avail=0.0 (with error_reason on
a hard failure like a missing tool). No DB access here so collectors are unit-
testable by mocking the private probe helpers.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Sample:
    metric: str
    value: float
    error_reason: str | None = None


# ── Probe primitives (mocked in tests) ─────────────────────────────────────────


def _ping_once(host: str, timeout: float) -> float | None:
    """One ICMP echo. Returns latency in ms, or None on loss. Raises on missing tool."""
    import ping3  # optional dep; ImportError surfaces as a hard failure

    ping3.EXCEPTIONS = False
    result = ping3.ping(host, timeout=timeout, unit="ms")
    if result is None or result is False:
        return None
    return round(float(result), 3)


def _tcp_connect(host: str, port: int, timeout: float) -> tuple[bool, float | None]:
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, round((time.monotonic() - t0) * 1000, 2)
    except OSError:
        return False, None


def _http_head(url: str, timeout: float) -> tuple[int, float]:
    import httpx

    t0 = time.monotonic()
    resp = httpx.head(url, timeout=timeout, follow_redirects=True)
    return resp.status_code, round((time.monotonic() - t0) * 1000, 2)


# ── Collectors ─────────────────────────────────────────────────────────────────


def collect_icmp(host: str, params: dict) -> list[Sample]:
    count = int(params.get("packet_count", 5))
    timeout = float(params.get("timeout", 1.5))
    latencies: list[float] = []
    lost = 0
    try:
        for _ in range(count):
            rtt = _ping_once(host, timeout)
            if rtt is None:
                lost += 1
            else:
                latencies.append(rtt)
    except (ImportError, FileNotFoundError, OSError):
        return [Sample("avail", 0.0, error_reason="icmp_unavailable")]

    loss_pct = round(lost / count * 100, 2) if count else 100.0
    up = 1.0 if latencies else 0.0
    out = [Sample("avail", up), Sample("packet_loss_pct", loss_pct)]
    if latencies:
        mean = round(sum(latencies) / len(latencies), 3)
        jitter = _jitter(latencies)
        out += [
            Sample("latency_ms", mean),
            Sample("latency_min_ms", min(latencies)),
            Sample("latency_max_ms", max(latencies)),
            Sample("jitter_ms", jitter),
        ]
    return out


def _jitter(latencies: list[float]) -> float:
    if len(latencies) < 2:
        return 0.0
    deltas = [abs(latencies[i] - latencies[i - 1]) for i in range(1, len(latencies))]
    return round(sum(deltas) / len(deltas), 3)


def collect_tcp(host: str, params: dict) -> list[Sample]:
    ports = params.get("ports") or [params.get("port", 80)]
    timeout = float(params.get("timeout", 1.0))
    for port in ports:
        ok, latency = _tcp_connect(host, int(port), timeout)
        if ok and latency is not None:
            return [Sample("avail", 1.0), Sample("latency_ms", latency)]
    return [Sample("avail", 0.0)]


def collect_http(host: str, params: dict) -> list[Sample]:
    url = params.get("url") or f"http://{host}/"
    timeout = float(params.get("timeout", 2.0))
    try:
        status, latency = _http_head(url, timeout)
    except Exception:  # noqa: BLE001 — network failure is a datum, not an error
        return [Sample("avail", 0.0, error_reason="http_error")]
    return [
        Sample("avail", 1.0),
        Sample("latency_ms", latency),
        Sample("http_status_class", float(status // 100)),
    ]


COLLECTORS: dict[str, Callable[[str, dict], list[Sample]]] = {
    "icmp": collect_icmp,
    "tcp": collect_tcp,
    "http": collect_http,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_collectors.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/monitoring/ apps/backend/tests/services/test_monitor_collectors.py
git commit -m "feat(monitoring): ICMP/TCP/HTTP collectors with packet loss and jitter"
```

---

### Task 4: Sample writer (bulk insert)

**Files:**
- Create: `apps/backend/src/app/services/monitoring/writer.py`
- Test: `apps/backend/tests/services/test_monitor_writer.py`

**Interfaces:**
- Consumes: `Sample` from `collectors.py`; `MonitorItem`, `TelemetryTimeseries` models.
- Produces: `def write_samples(db: Session, rows: list[SampleRow]) -> int` where
  `SampleRow = tuple[int, str, int | None, list[Sample], datetime]` = `(item_id, entity_type, entity_id, samples, ts)`. Returns number of `telemetry_timeseries` rows inserted. One bulk insert for the whole batch.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/services/test_monitor_writer.py
from datetime import UTC, datetime

from app.db.models import TelemetryTimeseries
from app.services.monitoring.collectors import Sample
from app.services.monitoring.writer import write_samples


def test_write_samples_bulk_inserts_rows(db_session):
    ts = datetime.now(UTC)
    rows = [
        (7, "hardware", 3, [Sample("avail", 1.0), Sample("packet_loss_pct", 0.0)], ts),
        (8, "ip", None, [Sample("avail", 0.0, error_reason="icmp_unavailable")], ts),
    ]
    n = write_samples(db_session, rows)
    db_session.commit()
    assert n == 3

    stored = db_session.query(TelemetryTimeseries).filter(TelemetryTimeseries.item_id == 7).all()
    metrics = {r.metric: r.value for r in stored}
    assert metrics == {"avail": 1.0, "packet_loss_pct": 0.0}
    assert all(r.source == "monitor" for r in stored)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: ... writer`.

- [ ] **Step 3: Implement the writer**

Create `apps/backend/src/app/services/monitoring/writer.py`:

```python
"""Bulk-write collector Samples into the telemetry_timeseries hypertable."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import TelemetryTimeseries
from app.services.monitoring.collectors import Sample

SampleRow = tuple[int, str, int | None, list[Sample], datetime]


def write_samples(db: Session, rows: list[SampleRow]) -> int:
    """Insert all samples from a batch of polled items in one bulk statement.

    Caller owns the transaction (commit/rollback). Returns the row count.
    """
    mappings: list[dict] = []
    for item_id, entity_type, entity_id, samples, ts in rows:
        for s in samples:
            mappings.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id if entity_id is not None else 0,
                    "item_id": item_id,
                    "metric": s.metric,
                    "value": s.value,
                    "source": "monitor",
                    "ts": ts,
                }
            )
    if mappings:
        db.bulk_insert_mappings(TelemetryTimeseries, mappings)
    return len(mappings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_writer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/monitoring/writer.py apps/backend/tests/services/test_monitor_writer.py
git commit -m "feat(monitoring): bulk sample writer into telemetry_timeseries"
```

---

### Task 5: Scheduler claim-and-enqueue

**Files:**
- Create: `apps/backend/src/app/services/monitoring/scheduler.py`
- Modify: `apps/backend/src/app/core/subjects.py` (add subject constant)
- Test: `apps/backend/tests/services/test_monitor_scheduler.py`

**Interfaces:**
- Consumes: `MonitorItem` model; `subjects.MONITOR_POLL_ITEM`.
- Produces:
  - `def claim_due_items(db: Session, batch: int = 200) -> list[dict]` — atomically claims due items, advances their `next_due_at`, returns dicts `{item_id, target_type, target_id, host, check_type, params, interval_secs}`.
  - `async def enqueue_due(db: Session, publish: Callable[[str, dict], Awaitable[bool]], batch: int = 200) -> int` — claims and publishes; returns count enqueued.
- `MONITOR_POLL_ITEM = "mon.poll.item"` in `subjects.py`.

- [ ] **Step 1: Add the subject constant**

In `apps/backend/src/app/core/subjects.py`, add near the other subject groups:

```python
# ── Monitoring poll queue (dedicated work-queue stream; NOT under monitor.>) ──
MONITOR_POLL_ITEM = "mon.poll.item"
```

- [ ] **Step 2: Write the failing test**

```python
# apps/backend/tests/services/test_monitor_scheduler.py
from datetime import UTC, datetime, timedelta

from app.db.models import MonitorItem
from app.services.monitoring.scheduler import claim_due_items


def _mk(db, *, due_offset_s, enabled=True, interval=60):
    item = MonitorItem(
        target_type="ip",
        target_id=None,
        host="10.0.0.9",
        check_type="icmp",
        params={},
        interval_secs=interval,
        enabled=enabled,
        next_due_at=datetime.now(UTC) + timedelta(seconds=due_offset_s),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_claim_returns_only_due_enabled_items(db_session):
    due = _mk(db_session, due_offset_s=-5)
    _mk(db_session, due_offset_s=120)  # not due
    _mk(db_session, due_offset_s=-5, enabled=False)  # disabled

    claimed = claim_due_items(db_session, batch=100)
    ids = [c["item_id"] for c in claimed]
    assert ids == [due.id]


def test_claim_advances_next_due_beyond_now(db_session):
    item = _mk(db_session, due_offset_s=-5, interval=60)
    claim_due_items(db_session, batch=100)
    db_session.expire_all()
    refreshed = db_session.get(MonitorItem, item.id)
    assert refreshed.next_due_at > datetime.now(UTC)
    # Immediately claiming again returns nothing — no double-enqueue.
    assert claim_due_items(db_session, batch=100) == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: ... scheduler`.

- [ ] **Step 4: Implement the scheduler**

Create `apps/backend/src/app/services/monitoring/scheduler.py`:

```python
"""Atomically claim due monitor items and enqueue poll messages.

The claim is a single UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)
RETURNING statement: it selects due rows, advances next_due_at (with small jitter
so a post-downtime burst spreads out), and returns the claimed rows — all in one
round-trip. This makes double-enqueue impossible and is safe across concurrent
schedulers (SKIP LOCKED), though normally only one runs (advisory lock).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.subjects import MONITOR_POLL_ITEM

logger = logging.getLogger(__name__)

_CLAIM_SQL = text(
    """
    UPDATE monitor_items
    SET next_due_at = now()
        + make_interval(secs => interval_secs)
        + make_interval(secs => random() * least(interval_secs, 5)),
        updated_at = now()
    WHERE id IN (
        SELECT id FROM monitor_items
        WHERE enabled AND next_due_at <= now()
        ORDER BY next_due_at
        FOR UPDATE SKIP LOCKED
        LIMIT :batch
    )
    RETURNING id, target_type, target_id, host, check_type, params, interval_secs
    """
)


def claim_due_items(db: Session, batch: int = 200) -> list[dict]:
    rows = db.execute(_CLAIM_SQL, {"batch": batch}).mappings().all()
    db.commit()
    return [
        {
            "item_id": r["id"],
            "target_type": r["target_type"],
            "target_id": r["target_id"],
            "host": r["host"],
            "check_type": r["check_type"],
            "params": r["params"] or {},
            "interval_secs": r["interval_secs"],
        }
        for r in rows
    ]


async def enqueue_due(
    db: Session,
    publish: Callable[[str, dict], Awaitable[bool]],
    batch: int = 200,
) -> int:
    items = claim_due_items(db, batch=batch)
    enqueued = 0
    for item in items:
        ok = await publish(MONITOR_POLL_ITEM, item)
        if ok:
            enqueued += 1
        else:
            logger.warning("Failed to enqueue poll for item %s", item["item_id"])
    return enqueued
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_scheduler.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/services/monitoring/scheduler.py apps/backend/src/app/core/subjects.py apps/backend/tests/services/test_monitor_scheduler.py
git commit -m "feat(monitoring): atomic claim-and-enqueue scheduler"
```

---

### Task 6: NATS work-queue stream helper

**Files:**
- Modify: `apps/backend/src/app/core/nats_client.py` (add method to `NATSClient`)
- Test: covered by the integration test in Task 9 (JetStream needs a live NATS; no isolated unit test).

**Interfaces:**
- Produces: `async def ensure_monitor_poll_stream(self) -> None` on `NATSClient` — idempotently creates the `MONITOR_POLL` work-queue stream owning subject `mon.poll.item`.

- [ ] **Step 1: Implement the stream helper**

Add this method to the `NATSClient` class in `apps/backend/src/app/core/nats_client.py`, following the existing `_ensure_events_stream` pattern:

```python
    async def ensure_monitor_poll_stream(self) -> None:
        """Create the MONITOR_POLL work-queue stream if absent.

        WorkQueuePolicy: a message is deleted once acked, so this is a durable
        task queue (not an event log). Subject root is `mon.` to avoid overlap
        with CB_EVENTS' `monitor.>`.
        """
        if not self._connected or not self._js:
            return
        try:
            from nats.js.api import RetentionPolicy

            await self._js.add_stream(
                name="MONITOR_POLL",
                subjects=["mon.poll.item"],
                retention=RetentionPolicy.WORK_QUEUE,
                max_age=int(os.getenv("CB_MONITOR_POLL_MAX_AGE_S", "300")),
            )
            _logger.info("NATS MONITOR_POLL stream created")
        except Exception as exc:
            msg = str(exc).lower()
            if "already in use" in msg or "already exists" in msg or "name already in use" in msg:
                _logger.debug("NATS MONITOR_POLL stream already exists")
            else:
                _logger.warning("NATS MONITOR_POLL stream ensure failed: %s", exc)
```

(`os` is already imported at the top of `nats_client.py`.)

- [ ] **Step 2: Sanity check import**

Run: `cd apps/backend && poetry run python -c "from app.core.nats_client import NATSClient; assert hasattr(NATSClient, 'ensure_monitor_poll_stream')"`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add apps/backend/src/app/core/nats_client.py
git commit -m "feat(monitoring): MONITOR_POLL work-queue stream helper"
```

---

### Task 7: Poll worker (consume → collect → write)

**Files:**
- Create: `apps/backend/src/app/workers/monitor_poll_worker.py`
- Test: `apps/backend/tests/services/test_monitor_poll_worker.py`

**Interfaces:**
- Consumes: `COLLECTORS` from `collectors.py`; `write_samples` from `writer.py`.
- Produces:
  - `async def poll_one(item: dict) -> tuple[int, str, int | None, list[Sample], datetime]` — runs the collector for one claimed item dict (in a thread), returns a `SampleRow`. Never raises; unknown/failed check → `avail=0` sample.
  - `async def process_batch(items: list[dict], db_factory) -> int` — polls a batch concurrently, writes once, returns rows written.
  - `async def run_worker(shutdown_event: asyncio.Event | None = None) -> None` — the JetStream pull-consumer loop.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/services/test_monitor_poll_worker.py
import asyncio
from unittest.mock import patch

from app.db.models import TelemetryTimeseries
from app.services.monitoring.collectors import Sample
from app.workers.monitor_poll_worker import poll_one, process_batch


def test_poll_one_runs_collector():
    item = {"item_id": 5, "target_type": "ip", "target_id": None, "host": "10.0.0.5",
            "check_type": "icmp", "params": {"packet_count": 1}, "interval_secs": 60}
    with patch("app.workers.monitor_poll_worker.COLLECTORS",
               {"icmp": lambda host, params: [Sample("avail", 1.0)]}):
        row = asyncio.run(poll_one(item))
    item_id, entity_type, entity_id, samples, ts = row
    assert item_id == 5
    assert samples[0].metric == "avail"


def test_poll_one_unknown_check_type_is_down():
    item = {"item_id": 6, "target_type": "ip", "target_id": None, "host": "x",
            "check_type": "bogus", "params": {}, "interval_secs": 60}
    row = asyncio.run(poll_one(item))
    _, _, _, samples, _ = row
    assert samples[0].metric == "avail" and samples[0].value == 0.0
    assert samples[0].error_reason == "unknown_check_type"


def test_process_batch_writes_all(db_session):
    from app.db.session import SessionLocal

    items = [
        {"item_id": 10, "target_type": "ip", "target_id": None, "host": "a",
         "check_type": "icmp", "params": {}, "interval_secs": 60},
        {"item_id": 11, "target_type": "ip", "target_id": None, "host": "b",
         "check_type": "icmp", "params": {}, "interval_secs": 60},
    ]
    with patch("app.workers.monitor_poll_worker.COLLECTORS",
               {"icmp": lambda host, params: [Sample("avail", 1.0)]}):
        written = asyncio.run(process_batch(items, SessionLocal))
    assert written == 2
    assert db_session.query(TelemetryTimeseries).filter(
        TelemetryTimeseries.item_id.in_([10, 11])
    ).count() == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_poll_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: ... monitor_poll_worker`.

- [ ] **Step 3: Implement the worker**

Create `apps/backend/src/app/workers/monitor_poll_worker.py`:

```python
"""Monitor poll worker: JetStream consumer that runs collectors and writes samples.

Deliberately NOT an in-process asyncio task on the API loop (the discovery-scan
anti-pattern). Poll load lives here and scales by running more replicas.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from app.core.nats_client import nats_client
from app.services.monitoring.collectors import COLLECTORS, Sample
from app.services.monitoring.writer import SampleRow, write_samples

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-monitor-poll.healthy")
_MAX_PARALLEL = int(os.getenv("CB_MONITOR_POLL_PARALLEL", "50"))
_FETCH_BATCH = int(os.getenv("CB_MONITOR_POLL_FETCH", "50"))
_JS_STREAM = "MONITOR_POLL"
_JS_DURABLE = "monitor_pollers"
_sema = asyncio.Semaphore(_MAX_PARALLEL)


def _touch_healthy() -> None:
    try:
        _HEALTHY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HEALTHY_FILE.write_text(str(time.time()))
    except OSError:
        pass


async def poll_one(item: dict) -> SampleRow:
    """Run the collector for one item in a worker thread. Never raises."""
    ts = datetime.now(UTC)
    collector = COLLECTORS.get(item["check_type"])
    if collector is None:
        return (item["item_id"], item["target_type"], item["target_id"],
                [Sample("avail", 0.0, error_reason="unknown_check_type")], ts)
    try:
        async with _sema:
            samples = await asyncio.to_thread(collector, item["host"], item["params"])
    except Exception as exc:  # noqa: BLE001 — a probe crash is a down datum
        logger.debug("Collector crashed for item %s: %s", item["item_id"], exc)
        samples = [Sample("avail", 0.0, error_reason="collector_error")]
    return (item["item_id"], item["target_type"], item["target_id"], samples, ts)


async def process_batch(items: list[dict], db_factory: Callable[[], Any]) -> int:
    rows: list[SampleRow] = await asyncio.gather(*(poll_one(i) for i in items))
    db = db_factory()
    try:
        written = write_samples(db, list(rows))
        db.commit()
        return written
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def run_worker(shutdown_event: asyncio.Event | None = None) -> None:
    from app.db.session import SessionLocal

    backoff = 2
    while not nats_client.is_connected:
        await nats_client.connect()
        if not nats_client.is_connected:
            logger.warning("monitor-poll: waiting for NATS (%ds)", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    await nats_client.ensure_monitor_poll_stream()
    js = nats_client._nc.jetstream()
    psub = await js.pull_subscribe("mon.poll.item", durable=_JS_DURABLE, stream=_JS_STREAM)
    logger.info("monitor-poll worker subscribed (durable=%s)", _JS_DURABLE)
    _touch_healthy()

    while not (shutdown_event and shutdown_event.is_set()):
        try:
            msgs = await psub.fetch(_FETCH_BATCH, timeout=1.0)
        except Exception as exc:  # noqa: BLE001
            if "Timeout" not in type(exc).__name__:
                logger.warning("monitor-poll fetch error: %s", exc)
            _touch_healthy()
            continue

        items: list[dict] = []
        for m in msgs:
            try:
                items.append(json.loads(m.data.decode()))
            except json.JSONDecodeError:
                logger.warning("monitor-poll: bad message, dropping")

        if items:
            try:
                await process_batch(items, SessionLocal)
            except Exception as exc:  # noqa: BLE001
                logger.error("monitor-poll batch failed: %s", exc, exc_info=True)
                for m in msgs:
                    await _safe_nak(m)
                continue

        for m in msgs:
            await _safe_ack(m)
        _touch_healthy()

    logger.info("monitor-poll worker stopped")


async def _safe_ack(msg: Any) -> None:
    try:
        await msg.ack()
    except Exception:
        pass


async def _safe_nak(msg: Any) -> None:
    try:
        await msg.nak()
    except Exception:
        pass


if __name__ == "__main__":
    from app.workers import run_with_graceful_shutdown

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_with_graceful_shutdown(run_worker))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_poll_worker.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/workers/monitor_poll_worker.py apps/backend/tests/services/test_monitor_poll_worker.py
git commit -m "feat(monitoring): JetStream poll worker (collect + batched write)"
```

---

### Task 8: Scheduler worker (advisory-lock singleton loop)

**Files:**
- Create: `apps/backend/src/app/workers/monitor_scheduler.py`
- Test: `apps/backend/tests/services/test_monitor_scheduler_worker.py`

**Interfaces:**
- Consumes: `enqueue_due` from `scheduler.py`; `try_advisory_lock`/`advisory_unlock` from `core/job_lock.py`; `nats_client`.
- Produces:
  - `async def tick(db_factory, publish) -> int` — one scheduler iteration; returns items enqueued.
  - `async def run_worker(shutdown_event: asyncio.Event | None = None) -> None` — the singleton loop.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/services/test_monitor_scheduler_worker.py
import asyncio
from datetime import UTC, datetime, timedelta

from app.db.models import MonitorItem
from app.db.session import SessionLocal
from app.workers.monitor_scheduler import tick


def test_tick_publishes_due_items(db_session):
    item = MonitorItem(
        target_type="ip", target_id=None, host="10.0.0.9", check_type="icmp",
        params={}, interval_secs=60, enabled=True,
        next_due_at=datetime.now(UTC) - timedelta(seconds=5),
    )
    db_session.add(item)
    db_session.commit()

    published: list[tuple[str, dict]] = []

    async def fake_publish(subject, payload):
        published.append((subject, payload))
        return True

    n = asyncio.run(tick(SessionLocal, fake_publish))
    assert n == 1
    assert published[0][0] == "mon.poll.item"
    assert published[0][1]["host"] == "10.0.0.9"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_scheduler_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: ... monitor_scheduler`.

- [ ] **Step 3: Implement the scheduler worker**

Create `apps/backend/src/app/workers/monitor_scheduler.py`:

```python
"""Monitor scheduler worker: the single active clock for the polling engine.

Guarded by a Postgres advisory lock so exactly one instance enqueues, even with
multiple replicas. Each tick atomically claims due items (advancing their
next_due_at) and publishes one poll message per item. All scheduling state is in
the DB, so a restart resumes cleanly with no wedged state.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.core.job_lock import _lock_id_for, advisory_unlock, try_advisory_lock
from app.core.nats_client import nats_client
from app.services.monitoring.scheduler import enqueue_due

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-monitor-scheduler.healthy")
_TICK_S = float(os.getenv("CB_MONITOR_SCHED_TICK_S", "1.0"))
_BATCH = int(os.getenv("CB_MONITOR_SCHED_BATCH", "200"))
_LOCK_NAME = "monitor_scheduler"


def _touch_healthy() -> None:
    try:
        _HEALTHY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HEALTHY_FILE.write_text(str(time.time()))
    except OSError:
        pass


async def tick(
    db_factory: Callable[[], Any],
    publish: Callable[[str, dict], Awaitable[bool]],
) -> int:
    db = db_factory()
    try:
        return await enqueue_due(db, publish, batch=_BATCH)
    finally:
        db.close()


async def run_worker(shutdown_event: asyncio.Event | None = None) -> None:
    from app.db.session import SessionLocal

    backoff = 2
    while not nats_client.is_connected:
        await nats_client.connect()
        if not nats_client.is_connected:
            logger.warning("monitor-scheduler: waiting for NATS (%ds)", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
    await nats_client.ensure_monitor_poll_stream()

    lock_id = _lock_id_for(_LOCK_NAME)
    lock_db = SessionLocal()
    have_lock = try_advisory_lock(lock_db, lock_id)
    if not have_lock:
        logger.info("monitor-scheduler: another instance holds the lock; standing by")

    logger.info("monitor-scheduler started (active=%s, tick=%ss)", have_lock, _TICK_S)
    _touch_healthy()
    try:
        while not (shutdown_event and shutdown_event.is_set()):
            if not have_lock:
                have_lock = try_advisory_lock(lock_db, lock_id)
            if have_lock:
                try:
                    await tick(SessionLocal, nats_client.js_publish)
                except Exception as exc:  # noqa: BLE001
                    logger.error("monitor-scheduler tick failed: %s", exc, exc_info=True)
            _touch_healthy()
            try:
                if shutdown_event:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=_TICK_S)
                else:
                    await asyncio.sleep(_TICK_S)
            except TimeoutError:
                pass
    finally:
        if have_lock:
            advisory_unlock(lock_db, lock_id)
        lock_db.close()
    logger.info("monitor-scheduler worker stopped")


if __name__ == "__main__":
    from app.workers import run_with_graceful_shutdown

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_with_graceful_shutdown(run_worker))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_scheduler_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/workers/monitor_scheduler.py apps/backend/tests/services/test_monitor_scheduler_worker.py
git commit -m "feat(monitoring): singleton scheduler worker loop"
```

---

### Task 9: Wire workers into entrypoint + supervisord; retire old monitor job

**Files:**
- Modify: `apps/backend/src/app/workers/main.py`
- Modify: `docker/supervisord.mono.conf`
- Modify: `apps/backend/src/app/main.py:900-913`
- Test: `apps/backend/tests/services/test_worker_dispatch.py`

**Interfaces:**
- Consumes: `monitor_scheduler.run_worker`, `monitor_poll_worker.run_worker`.
- Produces: worker `--type` values `4`→`monitor_scheduler`, `5`,`6`→`monitor_poll`.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/services/test_worker_dispatch.py
from app.workers.main import _TYPE_MAP


def test_monitor_worker_types_registered():
    assert _TYPE_MAP["4"] == "monitor_scheduler"
    assert _TYPE_MAP["5"] == "monitor_poll"
    assert _TYPE_MAP["6"] == "monitor_poll"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && poetry run pytest tests/services/test_worker_dispatch.py -v`
Expected: FAIL with `KeyError: '4'`.

- [ ] **Step 3: Extend the worker entrypoint**

In `apps/backend/src/app/workers/main.py`, extend `_TYPE_MAP` and add dispatch branches:

```python
_TYPE_MAP = {
    "0": "discovery",
    "1": "webhook",
    "2": "notification",
    "3": "telemetry",
    "4": "monitor_scheduler",
    "5": "monitor_poll",
    "6": "monitor_poll",
}
```

Add two runner functions alongside the existing `_run_*`:

```python
async def _run_monitor_scheduler() -> None:
    from app.workers import monitor_scheduler

    await run_with_graceful_shutdown(monitor_scheduler.run_worker)


async def _run_monitor_poll() -> None:
    from app.workers import monitor_poll_worker

    await run_with_graceful_shutdown(monitor_poll_worker.run_worker)
```

Extend `_dispatch`:

```python
    elif kind == "monitor_scheduler":
        await _run_monitor_scheduler()
    elif kind == "monitor_poll":
        await _run_monitor_poll()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && poetry run pytest tests/services/test_worker_dispatch.py -v`
Expected: PASS.

- [ ] **Step 5: Update supervisord worker count**

In `docker/supervisord.mono.conf`, change the `[program:workers]` `numprocs` from `4` to `7` (indices 0–6: discovery, webhook, notification, telemetry, monitor_scheduler, and two monitor_poll workers). Locate:

```
numprocs=4
```

and change to:

```
numprocs=7
```

- [ ] **Step 6: Retire the old sequential monitor job**

In `apps/backend/src/app/main.py`, delete the block at lines 900–913 (the `run_all_monitors_job` `IntervalTrigger` registration), replacing it with a one-line marker comment:

```python
    # Uptime monitoring is handled by the item-based polling engine
    # (workers: monitor_scheduler + monitor_poll). The legacy run_all_monitors_job
    # APScheduler loop was retired in the polling-engine migration.
```

- [ ] **Step 7: Verify the app still imports**

Run: `cd apps/backend && poetry run python -c "import app.main"`
Expected: no error.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/src/app/workers/main.py docker/supervisord.mono.conf apps/backend/src/app/main.py apps/backend/tests/services/test_worker_dispatch.py
git commit -m "feat(monitoring): register poll workers; retire legacy uptime monitor job"
```

---

### Task 10: Data migration — `hardware_monitors` → `monitor_items`

**Files:**
- Create: `apps/backend/migrations/versions/0083_migrate_hardware_monitors.py`
- Test: `apps/backend/tests/services/test_monitor_backfill.py`

**Interfaces:**
- Consumes: existing `hardware_monitors` rows and `hardware.ip_address`.
- Produces: `def backfill_monitor_items(db: Session) -> int` in a small helper module `app/services/monitoring/backfill.py`, returning items created. The migration calls it; the test calls it directly.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/services/test_monitor_backfill.py
from app.db.models import Hardware, HardwareMonitor, MonitorItem
from app.services.monitoring.backfill import backfill_monitor_items


def test_backfill_creates_icmp_item_per_enabled_monitor(db_session):
    hw = Hardware(name="router", ip_address="10.0.0.1")
    db_session.add(hw)
    db_session.commit()
    db_session.add(HardwareMonitor(
        hardware_id=hw.id, enabled=True, interval_secs=30,
        probe_methods=["icmp", "tcp"], last_status="up",
        created_at="2026-07-14T00:00:00Z", updated_at="2026-07-14T00:00:00Z",
    ))
    db_session.commit()

    created = backfill_monitor_items(db_session)
    db_session.commit()
    assert created >= 1

    items = db_session.query(MonitorItem).filter(MonitorItem.target_id == hw.id).all()
    kinds = {i.check_type for i in items}
    assert "icmp" in kinds
    assert all(i.host == "10.0.0.1" and i.interval_secs == 30 for i in items)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_backfill.py -v`
Expected: FAIL with `ModuleNotFoundError: ... backfill`.

- [ ] **Step 3: Implement the backfill helper**

Create `apps/backend/src/app/services/monitoring/backfill.py`:

```python
"""One-time backfill: convert enabled HardwareMonitor rows into MonitorItems."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import Hardware, HardwareMonitor, MonitorItem


def backfill_monitor_items(db: Session) -> int:
    created = 0
    monitors = db.query(HardwareMonitor).filter(HardwareMonitor.enabled.is_(True)).all()
    for mon in monitors:
        hw = db.get(Hardware, mon.hardware_id)
        if not hw or not hw.ip_address:
            continue
        methods = mon.probe_methods or ["icmp"]
        now = datetime.now(UTC)
        for method in methods:
            if method not in ("icmp", "tcp", "http"):
                continue
            exists = (
                db.query(MonitorItem)
                .filter(
                    MonitorItem.target_type == "hardware",
                    MonitorItem.target_id == hw.id,
                    MonitorItem.check_type == method,
                )
                .first()
            )
            if exists:
                continue
            db.add(
                MonitorItem(
                    target_type="hardware",
                    target_id=hw.id,
                    host=hw.ip_address,
                    check_type=method,
                    params={"packet_count": 5} if method == "icmp" else {},
                    interval_secs=mon.interval_secs or 60,
                    enabled=True,
                    next_due_at=now,
                )
            )
            created += 1
    return created
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_backfill.py -v`
Expected: PASS.

- [ ] **Step 5: Write the migration that invokes the backfill**

```python
# apps/backend/migrations/versions/0083_migrate_hardware_monitors.py
"""Backfill monitor_items from existing hardware_monitors."""

from __future__ import annotations

from alembic import op
from sqlalchemy.orm import Session

revision = "0083_migrate_hardware_monitors"
down_revision = "0082_telemetry_item_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.services.monitoring.backfill import backfill_monitor_items

    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        n = backfill_monitor_items(session)
        session.commit()
        print(f"[0083] backfilled {n} monitor_items from hardware_monitors")
    finally:
        session.close()


def downgrade() -> None:
    # Backfilled rows are left in place; monitor_items itself is dropped by 0081 downgrade.
    pass
```

- [ ] **Step 6: Verify migration runs**

Run: `cd apps/backend && poetry run alembic upgrade head`
Expected: prints the backfill count, no error.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/src/app/services/monitoring/backfill.py apps/backend/migrations/versions/0083_migrate_hardware_monitors.py apps/backend/tests/services/test_monitor_backfill.py
git commit -m "feat(monitoring): backfill monitor_items from hardware_monitors"
```

---

### Task 11: End-to-end integration test

**Files:**
- Create: `apps/backend/tests/integration/test_monitor_engine_e2e.py`

**Interfaces:**
- Consumes: `claim_due_items`, `process_batch`, `write_samples`, `MonitorItem`, `TelemetryTimeseries`. Exercises the full loop without live NATS by calling `claim_due_items` → `process_batch` directly (the scheduler↔worker contract is the `item` dict, verified in Tasks 5/7).

- [ ] **Step 1: Write the end-to-end test**

```python
# apps/backend/tests/integration/test_monitor_engine_e2e.py
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.db.models import MonitorItem, TelemetryTimeseries
from app.db.session import SessionLocal
from app.services.monitoring.collectors import Sample
from app.services.monitoring.scheduler import claim_due_items
from app.workers.monitor_poll_worker import process_batch


def _due_item(db, host, offset_s=-1):
    it = MonitorItem(
        target_type="ip", target_id=None, host=host, check_type="icmp",
        params={"packet_count": 3}, interval_secs=60, enabled=True,
        next_due_at=datetime.now(UTC) + timedelta(seconds=offset_s),
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def test_claim_then_poll_writes_samples(db_session):
    item = _due_item(db_session, "10.0.0.5")
    claimed = claim_due_items(db_session, batch=50)
    assert [c["item_id"] for c in claimed] == [item.id]

    with patch("app.workers.monitor_poll_worker.COLLECTORS",
               {"icmp": lambda host, params: [Sample("avail", 1.0), Sample("packet_loss_pct", 0.0)]}):
        written = asyncio.run(process_batch(claimed, SessionLocal))
    assert written == 2

    stored = db_session.query(TelemetryTimeseries).filter(
        TelemetryTimeseries.item_id == item.id
    ).all()
    assert {r.metric for r in stored} == {"avail", "packet_loss_pct"}


def test_restart_self_heals_no_wedged_items(db_session):
    """After a claim, a 'crash' before poll leaves the item simply due again later —
    never stuck. Claiming again immediately returns nothing (next_due advanced)."""
    item = _due_item(db_session, "10.0.0.6")
    claim_due_items(db_session, batch=50)  # simulate scheduler enqueue, then 'crash'
    # No poll happened. Item is not wedged in a 'running' state — it's just scheduled ahead.
    assert claim_due_items(db_session, batch=50) == []
    refreshed = db_session.get(MonitorItem, item.id)
    assert refreshed.next_due_at > datetime.now(UTC)


def test_duplicate_delivery_is_tolerated(db_session):
    item = _due_item(db_session, "10.0.0.7")
    claimed = claim_due_items(db_session, batch=50)
    with patch("app.workers.monitor_poll_worker.COLLECTORS",
               {"icmp": lambda host, params: [Sample("avail", 1.0)]}):
        asyncio.run(process_batch(claimed, SessionLocal))
        asyncio.run(process_batch(claimed, SessionLocal))  # redelivery
    # Two near-duplicate samples — harmless, no crash, both present.
    n = db_session.query(TelemetryTimeseries).filter(
        TelemetryTimeseries.item_id == item.id, TelemetryTimeseries.metric == "avail"
    ).count()
    assert n == 2
```

- [ ] **Step 2: Run the integration test**

Run: `cd apps/backend && poetry run pytest tests/integration/test_monitor_engine_e2e.py -v`
Expected: PASS (3 tests).

- [ ] **Step 3: Run the full monitoring suite**

Run: `cd apps/backend && poetry run pytest tests/services/test_monitor_*.py tests/integration/test_monitor_engine_e2e.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/tests/integration/test_monitor_engine_e2e.py
git commit -m "test(monitoring): end-to-end claim→poll→write with self-heal and dedup"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Item-based model → Task 1. `item_id` samples dimension → Task 2. Collectors (ICMP loss/jitter, TCP, HTTP) → Task 3. Batched writer → Task 4 (per-fetch-batch bulk insert in Task 7). Scheduler (SKIP LOCKED claim + advance next_due) → Task 5. Work-queue stream (`mon.` namespace) → Task 6. Poll workers (JetStream, horizontal) → Task 7. Singleton scheduler (advisory lock) + overdue jitter → Task 8. Worker wiring + retire `run_all_monitors_job` → Task 9. Migration from `HardwareMonitor` → Task 10. Reliability guarantees (self-heal, loud failure, no double-schedule, dedup tolerance) → verified in Tasks 5/7/11.
- Deferred per spec (not in this plan): SNMP bandwidth, triggers/alerting, history UI, templates, `IntegrationMonitor` unification.

**Placeholder scan:** none — every code step contains complete, runnable code.

**Type consistency:** `Sample(metric, value, error_reason)` consistent across collectors/writer/worker. `SampleRow = (item_id, entity_type, entity_id, samples, ts)` defined in Task 4, produced by `poll_one` (Task 7), consumed by `write_samples` (Task 4) and `process_batch` (Task 7). Claim dict keys (`item_id, target_type, target_id, host, check_type, params, interval_secs`) identical in scheduler (Task 5), worker (Task 7), and e2e (Task 11). Subject `mon.poll.item` consistent across Tasks 5/6/7/8.

**Note for implementer:** Tasks 6, 8's `run_worker`, and the supervisord change require a live NATS to exercise fully; their unit tests cover the pure logic (`tick`, `poll_one`, `process_batch`, `claim_due_items`). Validate the JetStream path manually with `make up` before merging.
```
