# Proxmox as Priority Uptime Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For monitors on Proxmox-linked targets (`Hardware.proxmox_node_name` or `ComputeUnit.proxmox_vmid`), a fresh, disagreeing Proxmox status overrides the raw ICMP/TCP check result — including the stored `avail` sample that feeds uptime percentages — so a transient network blip against a Proxmox-linked target no longer reports false "down" while Proxmox itself confirms the entity is running.

**Architecture:** A new pure function `apply_proxmox_overrides()` batch-fetches the `Hardware`/`ComputeUnit` rows referenced by a poll batch and rewrites any outcome where a fresh Proxmox opinion disagrees with the raw check. It runs once per batch inside `monitor_poll_worker.process_batch()`, after collectors finish and before samples are written / state transitions applied, so everything downstream (rollups, percentages, notifications) sees the corrected result with zero further changes.

**Tech Stack:** Python, SQLAlchemy ORM (sync `Session`), pytest + real Postgres (testcontainers), Alembic migrations.

Spec: `specs/2026-07-26-proxmox-uptime-priority-design.md`

## Global Constraints

- Freshness window is a flat 5 minutes for both `Hardware` and `ComputeUnit`, hardcoded (not user-configurable).
- Collectors (`collectors/net.py` etc.) and the Proxmox client/polling schedule are out of scope — untouched.
- No retroactive correction of historical samples/events.
- A defect in the new override code must degrade to today's raw-check behavior for that item, never fail the batch (mirrors `poll_one()`'s "never raises" philosophy).
- Tests use real Postgres via the existing `db_session` / `factories` fixtures — no mocking the ORM.
- Follow this repo's fresh-install migration convention: any new column must be added to `_EXCLUDED_COLUMNS` in `apps/backend/migrations/versions/0001_init.py` so a fresh install doesn't create it before its own migration runs.

---

### Task 1: Add `telemetry_last_polled` to `ComputeUnit`

**Files:**
- Modify: `apps/backend/src/app/db/models.py` (`ComputeUnit` class, ~line 384-421)
- Modify: `apps/backend/migrations/versions/0001_init.py` (`_EXCLUDED_COLUMNS["compute_units"]`, ~line 77-83)
- Create: `apps/backend/migrations/versions/0088_compute_unit_telemetry_last_polled.py`

**Interfaces:**
- Produces: `ComputeUnit.telemetry_last_polled: datetime | None` — read by Task 3's `apply_proxmox_overrides()` and written by Task 2.

- [ ] **Step 1: Add the column to the model**

In `apps/backend/src/app/db/models.py`, inside `class ComputeUnit`, add right after the existing `proxmox_status` column (~line 413):

```python
    proxmox_status: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    telemetry_last_polled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

This mirrors `Hardware.telemetry_last_polled` (models.py:115) exactly.

- [ ] **Step 2: Write the migration**

Create `apps/backend/migrations/versions/0088_compute_unit_telemetry_last_polled.py`:

```python
"""Add telemetry_last_polled column to compute_units table.

Revision ID: 0088_compute_unit_telemetry_last_polled
Revises: 0087_monitor_daily_stats
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0088_compute_unit_telemetry_last_polled"
down_revision = "0087_monitor_daily_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("compute_units")}
    if "telemetry_last_polled" not in cols:
        op.add_column(
            "compute_units",
            sa.Column("telemetry_last_polled", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("compute_units", "telemetry_last_polled")
```

- [ ] **Step 3: Update the fresh-install exclusion list**

In `apps/backend/migrations/versions/0001_init.py`, add `"telemetry_last_polled"` to the `compute_units` entry in `_EXCLUDED_COLUMNS` (~line 77-83):

```python
    "compute_units": {
        "integration_config_id",
        "proxmox_config",
        "proxmox_status",
        "proxmox_type",
        "proxmox_vmid",
        "telemetry_last_polled",
    },
```

Without this, `0001_init`'s reflection-based bootstrap would try to create the column on a fresh install before migration 0088 runs, causing a duplicate-column error.

- [ ] **Step 4: Verify migration runs cleanly**

Run (from `apps/backend/`):
```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```
Expected: no errors; `compute_units.telemetry_last_polled` exists after the final upgrade.

If Docker Compose / a live Postgres isn't available in this environment, use whatever alembic upgrade/downgrade substitute this repo's test harness already relies on (e.g. running it against the same Postgres the pytest suite starts) — do not skip this check silently.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/db/models.py apps/backend/migrations/versions/0001_init.py apps/backend/migrations/versions/0088_compute_unit_telemetry_last_polled.py
git commit -m "feat(monitors): add telemetry_last_polled to compute_units"
```

---

### Task 2: Set `telemetry_last_polled` in the Proxmox VM-poll path

**Files:**
- Modify: `apps/backend/src/app/services/proxmox_telemetry.py` (`poll_vm_telemetry`, ~line 499-500)
- Modify: `apps/backend/tests/conftest.py` (add `async_db_session` fixture)
- Create: `apps/backend/tests/services/test_proxmox_telemetry_vm.py`

**Interfaces:**
- Consumes: `ComputeUnit.telemetry_last_polled` (Task 1).
- Produces: nothing new downstream — this task only ensures the column set in Task 1 gets populated by the existing VM-poll loop, so Task 3's override function has fresh data to read.

**Context:** `poll_vm_telemetry` uses `AsyncSession` and genuinely `await`s DB calls (`await db.execute(...)`), unlike the sync `Session` used elsewhere in the poll worker. The existing `db_session` fixture in `conftest.py` is a **sync** `Session` and cannot be awaited into. There is currently no async DB fixture in this test suite, so this task adds one, mirroring the existing `db_session` fixture's SAVEPOINT-based isolation pattern exactly but built on `app.db.async_session.async_engine`.

- [ ] **Step 1: Add the `async_db_session` fixture**

In `apps/backend/tests/conftest.py`, add after the existing `db_session` fixture (~line 130):

```python
@pytest_asyncio.fixture
async def async_db_session(setup_db):
    """Per-test ASYNC DB session (SAVEPOINT-based isolation), mirroring db_session
    above. Needed for code paths that genuinely `await` AsyncSession calls (e.g.
    proxmox_telemetry.py) rather than the sync ORM Session used everywhere else.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.async_session import async_engine

    async with async_engine.connect() as connection:
        outer_tx = await connection.begin()
        session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await outer_tx.rollback()
```

- [ ] **Step 2: Write the failing test**

Create `apps/backend/tests/services/test_proxmox_telemetry_vm.py`:

```python
"""Tests for the Proxmox VM-poll path setting telemetry_last_polled."""

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_poll_vm_telemetry_sets_telemetry_last_polled(async_db_session):
    from app.db.models import ComputeUnit, Hardware, IntegrationConfig
    from app.services.proxmox_telemetry import poll_vm_telemetry

    config = IntegrationConfig(
        type="proxmox", name="pve", config_url="https://pve.local:8006", auto_sync=True
    )
    async_db_session.add(config)
    await async_db_session.flush()

    hw = Hardware(name="pve-node-1", proxmox_node_name="pve1", integration_config_id=config.id)
    async_db_session.add(hw)
    await async_db_session.flush()

    cu = ComputeUnit(
        name="vm-100",
        kind="vm",
        hardware_id=hw.id,
        proxmox_vmid=100,
        proxmox_type="qemu",
        integration_config_id=config.id,
    )
    async_db_session.add(cu)
    await async_db_session.flush()
    assert cu.telemetry_last_polled is None

    fake_client = AsyncMock()
    fake_client.get_vm_status.return_value = {
        "status": "running",
        "cpu": 0.1,
        "maxmem": 1024,
        "mem": 512,
        "netin": 0,
        "netout": 0,
        "maxdisk": 0,
        "disk": 0,
    }
    with (
        patch(
            "app.services.proxmox_telemetry._get_client_async",
            AsyncMock(return_value=fake_client),
        ),
        patch("app.services.proxmox_telemetry._publish", AsyncMock()),
        patch("app.services.telemetry_cache.publish_telemetry", AsyncMock()),
    ):
        await poll_vm_telemetry(async_db_session)

    await async_db_session.refresh(cu)
    assert cu.status == "active"
    assert cu.telemetry_last_polled is not None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest apps/backend/tests/services/test_proxmox_telemetry_vm.py -v`
Expected: FAIL — `assert cu.telemetry_last_polled is not None` fails (attribute doesn't exist yet / stays `None`).

- [ ] **Step 4: Set the column in the VM-poll path**

In `apps/backend/src/app/services/proxmox_telemetry.py`, in `poll_vm_telemetry`, right after the existing status assignment (~line 500):

```python
                    cu.proxmox_status = pve_status
                    cu.status = "active" if status.get("status") == "running" else "inactive"
                    cu.telemetry_last_polled = now
```

(`now` is already computed earlier in the function via `now = utcnow()`, ~line 469.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest apps/backend/tests/services/test_proxmox_telemetry_vm.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/services/proxmox_telemetry.py apps/backend/tests/conftest.py apps/backend/tests/services/test_proxmox_telemetry_vm.py
git commit -m "feat(monitors): stamp telemetry_last_polled on Proxmox VM poll"
```

---

### Task 3: `apply_proxmox_overrides()` — the override function

**Files:**
- Create: `apps/backend/src/app/services/monitoring/proxmox_override.py`
- Create: `apps/backend/tests/services/test_proxmox_override.py`

**Interfaces:**
- Consumes: `Hardware.proxmox_node_name`, `Hardware.telemetry_last_polled` (existing); `ComputeUnit.proxmox_vmid`, `ComputeUnit.status`, `ComputeUnit.telemetry_last_polled` (Task 1); `Sample` (`metric: str`, `value: float`, `error_reason: str | None`) and `SampleRow = tuple[int, str | None, int | None, list[Sample], datetime]` from `app.services.monitoring.writer` / `app.services.monitoring.collectors`.
- Produces: `apply_proxmox_overrides(db: Session, items: list[dict], outcomes: list[tuple[SampleRow, bool, str]]) -> list[tuple[SampleRow, bool, str]]` — consumed by Task 4.

Each `item` dict has at least `item_id: int`, `target_type: str | None`, `target_id: int | None` (same shape `poll_one()` already consumes in `monitor_poll_worker.py`).

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/services/test_proxmox_override.py`:

```python
"""Tests for Proxmox priority override of raw ICMP/TCP check outcomes."""

from datetime import UTC, datetime, timedelta

from app.core.time import utcnow
from app.services.monitoring.collectors import Sample
from app.services.monitoring.proxmox_override import apply_proxmox_overrides


def _outcome(item_id, target_type, target_id, up, avail_value, msg="", extra_samples=None):
    samples = [Sample("avail", avail_value), *(extra_samples or [])]
    row = (item_id, target_type, target_id, samples, datetime.now(UTC))
    return row, up, msg


def test_fresh_hardware_overrides_false_down(db_session, factories):
    hw = factories.hardware(proxmox_node_name="pve1", telemetry_last_polled=utcnow())
    latency = Sample("latency_ms", 1234.0)
    outcome = _outcome(1, "hardware", hw.id, False, 0.0, msg="100% packet loss", extra_samples=[latency])
    items = [{"item_id": 1, "target_type": "hardware", "target_id": hw.id}]

    [(new_row, new_up, new_msg)] = apply_proxmox_overrides(db_session, items, [outcome])

    assert new_up is True
    samples_out = new_row[3]
    assert samples_out[0].metric == "avail" and samples_out[0].value == 1.0
    assert samples_out[1] is latency  # other samples untouched, same object
    assert "overridden" in new_msg and "node running" in new_msg


def test_stale_hardware_passes_through_unchanged(db_session, factories):
    stale = utcnow() - timedelta(minutes=10)
    hw = factories.hardware(proxmox_node_name="pve1", telemetry_last_polled=stale)
    outcome = _outcome(2, "hardware", hw.id, False, 0.0)
    items = [{"item_id": 2, "target_type": "hardware", "target_id": hw.id}]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome  # untouched: same tuple object, not rebuilt


def test_hardware_without_proxmox_link_passes_through_unchanged(db_session, factories):
    hw = factories.hardware()
    outcome = _outcome(3, "hardware", hw.id, False, 0.0)
    items = [{"item_id": 3, "target_type": "hardware", "target_id": hw.id}]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome


def test_fresh_compute_unit_overrides_false_up(db_session, factories):
    hw = factories.hardware(proxmox_node_name="pve1")
    cu = factories.compute_unit(
        hardware_id=hw.id,
        proxmox_vmid=100,
        status="inactive",
        telemetry_last_polled=utcnow(),
    )
    outcome = _outcome(4, "compute_unit", cu.id, True, 1.0, msg="tcp connect ok")
    items = [{"item_id": 4, "target_type": "compute_unit", "target_id": cu.id}]

    [(new_row, new_up, new_msg)] = apply_proxmox_overrides(db_session, items, [outcome])

    assert new_up is False
    assert new_row[3][0].value == 0.0
    assert "overridden" in new_msg and "stopped" in new_msg


def test_agreement_passes_through_unchanged(db_session, factories):
    hw = factories.hardware(proxmox_node_name="pve1", telemetry_last_polled=utcnow())
    outcome = _outcome(5, "hardware", hw.id, True, 1.0)
    items = [{"item_id": 5, "target_type": "hardware", "target_id": hw.id}]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome


def test_missing_target_row_passes_through_unchanged(db_session):
    outcome = _outcome(6, "hardware", 999999, False, 0.0)
    items = [{"item_id": 6, "target_type": "hardware", "target_id": 999999}]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome


def test_standalone_monitor_passes_through_unchanged(db_session):
    outcome = _outcome(7, None, None, False, 0.0)
    items = [{"item_id": 7, "target_type": None, "target_id": None}]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/backend/tests/services/test_proxmox_override.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.monitoring.proxmox_override'`.

- [ ] **Step 3: Implement `apply_proxmox_overrides`**

Create `apps/backend/src/app/services/monitoring/proxmox_override.py`:

```python
"""Proxmox priority override: a fresh Proxmox opinion wins over a raw ICMP/TCP
check for monitors on Proxmox-linked targets (Hardware nodes, VMs/containers).

Runs once per batch in monitor_poll_worker.process_batch(), after collectors
have produced outcomes and before write_samples()/apply_result() run — so both
the stored avail sample and the state-machine transition see the corrected
result. Never raises: a defect here degrades a single item back to its raw,
un-overridden outcome rather than failing the batch.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import ComputeUnit, Hardware
from app.services.monitoring.collectors import Sample
from app.services.monitoring.writer import SampleRow

logger = logging.getLogger(__name__)

_FRESHNESS_WINDOW = timedelta(minutes=5)

Outcome = tuple[SampleRow, bool, str]


def apply_proxmox_overrides(
    db: Session, items: list[dict], outcomes: list[Outcome]
) -> list[Outcome]:
    targets_by_item = {item["item_id"]: item for item in items}
    cutoff = utcnow() - _FRESHNESS_WINDOW

    hardware_ids = {i["target_id"] for i in items if i["target_type"] == "hardware"}
    compute_ids = {i["target_id"] for i in items if i["target_type"] == "compute_unit"}
    hw_map = (
        {hw.id: hw for hw in db.query(Hardware).filter(Hardware.id.in_(hardware_ids)).all()}
        if hardware_ids
        else {}
    )
    cu_map = (
        {cu.id: cu for cu in db.query(ComputeUnit).filter(ComputeUnit.id.in_(compute_ids)).all()}
        if compute_ids
        else {}
    )

    result: list[Outcome] = []
    for outcome in outcomes:
        try:
            result.append(_apply_one(outcome, targets_by_item, hw_map, cu_map, cutoff))
        except Exception as exc:  # noqa: BLE001 — a defect here degrades to the raw outcome
            logger.warning("Proxmox override crashed, using raw outcome: %s", exc)
            result.append(outcome)
    return result


def _apply_one(
    outcome: Outcome,
    targets_by_item: dict[int, dict],
    hw_map: dict[int, Hardware],
    cu_map: dict[int, ComputeUnit],
    cutoff: datetime,
) -> Outcome:
    row, up, msg = outcome
    item_id, target_type, target_id, samples, ts = row
    item = targets_by_item.get(item_id)
    if item is None:
        return outcome

    proxmox_up, label = _proxmox_opinion(item, hw_map, cu_map, cutoff)
    if proxmox_up is None or proxmox_up == up:
        return outcome

    new_samples = [
        Sample("avail", 1.0 if proxmox_up else 0.0) if s.metric == "avail" else s
        for s in samples
    ]
    state = "running" if proxmox_up else "stopped"
    new_msg = f"{msg} (overridden: Proxmox reports {label} {state})".strip()
    new_row = (item_id, target_type, target_id, new_samples, ts)
    return new_row, proxmox_up, new_msg


def _proxmox_opinion(
    item: dict,
    hw_map: dict[int, Hardware],
    cu_map: dict[int, ComputeUnit],
    cutoff: datetime,
) -> tuple[bool | None, str]:
    target_type = item.get("target_type")
    target_id = item.get("target_id")

    if target_type == "hardware":
        hw = hw_map.get(target_id)
        is_fresh = (
            hw is not None
            and hw.proxmox_node_name
            and hw.telemetry_last_polled is not None
            and hw.telemetry_last_polled >= cutoff
        )
        # A successful node poll IS the reachability signal (proxmox_telemetry.py
        # only updates telemetry_last_polled when the node poll succeeds), so a
        # fresh timestamp always means "up". There's no fresh-but-down state for
        # a node — a genuinely down node just looks stale, same as "no opinion".
        return (True, "node") if is_fresh else (None, "node")

    if target_type == "compute_unit":
        cu = cu_map.get(target_id)
        is_fresh = (
            cu is not None
            and cu.proxmox_vmid is not None
            and cu.telemetry_last_polled is not None
            and cu.telemetry_last_polled >= cutoff
        )
        if not is_fresh:
            return None, ""
        label = "VM" if cu.kind == "vm" else "container"
        return cu.status == "active", label

    return None, ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/backend/tests/services/test_proxmox_override.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/monitoring/proxmox_override.py apps/backend/tests/services/test_proxmox_override.py
git commit -m "feat(monitors): add apply_proxmox_overrides for priority Proxmox signal"
```

---

### Task 4: Wire the override into `monitor_poll_worker.process_batch`

**Files:**
- Modify: `apps/backend/src/app/workers/monitor_poll_worker.py` (imports + `process_batch`, ~line 26, 75-95)
- Modify: `apps/backend/tests/services/test_monitor_poll_worker.py`

**Interfaces:**
- Consumes: `apply_proxmox_overrides(db, items, outcomes)` from Task 3.

- [ ] **Step 1: Write the failing wiring test**

In `apps/backend/tests/services/test_monitor_poll_worker.py`, add (needs `factories` fixture — already available via `conftest.py`; add `factories` to the test's parameters):

```python
async def test_process_batch_applies_proxmox_override(db_session, factories):
    factory, orig_close = _noop_close_factory(db_session)
    hw = factories.hardware(proxmox_node_name="pve1", telemetry_last_polled=datetime.now(UTC))
    item = MonitorItem(
        name="pve-node",
        host="10.0.0.9",
        check_type="fake_down",
        target_type="hardware",
        target_id=hw.id,
        max_retries=0,
        interval_secs=60,
        last_status="down",
        next_due_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    db_session.add(item)
    db_session.flush()

    fake_redis = AsyncMock()
    with (
        patch(
            "app.workers.monitor_poll_worker.COLLECTORS",
            {
                "fake_down": lambda host, params: CheckResult(
                    up=False, samples=[Sample("avail", 0.0)], msg="100% packet loss"
                )
            },
        ),
        patch.object(mpw, "get_redis", AsyncMock(return_value=fake_redis)),
    ):
        await process_batch(
            [
                {
                    "item_id": item.id,
                    "target_type": "hardware",
                    "target_id": hw.id,
                    "host": item.host,
                    "check_type": "fake_down",
                    "params": {},
                }
            ],
            factory,
        )
    db_session.close = orig_close

    db_session.expire_all()
    fresh = db_session.get(MonitorItem, item.id)
    assert fresh.last_status == "up"  # Proxmox override flipped it: down -> up = "recovered"

    sample = (
        db_session.query(TelemetryTimeseries)
        .filter(TelemetryTimeseries.item_id == item.id, TelemetryTimeseries.metric == "avail")
        .one()
    )
    assert sample.value == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/backend/tests/services/test_monitor_poll_worker.py::test_process_batch_applies_proxmox_override -v`
Expected: FAIL — `fresh.last_status == "down"` (override not wired in yet), or the `sample.value == 1.0` assertion fails (still `0.0`).

- [ ] **Step 3: Wire in the override call**

In `apps/backend/src/app/workers/monitor_poll_worker.py`, add the import (~line 26):

```python
from app.services.monitoring.collectors import COLLECTORS, CheckResult, Sample
from app.services.monitoring.proxmox_override import apply_proxmox_overrides
from app.services.monitoring.state import AppliedTransition, apply_result
```

And update `process_batch` (~line 75-86) to call it right after `db = db_factory()` and before `write_samples`:

```python
async def process_batch(items: list[dict], db_factory: Callable[[], Any]) -> int:
    outcomes = await asyncio.gather(*(poll_one(i) for i in items))
    transitions: list[AppliedTransition] = []
    db = db_factory()
    try:
        outcomes = apply_proxmox_overrides(db, items, outcomes)
        written = write_samples(db, [row for row, _, _ in outcomes])
        for row, up, msg in outcomes:
            item_id, _, _, _, ts = row
            transition = apply_result(db, item_id, up=up, msg=msg, checked_at=ts)
            if transition:
                transitions.append(transition)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    await _publish_transitions(transitions)
    await _publish_live_status(outcomes)
    return written
```

(`_publish_live_status(outcomes)` already runs after reassignment, so live status pushes also reflect the override automatically — no further change needed there.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/backend/tests/services/test_monitor_poll_worker.py -v`
Expected: PASS (all tests in the file, including the existing ones — confirms no regression).

- [ ] **Step 5: Run the full backend test suite**

Run: `pytest apps/backend/tests -q`
Expected: PASS. (Known pre-existing unrelated failures on this host — pg_dump, nmap gate, webhook tests — are expected and not caused by this change; see memory `backend-test-env-gotchas` if new failures need triage.)

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/workers/monitor_poll_worker.py apps/backend/tests/services/test_monitor_poll_worker.py
git commit -m "feat(monitors): wire Proxmox priority override into process_batch"
```

---

## Self-Review Notes

- Spec's "Where the override happens" and "Downstream effect" sections → Task 4 (call site placement, no changes needed to rollup/percentage code since they already read from `telemetry_timeseries`/`avail`).
- Spec's "Mechanics" steps 1-3 (batch fetch, freshness determination per entity type, 5-minute window) → Task 3.
- Spec's "Mechanics" step 4 (rebuild outcome: avail sample, `up`, annotated `msg`, immutability) → Task 3, `_apply_one`.
- Spec's "Mechanics" step 5 (agreement / no opinion → unchanged, same object) → Task 3, tests `test_agreement_passes_through_unchanged` / `test_stale_hardware_passes_through_unchanged` assert identity (`is`), not just equality.
- Spec's "Mechanics" step 6 (symmetric override) → Task 3, `test_fresh_compute_unit_overrides_false_up` (ComputeUnit can flip either direction; Hardware is asymmetric by construction since a fresh node poll can only mean "up" — this matches the spec's own reasoning in step 2, not a deviation).
- Spec's "Schema change" → Task 1 (column + migration + exclusion list) and Task 2 (setting it in the poll loop).
- Spec's "Error handling" (no link/stale → passthrough; missing target row → passthrough; internal bug → per-item fallback) → Task 3 tests `test_hardware_without_proxmox_link_passes_through_unchanged`, `test_missing_target_row_passes_through_unchanged`, `test_standalone_monitor_passes_through_unchanged`, and the try/except in `apply_proxmox_overrides`.
- Spec's "Testing" section is covered 1:1: unit tests for `apply_proxmox_overrides` (Task 3), wiring test in `process_batch` (Task 4), `proxmox_telemetry.py` VM-poll assertion (Task 2), migration verification (Task 1, Step 4).
- Spec's "Out of scope" items (retroactive correction, `proxmox_client.py`/polling schedule, ICMP/TCP collectors, user-facing conflict UI) → deliberately untouched by all four tasks.
