# Native Monitoring Engine — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the polling engine's `monitor_items` into first-class monitors with a full HTTP/DNS check library, an up/pending/down state machine, transition events, alert publishing, live WS push, and a Monitors dashboard.

**Architecture:** The existing scheduler → NATS JetStream (`mon.poll.item`) → poll-worker → TimescaleDB pipeline stays intact. Collectors become a package returning a richer `CheckResult`; the poll worker applies a state machine against the `monitor_items` row (SELECT FOR UPDATE), appends `monitor_events` on transitions, publishes alerts to the existing `alert.>` NATS pipeline and live status to Redis pub/sub channel `monitor:{id}`, bridged to the browser by a new WS endpoint.

**Tech Stack:** FastAPI, SQLAlchemy 2 + Alembic, NATS JetStream, Redis pub/sub, TimescaleDB, httpx, dnspython (new dep), React (JSX) frontend.

**Spec:** `specs/2026-07-25-native-monitoring-engine-design.md`

## Global Constraints

- **CB nomenclature only** — zero "kuma"/"uptime-kuma" strings in any production code, test, comment, or migration. Terms: *check*, *sample*, *event*, *monitor* (never "beat"/"heartbeat").
- Collector functions **never raise** for unreachable targets — failure is a datum (`up=False` + reason), matching the existing contract in `services/monitoring/collectors.py`.
- New tables/columns must be excluded in `migrations/versions/0001_init.py` (`_EXCLUDED_TABLES` / `_EXCLUDED_COLUMNS`) so fresh installs create them via the new migration, not the metadata bootstrap. Verify with a fresh-volume mono boot at the end.
- All configuration is in-app (API-driven); no terminal steps for users.
- Existing `params` JSONB column on `monitor_items` serves as the spec's `config` field — no rename churn. API exposes it as `config`.
- Statuses are lowercase strings: `up | down | pending | maintenance` (stored in the existing `last_status` column; `maintenance` is reserved for slice 2).
- Backend tests: `cd apps/backend && python -m pytest tests/...`. Known pre-existing failures on this host (pg_dump, nmap gate, webhooks) are not regressions. A built `frontend/dist` flips some backend 404 tests to 405 — don't chase those.
- Never add `Co-Authored-By: Claude` trailers to commits.

## File Structure

```
apps/backend/
  migrations/versions/0086_native_monitors.py      # NEW — schema evolution
  migrations/versions/0001_init.py                 # MODIFY — exclusion lists
  src/app/db/models.py                             # MODIFY — MonitorItem cols + MonitorEvent
  src/app/services/monitoring/collectors/          # NEW package (replaces collectors.py)
    __init__.py                                    #   Sample, CheckResult, COLLECTORS registry
    net.py                                         #   icmp + tcp (moved, wrapped)
    web.py                                         #   full HTTP check
    dns_check.py                                   #   DNS check
  src/app/services/monitoring/state.py             # NEW — state machine + row application
  src/app/workers/monitor_poll_worker.py           # MODIFY — CheckResult, state, publishing
  src/app/schemas/monitor.py                       # REWRITE — per-type config models
  src/app/services/monitor_service.py              # REWRITE — monitor-id CRUD + queries
  src/app/api/monitor.py                           # REWRITE — monitor-id endpoints
  src/app/api/ws_monitors.py                       # NEW — WS bridge for monitor:{id}
  src/app/main.py                                  # MODIFY — mount WS router
  src/app/core/subjects.py                         # MODIFY — alert subject helpers
apps/frontend/src/
  api/monitor.js                                   # REWRITE — monitor-id client
  hooks/useMonitorStream.js                        # NEW — WS hook
  pages/MonitorsPage.jsx                           # NEW — list + heartbeat bars + forms
  pages/MonitorDetailPage.jsx                      # NEW — detail view
  components/monitors/MonitorForm.jsx              # NEW — create/edit form
  components/monitors/CheckHistoryBar.jsx          # NEW — recent-checks bar
  App.jsx                                          # MODIFY — routes
  data/navigation.js                               # MODIFY — nav entry
  pages/MapPage.jsx, hooks/useMapRealTimeUpdates.js,
  components/settings/IntegrationsManager.jsx      # MODIFY — use hardware-summary endpoint
```

---

### Task 1: Schema — migration, models, bootstrap exclusions

**Files:**
- Create: `apps/backend/migrations/versions/0086_native_monitors.py`
- Modify: `apps/backend/src/app/db/models.py` (MonitorItem ~line 226), `apps/backend/migrations/versions/0001_init.py` (exclusion lists, ~line 22/57)
- Modify: `/home/shawnji/workspace/CircuitBreaker/.gitignore` (add `uptime-kuma/`)
- Test: `apps/backend/tests/services/test_monitor_model.py` (extend)

**Interfaces:**
- Produces: `MonitorItem` new columns `name: str`, `max_retries: int`, `retry_interval_secs: int | None`, `last_status_change_at: datetime | None`; `target_type` now nullable. New model `MonitorEvent(id, item_id, event_type, status_from, status_to, msg, duration_secs, created_at)`.

- [ ] **Step 1: Add `uptime-kuma/` to `.gitignore`**

Append to the repo-root `.gitignore`:

```gitignore
# Local reference repo for the monitoring port — never committed
uptime-kuma/
```

- [ ] **Step 2: Write failing model test**

Append to `apps/backend/tests/services/test_monitor_model.py`:

```python
from datetime import UTC, datetime

from app.db.models import MonitorEvent, MonitorItem


def test_monitor_item_native_fields(db_session):
    item = MonitorItem(
        name="edge router dns",
        target_type=None,
        target_id=None,
        host="192.0.2.10",
        check_type="dns",
        params={"record_type": "A"},
        interval_secs=60,
        max_retries=3,
        retry_interval_secs=15,
        next_due_at=datetime.now(UTC),
    )
    db_session.add(item)
    db_session.flush()
    assert item.id is not None
    assert item.max_retries == 3
    assert item.last_status_change_at is None


def test_monitor_event_row(db_session):
    item = MonitorItem(
        name="probe", host="192.0.2.11", check_type="icmp",
        target_type="ip", next_due_at=datetime.now(UTC),
    )
    db_session.add(item)
    db_session.flush()
    ev = MonitorEvent(
        item_id=item.id, event_type="down",
        status_from="up", status_to="down", msg="timed out",
    )
    db_session.add(ev)
    db_session.flush()
    assert ev.id is not None
    assert ev.created_at is not None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_model.py -v`
Expected: FAIL — `TypeError: 'name' is an invalid keyword argument` / `ImportError: cannot import name 'MonitorEvent'`

- [ ] **Step 4: Update `models.py`**

In `MonitorItem` (models.py:226): make `target_type` nullable and add the new columns after `check_type`:

```python
class MonitorItem(Base):
    """A monitor: one configured check on a target at an interval."""

    __tablename__ = "monitor_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    # hardware|compute_unit|external_node|service|ip — None for standalone monitors
    target_type: Mapped[str | None] = mapped_column(String, nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    host: Mapped[str] = mapped_column(String, nullable=False)  # resolved ip/hostname to probe
    check_type: Mapped[str] = mapped_column(String, nullable=False)  # icmp|tcp|http|dns
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    interval_secs: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # interval while in pending (retrying); None falls back to interval_secs
    retry_interval_secs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String, nullable=True)  # up|down|pending|maintenance
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_status_change_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (Index("ix_monitor_items_due", "enabled", "next_due_at"),)
```

Add directly below it:

```python
class MonitorEvent(Base):
    """State-transition history for a monitor (feeds event log and check bar)."""

    __tablename__ = "monitor_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monitor_items.id", ondelete="CASCADE"), nullable=False
    )
    # up|down|pending|maintenance|paused|resumed
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    status_from: Mapped[str | None] = mapped_column(String, nullable=True)
    status_to: Mapped[str] = mapped_column(String, nullable=False)
    msg: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # seconds spent in status_from before this transition
    duration_secs: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_monitor_events_item_time", "item_id", "created_at"),)
```

(`Text`, `Float`, `ForeignKey`, `Index` are already imported at the top of models.py.)

- [ ] **Step 5: Write migration `0086_native_monitors.py`**

```python
"""Evolve monitor_items into first-class monitors; add monitor_events.

Revision ID: 0086_native_monitors
Revises: 0085_bootstrap_domain_fqdn
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0086_native_monitors"
down_revision = "0085_bootstrap_domain_fqdn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monitor_items",
        sa.Column("name", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "monitor_items",
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "monitor_items",
        sa.Column("retry_interval_secs", sa.Integer(), nullable=True),
    )
    op.add_column(
        "monitor_items",
        sa.Column("last_status_change_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("monitor_items", "target_type", nullable=True)
    # Backfill names for engine-created rows; normalize legacy status values
    op.execute(
        "UPDATE monitor_items SET name = host || ' (' || check_type || ')' WHERE name = ''"
    )
    op.execute(
        "UPDATE monitor_items SET last_status = 'pending' "
        "WHERE last_status IS NULL OR last_status NOT IN ('up','down','pending','maintenance')"
    )

    op.create_table(
        "monitor_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("monitor_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("status_from", sa.String(), nullable=True),
        sa.Column("status_to", sa.String(), nullable=False),
        sa.Column("msg", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration_secs", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_monitor_events_item_time",
        "monitor_events",
        ["item_id", "created_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_monitor_events_item_time", table_name="monitor_events", if_exists=True)
    op.drop_table("monitor_events", if_exists=True)
    op.alter_column("monitor_items", "target_type", nullable=False)
    op.drop_column("monitor_items", "last_status_change_at")
    op.drop_column("monitor_items", "retry_interval_secs")
    op.drop_column("monitor_items", "max_retries")
    op.drop_column("monitor_items", "name")
```

- [ ] **Step 6: Update `0001_init.py` exclusion lists**

In `_EXCLUDED_TABLES` (0001_init.py:22) add alphabetically:

```python
    "monitor_events",
```

In `_EXCLUDED_COLUMNS` (0001_init.py:57) add an entry:

```python
    "monitor_items": {
        "name",
        "max_retries",
        "retry_interval_secs",
        "last_status_change_at",
    },
```

**Note:** `target_type` stays in 0001's metadata (it creates it nullable from the updated model, which is fine for fresh installs; 0086's `alter_column` is a no-op there).

- [ ] **Step 7: Apply migration to the dev DB and run tests**

Run: `cd apps/backend && alembic upgrade head && python -m pytest tests/services/test_monitor_model.py -v`
Expected: migration applies cleanly; both new tests PASS.

- [ ] **Step 8: Commit**

```bash
git add .gitignore apps/backend/migrations/versions/0086_native_monitors.py \
  apps/backend/migrations/versions/0001_init.py apps/backend/src/app/db/models.py \
  apps/backend/tests/services/test_monitor_model.py
git commit -m "feat(monitoring): evolve monitor_items into first-class monitors, add monitor_events"
```

---

### Task 2: Collector contract — `CheckResult` + collectors package

**Files:**
- Create: `apps/backend/src/app/services/monitoring/collectors/__init__.py`, `.../collectors/net.py`
- Delete: `apps/backend/src/app/services/monitoring/collectors.py` (contents move)
- Modify: `apps/backend/src/app/workers/monitor_poll_worker.py`, `apps/backend/src/app/services/monitoring/writer.py` (import only)
- Test: `apps/backend/tests/services/test_monitor_collectors.py` (update), `apps/backend/tests/services/test_monitor_poll_worker.py` (update)

**Interfaces:**
- Produces: `Sample(metric, value, error_reason)` (unchanged), `CheckResult(up: bool, samples: list[Sample], msg: str = "", details: dict | None = None)`, `COLLECTORS: dict[str, Callable[[str, dict], CheckResult]]` with keys `icmp`, `tcp`. Import path `app.services.monitoring.collectors` keeps working (package `__init__` re-exports).
- Consumers: poll worker (Task 6), web/dns collectors (Tasks 3–4) register here.

- [ ] **Step 1: Update collector tests for the new contract**

In `tests/services/test_monitor_collectors.py`, update assertions from `list[Sample]` to `CheckResult`. Pattern for every existing test (keep the mock style already used there — mocking `_ping_once` / `_tcp_connect`):

```python
from app.services.monitoring.collectors import COLLECTORS, CheckResult, Sample
from app.services.monitoring.collectors import net


def test_icmp_all_up(monkeypatch):
    monkeypatch.setattr(net, "_ping_once", lambda host, timeout: 12.5)
    result = net.collect_icmp("192.0.2.1", {"packet_count": 3})
    assert isinstance(result, CheckResult)
    assert result.up is True
    metrics = {s.metric: s.value for s in result.samples}
    assert metrics["avail"] == 1.0
    assert metrics["packet_loss_pct"] == 0.0


def test_icmp_all_lost(monkeypatch):
    monkeypatch.setattr(net, "_ping_once", lambda host, timeout: None)
    result = net.collect_icmp("192.0.2.1", {"packet_count": 3})
    assert result.up is False
    assert "loss" in result.msg


def test_tcp_down(monkeypatch):
    monkeypatch.setattr(net, "_tcp_connect", lambda h, p, t: (False, None))
    result = net.collect_tcp("192.0.2.1", {"port": 22})
    assert result.up is False


def test_registry_keys():
    assert {"icmp", "tcp"} <= set(COLLECTORS)
```

Adapt each pre-existing test in the file the same way: `samples` → `result.samples`, add `result.up` assertions. Delete tests for the old basic `collect_http` (replaced in Task 3).

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_collectors.py -v`
Expected: FAIL — `ImportError: cannot import name 'CheckResult'`

- [ ] **Step 3: Create the package**

`src/app/services/monitoring/collectors/__init__.py`:

```python
"""Check collectors for the monitoring engine.

Each collector runs blocking network I/O and returns a CheckResult. It must
NEVER raise for an unreachable target — failure is a datum (up=False with a
reason in msg). No DB access here so collectors stay unit-testable by mocking
the private probe helpers in each module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sample:
    metric: str
    value: float
    error_reason: str | None = None


@dataclass(frozen=True)
class CheckResult:
    up: bool
    samples: list[Sample] = field(default_factory=list)
    msg: str = ""
    details: dict | None = None


CollectorFn = Callable[[str, dict], CheckResult]

COLLECTORS: dict[str, CollectorFn] = {}


def register(check_type: str, fn: CollectorFn) -> None:
    COLLECTORS[check_type] = fn


# Import for side effect: each module registers its collectors.
from app.services.monitoring.collectors import net  # noqa: E402,F401
```

`src/app/services/monitoring/collectors/net.py` — move `_ping_once`, `_tcp_connect`, `_jitter` verbatim from the old `collectors.py`, then wrap the two collectors:

```python
"""ICMP and TCP reachability checks."""

from __future__ import annotations

import socket
import time

from app.services.monitoring.collectors import CheckResult, Sample, register

# ── Probe primitives (mocked in tests) ─────────────────────────────────────────
# _ping_once, _tcp_connect, _jitter: moved verbatim from the old collectors.py
# (keep their exact bodies — see git history of services/monitoring/collectors.py)


def collect_icmp(host: str, params: dict) -> CheckResult:
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
        return CheckResult(
            up=False,
            samples=[Sample("avail", 0.0, error_reason="icmp_unavailable")],
            msg="icmp probe unavailable on this host",
        )

    loss_pct = round(lost / count * 100, 2) if count else 100.0
    up = bool(latencies)
    samples = [Sample("avail", 1.0 if up else 0.0), Sample("packet_loss_pct", loss_pct)]
    if latencies:
        mean = round(sum(latencies) / len(latencies), 3)
        samples += [
            Sample("latency_ms", mean),
            Sample("latency_min_ms", min(latencies)),
            Sample("latency_max_ms", max(latencies)),
            Sample("jitter_ms", _jitter(latencies)),
        ]
        msg = f"{mean}ms avg, {loss_pct}% loss"
    else:
        msg = f"100% packet loss ({count} probes)"
    return CheckResult(up=up, samples=samples, msg=msg)


def collect_tcp(host: str, params: dict) -> CheckResult:
    ports = params.get("ports") or [params.get("port", 80)]
    timeout = float(params.get("timeout", 1.0))
    for port in ports:
        ok, latency = _tcp_connect(host, int(port), timeout)
        if ok and latency is not None:
            return CheckResult(
                up=True,
                samples=[Sample("avail", 1.0), Sample("latency_ms", latency)],
                msg=f"port {port} open in {latency}ms",
            )
    return CheckResult(
        up=False,
        samples=[Sample("avail", 0.0)],
        msg=f"no reachable port in {ports}",
    )


register("icmp", collect_icmp)
register("tcp", collect_tcp)
```

**Important:** copy `_ping_once`, `_tcp_connect`, `_jitter` bodies exactly as they exist in the current `collectors.py` (shown in its lines 27–52 and 88–92), then `git rm apps/backend/src/app/services/monitoring/collectors.py`. Do NOT carry over the old `_http_head`/`collect_http` (Task 3 replaces it).

- [ ] **Step 4: Fix the poll worker's temporary compatibility**

In `workers/monitor_poll_worker.py`, `poll_one` currently expects `list[Sample]`. Minimal interim change (Task 6 does the full rework):

```python
from app.services.monitoring.collectors import COLLECTORS, CheckResult, Sample
```

and in `poll_one`, after calling the collector:

```python
    try:
        async with _sema:
            result = await asyncio.to_thread(collector, item["host"], item["params"])
        samples = result.samples
    except Exception as exc:  # noqa: BLE001 — a probe crash is a down datum
        logger.debug("Collector crashed for item %s: %s", item["item_id"], exc)
        samples = [Sample("avail", 0.0, error_reason="collector_error")]
    return (item["item_id"], item["target_type"], item["target_id"], samples, ts)
```

Also update the unknown-check-type early return to stay `list[Sample]`-shaped (unchanged). `writer.py` needs no change (it imports `Sample` from the package path, which re-exports).

- [ ] **Step 5: Run collector + worker + writer tests**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_collectors.py tests/services/test_monitor_poll_worker.py tests/services/test_monitor_writer.py -v`
Expected: PASS (adjust any worker test that constructed `list[Sample]` collector returns — mock collectors must now return `CheckResult`).

- [ ] **Step 6: Commit**

```bash
git add -A apps/backend/src/app/services/monitoring apps/backend/src/app/workers/monitor_poll_worker.py apps/backend/tests/services
git commit -m "refactor(monitoring): collectors package with CheckResult contract"
```

---

### Task 3: Full HTTP check

**Files:**
- Create: `apps/backend/src/app/services/monitoring/collectors/web.py`
- Modify: `apps/backend/src/app/services/monitoring/collectors/__init__.py` (import line)
- Test: `apps/backend/tests/services/test_monitor_collector_web.py` (new)

**Interfaces:**
- Consumes: `CheckResult`, `Sample`, `register` from Task 2.
- Produces: `COLLECTORS["http"]`. Params schema (matches `HttpConfig` in Task 7): `url, method, headers, body, timeout, auth_type (none|basic|bearer), username, password, token, accepted_statuses (list[str] of "N" or "N-M" ranges), keyword, keyword_invert, json_path, expected_value, verify_tls, follow_redirects`.

- [ ] **Step 1: Write failing tests**

`tests/services/test_monitor_collector_web.py`:

```python
from unittest.mock import MagicMock, patch

from app.services.monitoring.collectors import COLLECTORS
from app.services.monitoring.collectors import web


def _mock_response(status=200, text="hello world", json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


def _run(params, resp):
    with patch.object(web, "_request", return_value=(resp, 42.0)):
        return web.collect_http("192.0.2.5", params)


def test_http_registered():
    assert COLLECTORS["http"] is web.collect_http


def test_status_in_default_range():
    result = _run({"url": "http://x/"}, _mock_response(204))
    assert result.up is True
    assert "204" in result.msg


def test_status_outside_range():
    result = _run({"url": "http://x/"}, _mock_response(500))
    assert result.up is False
    assert "500" in result.msg


def test_explicit_status_ranges():
    result = _run({"url": "http://x/", "accepted_statuses": ["301", "400-403"]},
                  _mock_response(403))
    assert result.up is True


def test_keyword_found():
    result = _run({"url": "http://x/", "keyword": "world"}, _mock_response(200, "hello world"))
    assert result.up is True


def test_keyword_missing():
    result = _run({"url": "http://x/", "keyword": "absent"}, _mock_response(200, "hello world"))
    assert result.up is False
    assert "keyword" in result.msg


def test_keyword_inverted():
    result = _run({"url": "http://x/", "keyword": "error", "keyword_invert": True},
                  _mock_response(200, "all fine"))
    assert result.up is True


def test_json_path_match():
    result = _run(
        {"url": "http://x/", "json_path": "status.state", "expected_value": "ok"},
        _mock_response(200, "{}", {"status": {"state": "ok"}}),
    )
    assert result.up is True


def test_json_path_mismatch():
    result = _run(
        {"url": "http://x/", "json_path": "status.state", "expected_value": "ok"},
        _mock_response(200, "{}", {"status": {"state": "degraded"}}),
    )
    assert result.up is False


def test_network_error_is_down_not_raise():
    with patch.object(web, "_request", side_effect=OSError("refused")):
        result = web.collect_http("192.0.2.5", {"url": "http://x/"})
    assert result.up is False
    assert result.samples[0].error_reason == "http_error"


def test_status_range_parser():
    assert web._status_accepted(204, ["200-299"]) is True
    assert web._status_accepted(301, ["200-299"]) is False
    assert web._status_accepted(301, ["200-299", "301"]) is True
    assert web._status_accepted(200, []) is True  # empty → default 200-299
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_collector_web.py -v`
Expected: FAIL — `ModuleNotFoundError: ... collectors.web`

- [ ] **Step 3: Implement `web.py`**

```python
"""HTTP(S) check: status ranges, keyword, JSON path, TLS certificate capture."""

from __future__ import annotations

import json
import socket
import ssl
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

from app.services.monitoring.collectors import CheckResult, Sample, register

_DEFAULT_RANGES = ["200-299"]


def _request(url: str, params: dict) -> tuple["httpx.Response", float]:
    """One HTTP request. Returns (response, latency_ms). Mocked in tests."""
    import httpx

    method = str(params.get("method", "GET")).upper()
    headers = dict(params.get("headers") or {})
    auth_type = params.get("auth_type", "none")
    auth = None
    if auth_type == "basic":
        auth = (params.get("username", ""), params.get("password", ""))
    elif auth_type == "bearer" and params.get("token"):
        headers["Authorization"] = f"Bearer {params['token']}"
    t0 = time.monotonic()
    resp = httpx.request(
        method,
        url,
        headers=headers or None,
        content=params.get("body") or None,
        timeout=float(params.get("timeout", 10.0)),
        follow_redirects=bool(params.get("follow_redirects", True)),
        auth=auth,
        verify=bool(params.get("verify_tls", True)),
    )
    return resp, round((time.monotonic() - t0) * 1000, 2)


def _status_accepted(status: int, ranges: list[str]) -> bool:
    for r in ranges or _DEFAULT_RANGES:
        r = str(r).strip()
        if "-" in r:
            lo, _, hi = r.partition("-")
            try:
                if int(lo) <= status <= int(hi):
                    return True
            except ValueError:
                continue
        elif r.isdigit() and int(r) == status:
            return True
    return False


def _json_path(data: object, path: str) -> object:
    """Resolve a dotted path with optional [idx] segments; None if unresolvable."""
    cur = data
    for part in path.replace("]", "").split("."):
        for seg in part.split("["):
            if seg == "":
                continue
            if isinstance(cur, dict):
                cur = cur.get(seg)
            elif isinstance(cur, list) and seg.lstrip("-").isdigit():
                idx = int(seg)
                cur = cur[idx] if -len(cur) <= idx < len(cur) else None
            else:
                return None
    return cur


def _tls_details(url: str, timeout: float) -> dict | None:
    """Best-effort certificate capture for https URLs. Never raises."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return None
    host = parsed.hostname
    port = parsed.port or 443
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
        not_after = cert.get("notAfter")
        expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
        days = (expires - datetime.now(UTC)).days
        subject = dict(x[0] for x in cert.get("subject", ()))
        issuer = dict(x[0] for x in cert.get("issuer", ()))
        return {
            "tls": {
                "subject_cn": subject.get("commonName"),
                "issuer_cn": issuer.get("commonName"),
                "expires_at": expires.isoformat(),
                "days_remaining": days,
            }
        }
    except Exception:  # noqa: BLE001 — cert capture is auxiliary, never fails a check
        return None


def collect_http(host: str, params: dict) -> CheckResult:
    url = params.get("url") or f"http://{host}/"
    try:
        resp, latency = _request(url, params)
    except Exception as exc:  # noqa: BLE001 — network failure is a datum, not an error
        return CheckResult(
            up=False,
            samples=[Sample("avail", 0.0, error_reason="http_error")],
            msg=f"request failed: {type(exc).__name__}",
        )

    samples = [Sample("latency_ms", latency), Sample("http_status", float(resp.status_code))]
    details = _tls_details(url, float(params.get("timeout", 10.0)))
    if details and details["tls"].get("days_remaining") is not None:
        samples.append(Sample("cert_days_remaining", float(details["tls"]["days_remaining"])))

    if not _status_accepted(resp.status_code, params.get("accepted_statuses") or []):
        samples.insert(0, Sample("avail", 0.0))
        return CheckResult(
            up=False, samples=samples,
            msg=f"unexpected status {resp.status_code}", details=details,
        )

    keyword = params.get("keyword")
    if keyword:
        found = keyword in (resp.text or "")
        invert = bool(params.get("keyword_invert", False))
        if found == invert:
            samples.insert(0, Sample("avail", 0.0))
            verb = "found" if invert else "not found"
            return CheckResult(
                up=False, samples=samples,
                msg=f"keyword {verb}: {keyword!r}", details=details,
            )

    json_path = params.get("json_path")
    if json_path:
        try:
            value = _json_path(resp.json(), json_path)
        except (ValueError, json.JSONDecodeError):
            value = None
        expected = params.get("expected_value")
        if expected is not None and str(value) != str(expected):
            samples.insert(0, Sample("avail", 0.0))
            return CheckResult(
                up=False, samples=samples,
                msg=f"json {json_path} = {value!r}, expected {expected!r}", details=details,
            )

    samples.insert(0, Sample("avail", 1.0))
    return CheckResult(
        up=True, samples=samples,
        msg=f"{resp.status_code} in {latency}ms", details=details,
    )


register("http", collect_http)
```

Add to `collectors/__init__.py` bottom import block:

```python
from app.services.monitoring.collectors import net, web  # noqa: E402,F401
```

- [ ] **Step 4: Run tests**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_collector_web.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/monitoring/collectors apps/backend/tests/services/test_monitor_collector_web.py
git commit -m "feat(monitoring): full HTTP check with status ranges, keyword, json path, cert capture"
```

---

### Task 4: DNS check

**Files:**
- Create: `apps/backend/src/app/services/monitoring/collectors/dns_check.py`
- Modify: `apps/backend/pyproject.toml` (add `dnspython>=2.6`), `collectors/__init__.py` (import line)
- Test: `apps/backend/tests/services/test_monitor_collector_dns.py` (new)

**Interfaces:**
- Produces: `COLLECTORS["dns"]`. Params (matches `DnsConfig`, Task 7): `record_type (A|AAAA|CNAME|MX|TXT|NS|SOA|PTR|SRV|CAA)`, `resolver` (IP, optional), `port` (default 53), `expected_values` (list[str], optional — up requires at least one returned record to contain one expected value), `timeout` (default 5).

- [ ] **Step 1: Add dependency**

In `apps/backend/pyproject.toml`, add to the main `dependencies` array (alphabetical position):

```toml
    "dnspython>=2.6",
```

Run: `cd apps/backend && uv sync` (or `pip install dnspython>=2.6` in the venv — match how the repo's dev env installs; check `Makefile` targets first).

- [ ] **Step 2: Write failing tests**

`tests/services/test_monitor_collector_dns.py`:

```python
from unittest.mock import patch

from app.services.monitoring.collectors import COLLECTORS
from app.services.monitoring.collectors import dns_check


def test_dns_registered():
    assert COLLECTORS["dns"] is dns_check.collect_dns


def test_resolve_up():
    with patch.object(dns_check, "_resolve", return_value=(["192.0.2.1", "192.0.2.2"], 8.5)):
        result = dns_check.collect_dns("example.com", {"record_type": "A"})
    assert result.up is True
    assert result.details == {"records": ["192.0.2.1", "192.0.2.2"]}
    metrics = {s.metric: s.value for s in result.samples}
    assert metrics["avail"] == 1.0
    assert metrics["latency_ms"] == 8.5


def test_expected_value_match():
    with patch.object(dns_check, "_resolve", return_value=(["192.0.2.1"], 5.0)):
        result = dns_check.collect_dns(
            "example.com", {"record_type": "A", "expected_values": ["192.0.2.1"]}
        )
    assert result.up is True


def test_expected_value_mismatch():
    with patch.object(dns_check, "_resolve", return_value=(["192.0.2.9"], 5.0)):
        result = dns_check.collect_dns(
            "example.com", {"record_type": "A", "expected_values": ["192.0.2.1"]}
        )
    assert result.up is False
    assert "expected" in result.msg


def test_nxdomain_is_down_not_raise():
    with patch.object(dns_check, "_resolve", side_effect=dns_check.DnsLookupError("NXDOMAIN")):
        result = dns_check.collect_dns("nope.invalid", {"record_type": "A"})
    assert result.up is False
    assert result.samples[0].error_reason == "dns_error"
```

- [ ] **Step 3: Run to verify failure**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_collector_dns.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement `dns_check.py`**

```python
"""DNS resolution check with optional expected-value matching."""

from __future__ import annotations

import time

from app.services.monitoring.collectors import CheckResult, Sample, register


class DnsLookupError(Exception):
    """Raised by _resolve on any lookup failure (wrapped for testability)."""


def _resolve(hostname: str, params: dict) -> tuple[list[str], float]:
    """Resolve one record set. Returns (record strings, latency_ms). Mocked in tests."""
    import dns.resolver

    resolver = dns.resolver.Resolver()
    if params.get("resolver"):
        resolver.nameservers = [str(params["resolver"])]
    resolver.port = int(params.get("port", 53))
    timeout = float(params.get("timeout", 5.0))
    resolver.timeout = timeout
    resolver.lifetime = timeout
    record_type = str(params.get("record_type", "A")).upper()
    t0 = time.monotonic()
    try:
        answer = resolver.resolve(hostname, record_type)
    except Exception as exc:  # noqa: BLE001 — normalized for the collector
        raise DnsLookupError(str(exc)) from exc
    latency = round((time.monotonic() - t0) * 1000, 2)
    return [str(r) for r in answer], latency


def collect_dns(host: str, params: dict) -> CheckResult:
    record_type = str(params.get("record_type", "A")).upper()
    try:
        records, latency = _resolve(host, params)
    except DnsLookupError as exc:
        return CheckResult(
            up=False,
            samples=[Sample("avail", 0.0, error_reason="dns_error")],
            msg=f"{record_type} lookup failed: {exc}",
        )

    samples = [Sample("avail", 1.0), Sample("latency_ms", latency)]
    details = {"records": records}
    expected = params.get("expected_values") or []
    if expected:
        matched = any(any(e in r for r in records) for e in expected)
        if not matched:
            samples[0] = Sample("avail", 0.0)
            return CheckResult(
                up=False, samples=samples,
                msg=f"{record_type} records {records} did not match expected {expected}",
                details=details,
            )
    return CheckResult(
        up=True, samples=samples,
        msg=f"{record_type}: {len(records)} record(s) in {latency}ms", details=details,
    )


register("dns", collect_dns)
```

Update `collectors/__init__.py` import line:

```python
from app.services.monitoring.collectors import dns_check, net, web  # noqa: E402,F401
```

- [ ] **Step 5: Run tests**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_collector_dns.py tests/services/test_monitor_collectors.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/pyproject.toml apps/backend/src/app/services/monitoring/collectors \
  apps/backend/tests/services/test_monitor_collector_dns.py
git commit -m "feat(monitoring): DNS check with expected-value matching"
```

---

### Task 5: State machine

**Files:**
- Create: `apps/backend/src/app/services/monitoring/state.py`
- Test: `apps/backend/tests/services/test_monitor_state.py` (new)

**Interfaces:**
- Produces:
  - constants `UP = "up"`, `DOWN = "down"`, `PENDING = "pending"`, `MAINTENANCE = "maintenance"`
  - `StateDecision(new_status: str, retries: int, event_type: str | None, notify: str | None)` — `notify` is `"down"`, `"recovered"`, or `None`
  - `decide(prev_status: str | None, prev_retries: int, up: bool, max_retries: int) -> StateDecision` (pure function)
  - `apply_result(db: Session, item_id: int, up: bool, msg: str, checked_at: datetime) -> AppliedTransition | None` — locks the row, applies `decide`, updates status/retries/next_due_at, inserts a `MonitorEvent` on transition. Returns `AppliedTransition(item_id, name, status_from, status_to, msg, notify, occurred_at)` when a transition happened, else `None`. **Caller owns commit.**
- Consumes: `MonitorItem`, `MonitorEvent` from Task 1.

- [ ] **Step 1: Write failing tests**

`tests/services/test_monitor_state.py`:

```python
from datetime import UTC, datetime, timedelta

from app.db.models import MonitorEvent, MonitorItem
from app.services.monitoring.state import DOWN, PENDING, UP, apply_result, decide


# ── decide(): pure transitions ─────────────────────────────────────────────────

def test_up_stays_up():
    d = decide(UP, 0, up=True, max_retries=3)
    assert d.new_status == UP and d.retries == 0
    assert d.event_type is None and d.notify is None


def test_first_check_up():
    d = decide(None, 0, up=True, max_retries=0)
    assert d.new_status == UP and d.event_type == "up" and d.notify is None


def test_failure_enters_pending_within_retries():
    d = decide(UP, 0, up=False, max_retries=3)
    assert d.new_status == PENDING and d.retries == 1
    assert d.event_type == "pending" and d.notify is None


def test_pending_stays_pending_silently():
    d = decide(PENDING, 1, up=False, max_retries=3)
    assert d.new_status == PENDING and d.retries == 2 and d.event_type is None


def test_retries_exhausted_goes_down():
    d = decide(PENDING, 3, up=False, max_retries=3)
    assert d.new_status == DOWN and d.event_type == "down" and d.notify == "down"


def test_no_retries_goes_straight_down():
    d = decide(UP, 0, up=False, max_retries=0)
    assert d.new_status == DOWN and d.notify == "down"


def test_down_stays_down_silently():
    d = decide(DOWN, 5, up=False, max_retries=3)
    assert d.new_status == DOWN and d.event_type is None and d.notify is None


def test_recovery_from_down_notifies():
    d = decide(DOWN, 4, up=True, max_retries=3)
    assert d.new_status == UP and d.retries == 0
    assert d.event_type == "up" and d.notify == "recovered"


def test_recovery_from_pending_no_notify():
    d = decide(PENDING, 2, up=True, max_retries=3)
    assert d.new_status == UP and d.event_type == "up" and d.notify is None


# ── apply_result(): row + event persistence ────────────────────────────────────

def _mk_item(db, **kw):
    defaults = dict(
        name="m", host="192.0.2.1", check_type="icmp", target_type=None,
        max_retries=1, retry_interval_secs=5, interval_secs=60,
        last_status=UP, consecutive_failures=0,
        next_due_at=datetime.now(UTC) + timedelta(seconds=60),
        last_status_change_at=datetime.now(UTC) - timedelta(seconds=120),
    )
    defaults.update(kw)
    item = MonitorItem(**defaults)
    db.add(item)
    db.flush()
    return item


def test_apply_failure_sets_pending_and_reschedules(db_session):
    item = _mk_item(db_session)
    now = datetime.now(UTC)
    transition = apply_result(db_session, item.id, up=False, msg="timeout", checked_at=now)
    db_session.flush()
    db_session.refresh(item)
    assert item.last_status == PENDING
    assert item.consecutive_failures == 1
    # retry rescheduling: next check ~retry_interval_secs out, not interval_secs
    assert (item.next_due_at - now).total_seconds() <= 10
    assert transition.status_to == PENDING and transition.notify is None
    ev = db_session.query(MonitorEvent).filter_by(item_id=item.id).one()
    assert ev.event_type == "pending" and ev.msg == "timeout"


def test_apply_down_then_recover_notifies(db_session):
    item = _mk_item(db_session, last_status=PENDING, consecutive_failures=1)
    now = datetime.now(UTC)
    t1 = apply_result(db_session, item.id, up=False, msg="still down", checked_at=now)
    assert t1.status_to == DOWN and t1.notify == "down"
    t2 = apply_result(db_session, item.id, up=True, msg="200 in 12ms", checked_at=now)
    assert t2.status_to == UP and t2.notify == "recovered"
    db_session.refresh(item)
    assert item.consecutive_failures == 0
    assert db_session.query(MonitorEvent).filter_by(item_id=item.id).count() == 2


def test_apply_no_transition_returns_none(db_session):
    item = _mk_item(db_session)
    result = apply_result(
        db_session, item.id, up=True, msg="ok", checked_at=datetime.now(UTC)
    )
    assert result is None
    assert db_session.query(MonitorEvent).filter_by(item_id=item.id).count() == 0


def test_apply_missing_item_returns_none(db_session):
    assert apply_result(db_session, 999999, up=True, msg="", checked_at=datetime.now(UTC)) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_state.py -v`
Expected: FAIL — `ModuleNotFoundError: ... monitoring.state`

- [ ] **Step 3: Implement `state.py`**

```python
"""Monitor state machine: up/pending/down transitions and event persistence.

decide() is pure and fully unit-testable. apply_result() locks the monitor row
(FOR UPDATE — safe across the 2 poll-worker replicas), applies the decision,
reschedules retries sooner than the base interval, and appends a MonitorEvent
on every transition. The caller owns the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import MonitorEvent, MonitorItem

UP = "up"
DOWN = "down"
PENDING = "pending"
MAINTENANCE = "maintenance"


@dataclass(frozen=True)
class StateDecision:
    new_status: str
    retries: int
    event_type: str | None  # None → no transition, nothing recorded
    notify: str | None  # "down" | "recovered" | None


@dataclass(frozen=True)
class AppliedTransition:
    item_id: int
    name: str
    status_from: str | None
    status_to: str
    msg: str
    notify: str | None
    occurred_at: datetime


def decide(
    prev_status: str | None, prev_retries: int, up: bool, max_retries: int
) -> StateDecision:
    if up:
        if prev_status == UP:
            return StateDecision(UP, 0, None, None)
        notify = "recovered" if prev_status == DOWN else None
        return StateDecision(UP, 0, "up", notify)

    retries = prev_retries + 1
    if prev_status != DOWN and retries <= max_retries:
        event = "pending" if prev_status != PENDING else None
        return StateDecision(PENDING, retries, event, None)
    if prev_status == DOWN:
        return StateDecision(DOWN, retries, None, None)
    return StateDecision(DOWN, retries, "down", "down")


def apply_result(
    db: Session, item_id: int, up: bool, msg: str, checked_at: datetime
) -> AppliedTransition | None:
    item = (
        db.query(MonitorItem)
        .filter(MonitorItem.id == item_id)
        .with_for_update()
        .one_or_none()
    )
    if item is None:
        return None

    decision = decide(item.last_status, item.consecutive_failures, up, item.max_retries)

    item.last_polled_at = checked_at
    item.consecutive_failures = decision.retries
    prev_status = item.last_status

    # Retrying: pull the next check in sooner than the scheduler's base advance.
    if decision.new_status == PENDING:
        retry_in = item.retry_interval_secs or item.interval_secs
        item.next_due_at = checked_at + timedelta(seconds=retry_in)

    if decision.event_type is None:
        item.last_status = decision.new_status
        return None

    duration_secs = None
    if item.last_status_change_at is not None:
        duration_secs = round((checked_at - item.last_status_change_at).total_seconds(), 1)

    item.last_status = decision.new_status
    item.last_status_change_at = checked_at
    db.add(
        MonitorEvent(
            item_id=item.id,
            event_type=decision.event_type,
            status_from=prev_status,
            status_to=decision.new_status,
            msg=msg[:2000],
            duration_secs=duration_secs,
        )
    )
    return AppliedTransition(
        item_id=item.id,
        name=item.name,
        status_from=prev_status,
        status_to=decision.new_status,
        msg=msg,
        notify=decision.notify,
        occurred_at=checked_at,
    )


__all__ = [
    "UP", "DOWN", "PENDING", "MAINTENANCE",
    "StateDecision", "AppliedTransition", "decide", "apply_result",
]
```

- [ ] **Step 4: Run tests**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_state.py -v`
Expected: all PASS. (Use the repo's existing `db_session` fixture from `tests/conftest.py`; per the log_worker_audit note, never use real prod keys as entity_name in direct tests — not applicable here, but keep test names synthetic.)

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/monitoring/state.py apps/backend/tests/services/test_monitor_state.py
git commit -m "feat(monitoring): up/pending/down state machine with event persistence"
```

---

### Task 6: Poll worker — apply state, publish alerts + live status

**Files:**
- Modify: `apps/backend/src/app/workers/monitor_poll_worker.py`, `apps/backend/src/app/core/subjects.py`
- Test: `apps/backend/tests/services/test_monitor_poll_worker.py` (extend)

**Interfaces:**
- Consumes: `CheckResult` (Task 2), `apply_result` (Task 5), `nats_client.js_publish(subject, payload_dict)`, `get_redis()` from `app.core.redis`.
- Produces:
  - NATS subjects (add to `core/subjects.py`): `MONITOR_ALERT_DOWN = "alert.monitor.down.{item_id}"`, `MONITOR_ALERT_RECOVERED = "alert.monitor.recovered.{item_id}"` plus payload helper `monitor_alert_payload(...)`.
  - Redis pub/sub channel `monitor:{item_id}` with payload `{"monitor_id", "status", "msg", "ts"}`.
  - `poll_one(item) -> tuple[SampleRow, bool, str]` (row, up, msg); `process_batch` unchanged signature, now applies state + publishes.

- [ ] **Step 1: Add subjects + payload helper**

In `core/subjects.py`, under the Notifications/Alerts section:

```python
MONITOR_ALERT_DOWN = "alert.monitor.down.{item_id}"  # formatted at publish time
MONITOR_ALERT_RECOVERED = "alert.monitor.recovered.{item_id}"
```

And with the payload helpers:

```python
def monitor_alert_payload(
    item_id: int,
    name: str,
    status: str,
    message: str,
    occurred_at: str,
) -> dict:
    severity = "critical" if status == "down" else "info"
    title = f"Monitor {name} is {status.upper()}"
    return {
        "title": title,
        "message": message,
        "severity": severity,
        "monitor_id": item_id,
        "monitor_name": name,
        "status": status,
        "occurred_at": occurred_at,
    }
```

- [ ] **Step 2: Write failing worker tests**

Append to `tests/services/test_monitor_poll_worker.py`:

```python
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.db.models import MonitorItem
from app.services.monitoring.collectors import CheckResult, Sample
from app.workers import monitor_poll_worker as mpw


def _register_fake(check_type, result):
    from app.services.monitoring import collectors
    collectors.COLLECTORS[check_type] = lambda host, params: result


async def test_poll_one_returns_up_and_msg():
    _register_fake("fake_up", CheckResult(up=True, samples=[Sample("avail", 1.0)], msg="ok"))
    row, up, msg = await mpw.poll_one(
        {"item_id": 1, "target_type": "ip", "target_id": None,
         "host": "192.0.2.1", "check_type": "fake_up", "params": {}}
    )
    assert up is True and msg == "ok"
    assert row[0] == 1


async def test_process_batch_applies_state_and_publishes(db_session_factory, db_session):
    item = MonitorItem(
        name="web", host="192.0.2.1", check_type="fake_down", target_type=None,
        max_retries=0, interval_secs=60, last_status="up",
        next_due_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    db_session.add(item)
    db_session.commit()
    _register_fake("fake_down", CheckResult(up=False, samples=[Sample("avail", 0.0)], msg="dead"))

    published = []

    async def fake_js_publish(subject, payload):
        published.append((subject, payload))
        return True

    fake_redis = AsyncMock()
    with (
        patch.object(mpw.nats_client, "js_publish", side_effect=fake_js_publish),
        patch.object(mpw, "get_redis", AsyncMock(return_value=fake_redis)),
    ):
        await mpw.process_batch(
            [{"item_id": item.id, "target_type": None, "target_id": None,
              "host": item.host, "check_type": "fake_down", "params": {}}],
            db_session_factory,
        )

    db_session.expire_all()
    fresh = db_session.get(MonitorItem, item.id)
    assert fresh.last_status == "down"
    assert any(s.startswith("alert.monitor.down.") for s, _ in published)
    fake_redis.publish.assert_awaited()
```

(If `db_session_factory` doesn't exist in `tests/conftest.py`, use the same factory fixture pattern the existing e2e test `tests/integration/test_monitor_engine_e2e.py` uses for `SessionLocal`-style factories — reuse, don't invent.)

- [ ] **Step 3: Run to verify failure**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_poll_worker.py -v`
Expected: new tests FAIL (`poll_one` returns a 5-tuple SampleRow today, no `get_redis` attr on module).

- [ ] **Step 4: Rework the worker**

In `workers/monitor_poll_worker.py`:

```python
from app.core.redis import get_redis
from app.core.subjects import (
    MONITOR_ALERT_DOWN,
    MONITOR_ALERT_RECOVERED,
    monitor_alert_payload,
)
from app.services.monitoring.collectors import COLLECTORS, CheckResult, Sample
from app.services.monitoring.state import AppliedTransition, apply_result
```

Replace `poll_one`:

```python
async def poll_one(item: dict) -> tuple[SampleRow, bool, str]:
    """Run the check for one monitor in a worker thread. Never raises."""
    ts = datetime.now(UTC)
    collector = COLLECTORS.get(item["check_type"])
    if collector is None:
        row = (
            item["item_id"], item["target_type"], item["target_id"],
            [Sample("avail", 0.0, error_reason="unknown_check_type")], ts,
        )
        return row, False, f"unknown check type {item['check_type']!r}"
    try:
        async with _sema:
            result: CheckResult = await asyncio.to_thread(
                collector, item["host"], item["params"]
            )
    except Exception as exc:  # noqa: BLE001 — a probe crash is a down datum
        logger.debug("Check crashed for monitor %s: %s", item["item_id"], exc)
        result = CheckResult(
            up=False,
            samples=[Sample("avail", 0.0, error_reason="collector_error")],
            msg=f"check crashed: {type(exc).__name__}",
        )
    row = (item["item_id"], item["target_type"], item["target_id"], result.samples, ts)
    return row, result.up, result.msg
```

Replace `process_batch`:

```python
async def process_batch(items: list[dict], db_factory: Callable[[], Any]) -> int:
    outcomes = await asyncio.gather(*(poll_one(i) for i in items))
    transitions: list[AppliedTransition] = []
    db = db_factory()
    try:
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


async def _publish_transitions(transitions: list[AppliedTransition]) -> None:
    for t in transitions:
        if t.notify == "down":
            subject = MONITOR_ALERT_DOWN.format(item_id=t.item_id)
        elif t.notify == "recovered":
            subject = MONITOR_ALERT_RECOVERED.format(item_id=t.item_id)
        else:
            continue
        payload = monitor_alert_payload(
            t.item_id, t.name, t.status_to, t.msg, t.occurred_at.isoformat()
        )
        try:
            await nats_client.js_publish(subject, payload)
        except Exception as exc:  # noqa: BLE001 — alerting is best-effort here
            logger.warning("Failed to publish monitor alert %s: %s", subject, exc)


async def _publish_live_status(outcomes: list[tuple[SampleRow, bool, str]]) -> None:
    redis = await get_redis()
    if redis is None:
        return
    for row, up, msg in outcomes:
        item_id, _, _, _, ts = row
        payload = json.dumps(
            {"monitor_id": item_id, "status": "up" if up else "down",
             "msg": msg, "ts": ts.isoformat()}
        )
        try:
            await redis.publish(f"monitor:{item_id}", payload)
        except Exception:  # noqa: BLE001 — live push degrades silently
            return
```

Note: the live-status payload reports the raw check outcome; the authoritative
status (including pending) comes from REST. Keep it simple in slice 1.

- [ ] **Step 5: Run worker + state tests**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_poll_worker.py tests/services/test_monitor_state.py tests/integration/test_monitor_engine_e2e.py -v`
Expected: PASS (update the e2e test's expectations if it asserted the old `poll_one` return shape).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/workers/monitor_poll_worker.py apps/backend/src/app/core/subjects.py apps/backend/tests
git commit -m "feat(monitoring): poll worker applies state machine, publishes alerts and live status"
```

---

### Task 7: API schemas + service rework (monitor-id CRUD)

**Files:**
- Rewrite: `apps/backend/src/app/schemas/monitor.py`, `apps/backend/src/app/services/monitor_service.py`
- Test: `apps/backend/tests/services/test_monitor_service.py` (new; the old service behavior is covered indirectly by API tests updated in Task 8)

**Interfaces:**
- Consumes: `MonitorItem`, `MonitorEvent` (Task 1); `TelemetryTimeseries`; `nats_client.js_publish` with `MONITOR_POLL_ITEM`.
- Produces (service functions used by Task 8's router):
  - `list_monitors(db, *, target_type=None, target_id=None, enabled=None) -> list[dict]`
  - `get_monitor(db, monitor_id: int) -> dict | None`
  - `create_monitor(db, payload: MonitorCreate) -> dict`
  - `update_monitor(db, monitor_id: int, payload: MonitorUpdate) -> dict | None`
  - `delete_monitor(db, monitor_id: int) -> bool`
  - `set_paused(db, monitor_id: int, paused: bool) -> dict | None` (toggles `enabled`, records `paused`/`resumed` event)
  - `get_events(db, monitor_id: int, limit: int = 50) -> list[dict]`
  - `get_history(db, monitor_id: int, metric: str = "latency_ms", hours: int = 24) -> list[dict]`
  - `get_uptime(db, monitor_id: int) -> dict` (`{"pct_24h": float | None}` — mean of `avail` samples over 24 h)
  - `run_immediate_check(db, monitor_id: int) -> bool`
  - `list_hardware_summaries(db, hardware_ids=None) -> list[dict]` (keeps today's synthesized per-hardware view for MapPage; reuse the existing `_synthesize_monitor` unchanged)
- Produces (schemas): `MonitorCreate`, `MonitorUpdate`, `MonitorRead`, `MonitorEventRead`, config models `IcmpConfig`, `TcpConfig`, `HttpConfig`, `DnsConfig`, and `CONFIG_MODELS: dict[str, type[BaseModel]]`.

- [ ] **Step 1: Write failing schema/service tests**

`tests/services/test_monitor_service.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.db.models import MonitorEvent, MonitorItem
from app.schemas.monitor import HttpConfig, MonitorCreate
from app.services import monitor_service


def test_create_validates_config_per_type():
    payload = MonitorCreate(
        name="site", check_type="http", host="192.0.2.4",
        config={"url": "https://example.com", "accepted_statuses": ["200-299"]},
    )
    assert payload.config["url"] == "https://example.com"

    with pytest.raises(ValidationError):
        MonitorCreate(
            name="bad", check_type="http", host="h",
            config={"accepted_statuses": "not-a-list"},
        )


def test_http_config_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        HttpConfig(url="http://x/", bogus_field=1)


def test_create_and_get_roundtrip(db_session):
    payload = MonitorCreate(
        name="dns watch", check_type="dns", host="example.com",
        config={"record_type": "A"}, interval_secs=120, max_retries=2,
    )
    created = monitor_service.create_monitor(db_session, payload)
    assert created["id"] > 0
    fetched = monitor_service.get_monitor(db_session, created["id"])
    assert fetched["name"] == "dns watch"
    assert fetched["check_type"] == "dns"
    assert fetched["config"] == {"record_type": "A"}
    assert fetched["status"] == "pending"


def test_pause_records_event_and_disables(db_session):
    payload = MonitorCreate(name="p", check_type="icmp", host="192.0.2.9", config={})
    created = monitor_service.create_monitor(db_session, payload)
    paused = monitor_service.set_paused(db_session, created["id"], True)
    assert paused["enabled"] is False
    events = monitor_service.get_events(db_session, created["id"])
    assert events[0]["event_type"] == "paused"


def test_list_filters_by_target(db_session):
    monitor_service.create_monitor(db_session, MonitorCreate(
        name="a", check_type="icmp", host="192.0.2.1", config={},
        target_type="hardware", target_id=42,
    ))
    monitor_service.create_monitor(db_session, MonitorCreate(
        name="b", check_type="icmp", host="192.0.2.2", config={},
    ))
    linked = monitor_service.list_monitors(db_session, target_type="hardware", target_id=42)
    assert [m["name"] for m in linked] == ["a"]
    everything = monitor_service.list_monitors(db_session)
    assert len(everything) >= 2
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_service.py -v`
Expected: FAIL — imports (`HttpConfig`, new `MonitorCreate` shape) don't exist.

- [ ] **Step 3: Rewrite `schemas/monitor.py`**

```python
"""Monitor API schemas with per-check-type config validation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CheckType = Literal["icmp", "tcp", "http", "dns"]
TargetType = Literal["hardware", "compute_unit", "external_node", "service", "ip"]


class _StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IcmpConfig(_StrictConfig):
    packet_count: int = Field(default=5, ge=1, le=20)
    timeout: float = Field(default=1.5, gt=0, le=30)


class TcpConfig(_StrictConfig):
    port: int | None = Field(default=None, ge=1, le=65535)
    ports: list[int] | None = None
    timeout: float = Field(default=1.0, gt=0, le=30)


class HttpConfig(_StrictConfig):
    url: str | None = None
    method: Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    timeout: float = Field(default=10.0, gt=0, le=120)
    auth_type: Literal["none", "basic", "bearer"] = "none"
    username: str | None = None
    password: str | None = None
    token: str | None = None
    accepted_statuses: list[str] = Field(default_factory=lambda: ["200-299"])
    keyword: str | None = None
    keyword_invert: bool = False
    json_path: str | None = None
    expected_value: str | None = None
    verify_tls: bool = True
    follow_redirects: bool = True


class DnsConfig(_StrictConfig):
    record_type: Literal[
        "A", "AAAA", "CNAME", "MX", "TXT", "NS", "SOA", "PTR", "SRV", "CAA"
    ] = "A"
    resolver: str | None = None
    port: int = Field(default=53, ge=1, le=65535)
    expected_values: list[str] = Field(default_factory=list)
    timeout: float = Field(default=5.0, gt=0, le=30)


CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "icmp": IcmpConfig,
    "tcp": TcpConfig,
    "http": HttpConfig,
    "dns": DnsConfig,
}


class _MonitorBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    check_type: CheckType
    host: str = Field(min_length=1, max_length=255)
    config: dict = Field(default_factory=dict)
    interval_secs: int = Field(default=60, ge=10, le=86400)
    max_retries: int = Field(default=0, ge=0, le=10)
    retry_interval_secs: int | None = Field(default=None, ge=5, le=86400)
    enabled: bool = True
    target_type: TargetType | None = None
    target_id: int | None = None

    @model_validator(mode="after")
    def _validate_config(self) -> "_MonitorBase":
        model = CONFIG_MODELS[self.check_type]
        self.config = model(**self.config).model_dump(exclude_none=True)
        return self


class MonitorCreate(_MonitorBase):
    pass


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict | None = None
    interval_secs: int | None = Field(default=None, ge=10, le=86400)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    retry_interval_secs: int | None = Field(default=None, ge=5, le=86400)
    enabled: bool | None = None
    target_type: TargetType | None = None
    target_id: int | None = None


class MonitorRead(BaseModel):
    id: int
    name: str
    check_type: str
    host: str
    config: dict
    interval_secs: int
    max_retries: int
    retry_interval_secs: int | None
    enabled: bool
    target_type: str | None
    target_id: int | None
    status: str
    retries: int
    last_polled_at: datetime | None
    last_status_change_at: datetime | None
    uptime_pct_24h: float | None = None
    latency_ms: float | None = None
    created_at: datetime
    updated_at: datetime


class MonitorEventRead(BaseModel):
    id: int
    monitor_id: int
    event_type: str
    status_from: str | None
    status_to: str
    msg: str
    duration_secs: float | None
    created_at: datetime


class MonitorHistoryPoint(BaseModel):
    ts: datetime
    value: float


class HardwareMonitorSummary(BaseModel):
    """Legacy synthesized per-hardware view (map + integrations panels)."""

    id: int
    hardware_id: int
    enabled: bool
    interval_secs: int
    probe_methods: list[str]
    last_status: str
    last_checked_at: str | None
    latency_ms: float | None
    consecutive_failures: int
    uptime_pct_24h: float | None
    created_at: str
    updated_at: str
```

Delete the old `MonitorCreate/MonitorRead/MonitorUpdate/UptimeEventRead` definitions (`UptimeEventRead` consumers are replaced in Task 8).

- [ ] **Step 4: Rewrite `services/monitor_service.py`**

Keep `_synthesize_monitor` and the hardware-grouping logic **verbatim** but expose it only through `list_hardware_summaries`. Replace the rest:

```python
"""Monitor service: monitor-id CRUD, events, history, and hardware summaries."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.nats_client import nats_client
from app.core.subjects import MONITOR_POLL_ITEM
from app.db.models import MonitorEvent, MonitorItem, TelemetryTimeseries
from app.schemas.monitor import MonitorCreate, MonitorUpdate
from app.services.monitoring.state import PENDING

logger = logging.getLogger(__name__)


def _to_dict(item: MonitorItem, uptime_pct_24h: float | None = None,
             latency_ms: float | None = None) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "check_type": item.check_type,
        "host": item.host,
        "config": item.params or {},
        "interval_secs": item.interval_secs,
        "max_retries": item.max_retries,
        "retry_interval_secs": item.retry_interval_secs,
        "enabled": item.enabled,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "status": item.last_status or PENDING,
        "retries": item.consecutive_failures,
        "last_polled_at": item.last_polled_at,
        "last_status_change_at": item.last_status_change_at,
        "uptime_pct_24h": uptime_pct_24h,
        "latency_ms": latency_ms,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _latest_metric_map(db: Session, item_ids: list[int], metric: str) -> dict[int, float]:
    if not item_ids:
        return {}
    rows = (
        db.query(TelemetryTimeseries)
        .filter(TelemetryTimeseries.item_id.in_(item_ids),
                TelemetryTimeseries.metric == metric)
        .distinct(TelemetryTimeseries.item_id)
        .order_by(TelemetryTimeseries.item_id, TelemetryTimeseries.ts.desc())
        .all()
    )
    return {r.item_id: r.value for r in rows}


def _uptime_pct_map(db: Session, item_ids: list[int], hours: int = 24) -> dict[int, float]:
    if not item_ids:
        return {}
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = db.execute(
        select(
            TelemetryTimeseries.item_id,
            func.avg(TelemetryTimeseries.value),
        )
        .where(
            TelemetryTimeseries.item_id.in_(item_ids),
            TelemetryTimeseries.metric == "avail",
            TelemetryTimeseries.ts >= since,
        )
        .group_by(TelemetryTimeseries.item_id)
    ).all()
    return {item_id: round(avg * 100, 1) for item_id, avg in rows if avg is not None}


def list_monitors(
    db: Session,
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    enabled: bool | None = None,
) -> list[dict]:
    query = select(MonitorItem).order_by(MonitorItem.name, MonitorItem.id)
    if target_type is not None:
        query = query.where(MonitorItem.target_type == target_type)
    if target_id is not None:
        query = query.where(MonitorItem.target_id == target_id)
    if enabled is not None:
        query = query.where(MonitorItem.enabled == enabled)
    items = list(db.scalars(query).all())
    ids = [i.id for i in items]
    uptimes = _uptime_pct_map(db, ids)
    latencies = _latest_metric_map(db, ids, "latency_ms")
    return [_to_dict(i, uptimes.get(i.id), latencies.get(i.id)) for i in items]


def get_monitor(db: Session, monitor_id: int) -> dict | None:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return None
    uptimes = _uptime_pct_map(db, [item.id])
    latencies = _latest_metric_map(db, [item.id], "latency_ms")
    return _to_dict(item, uptimes.get(item.id), latencies.get(item.id))


def create_monitor(db: Session, payload: MonitorCreate) -> dict:
    item = MonitorItem(
        name=payload.name,
        check_type=payload.check_type,
        host=payload.host,
        params=payload.config,
        interval_secs=payload.interval_secs,
        max_retries=payload.max_retries,
        retry_interval_secs=payload.retry_interval_secs,
        enabled=payload.enabled,
        target_type=payload.target_type,
        target_id=payload.target_id,
        last_status=PENDING,
        next_due_at=datetime.now(UTC),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_dict(item)


def update_monitor(db: Session, monitor_id: int, payload: MonitorUpdate) -> dict | None:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return None
    data = payload.model_dump(exclude_unset=True)
    if "config" in data and data["config"] is not None:
        from app.schemas.monitor import CONFIG_MODELS

        model = CONFIG_MODELS[item.check_type]
        data["config"] = model(**data["config"]).model_dump(exclude_none=True)
        item.params = data.pop("config")
    for field in ("name", "host", "interval_secs", "max_retries",
                  "retry_interval_secs", "enabled", "target_type", "target_id"):
        if field in data:
            setattr(item, field, data[field])
    db.commit()
    db.refresh(item)
    return _to_dict(item)


def delete_monitor(db: Session, monitor_id: int) -> bool:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return False
    db.delete(item)
    db.commit()
    return True


def set_paused(db: Session, monitor_id: int, paused: bool) -> dict | None:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return None
    item.enabled = not paused
    if not paused:
        item.next_due_at = datetime.now(UTC)
    db.add(MonitorEvent(
        item_id=item.id,
        event_type="paused" if paused else "resumed",
        status_from=item.last_status,
        status_to=item.last_status or PENDING,
        msg="paused by user" if paused else "resumed by user",
    ))
    db.commit()
    db.refresh(item)
    return _to_dict(item)


def get_events(db: Session, monitor_id: int, limit: int = 50) -> list[dict]:
    rows = db.scalars(
        select(MonitorEvent)
        .where(MonitorEvent.item_id == monitor_id)
        .order_by(MonitorEvent.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": e.id,
            "monitor_id": e.item_id,
            "event_type": e.event_type,
            "status_from": e.status_from,
            "status_to": e.status_to,
            "msg": e.msg,
            "duration_secs": e.duration_secs,
            "created_at": e.created_at,
        }
        for e in rows
    ]


def get_history(
    db: Session, monitor_id: int, metric: str = "latency_ms", hours: int = 24
) -> list[dict]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        db.query(TelemetryTimeseries)
        .filter(
            TelemetryTimeseries.item_id == monitor_id,
            TelemetryTimeseries.metric == metric,
            TelemetryTimeseries.ts >= since,
        )
        .order_by(TelemetryTimeseries.ts.asc())
        .all()
    )
    return [{"ts": r.ts, "value": r.value} for r in rows]


def get_uptime(db: Session, monitor_id: int) -> dict:
    return {"pct_24h": _uptime_pct_map(db, [monitor_id]).get(monitor_id)}


def run_immediate_check(db: Session, monitor_id: int) -> bool:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return False
    payload = {
        "item_id": item.id,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "host": item.host,
        "check_type": item.check_type,
        "params": item.params,
        "interval_secs": item.interval_secs,
    }
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(nats_client.js_publish(MONITOR_POLL_ITEM, payload))
        return True
    except RuntimeError:
        logger.warning("No running async loop to publish immediate check.")
        return False
```

Then append the retained legacy view (moved, not rewritten):

```python
# ── Hardware summary view (map + integrations panels) ─────────────────────────
# _synthesize_monitor: keep the existing implementation verbatim (it reads
# DailyUptimeStats + latest telemetry per item). Import Hardware and
# DailyUptimeStats as before.


def list_hardware_summaries(db: Session, hardware_ids: list[int] | None = None) -> list[dict]:
    query = select(MonitorItem).where(MonitorItem.target_type == "hardware")
    if hardware_ids is not None:
        query = query.where(MonitorItem.target_id.in_(hardware_ids))
    items = db.scalars(query).all()
    grouped: dict[int, list[MonitorItem]] = {}
    for item in items:
        if item.target_id is not None:
            grouped.setdefault(item.target_id, []).append(item)
    res = []
    for hw_id, hw_items in grouped.items():
        synthesized = _synthesize_monitor(db, hw_id, hw_items)
        if synthesized:
            res.append(synthesized)
    return res
```

Note: `run_immediate_check` also fixes a latent bug — the old code passed
`json.dumps(payload).encode()` to `js_publish`, which everywhere else takes a dict.

- [ ] **Step 5: Run tests**

Run: `cd apps/backend && python -m pytest tests/services/test_monitor_service.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/schemas/monitor.py apps/backend/src/app/services/monitor_service.py apps/backend/tests/services/test_monitor_service.py
git commit -m "feat(monitoring): monitor-id service layer with per-type config validation"
```

---

### Task 8: REST API rework

**Files:**
- Rewrite: `apps/backend/src/app/api/monitor.py`
- Test: `apps/backend/tests/api/test_monitor_api.py` (new; delete/absorb any old API tests that hit `/monitors/{hardware_id}`)

**Interfaces:**
- Consumes: every service function from Task 7; `require_write_auth`, `get_db` (existing).
- Produces REST (mounted at `/api/v1/monitors`, mount unchanged in `main.py:1685`):
  - `GET  ""` — list; query params `target_type`, `target_id`, `enabled`
  - `POST ""` — create (write auth)
  - `GET  "/hardware-summary"` — legacy per-hardware view (MapPage)
  - `GET  "/{monitor_id}"`, `PATCH "/{monitor_id}"`, `DELETE "/{monitor_id}"`
  - `POST "/{monitor_id}/pause"`, `POST "/{monitor_id}/resume"`, `POST "/{monitor_id}/check"`
  - `GET  "/{monitor_id}/events?limit="`, `GET "/{monitor_id}/history?metric=&hours="`, `GET "/{monitor_id}/uptime"`

- [ ] **Step 1: Write failing API tests**

`tests/api/test_monitor_api.py` (follow the auth/client fixture pattern used by neighboring files in `tests/api/`):

```python
def _create(client, **overrides):
    payload = {
        "name": "edge web", "check_type": "http", "host": "192.0.2.7",
        "config": {"url": "http://192.0.2.7/health", "accepted_statuses": ["200-299"]},
        "interval_secs": 60, "max_retries": 2,
    }
    payload.update(overrides)
    return client.post("/api/v1/monitors", json=payload)


def test_create_and_get(auth_client):
    resp = _create(auth_client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["config"]["url"] == "http://192.0.2.7/health"

    got = auth_client.get(f"/api/v1/monitors/{body['id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "edge web"


def test_create_invalid_config_422(auth_client):
    resp = _create(auth_client, config={"nonsense": True})
    assert resp.status_code == 422


def test_list_filter(auth_client):
    _create(auth_client, name="linked", target_type="hardware", target_id=1)
    resp = auth_client.get("/api/v1/monitors", params={"target_type": "hardware", "target_id": 1})
    assert resp.status_code == 200
    assert all(m["target_type"] == "hardware" for m in resp.json())


def test_pause_resume(auth_client):
    mid = _create(auth_client).json()["id"]
    assert auth_client.post(f"/api/v1/monitors/{mid}/pause").json()["enabled"] is False
    assert auth_client.post(f"/api/v1/monitors/{mid}/resume").json()["enabled"] is True
    events = auth_client.get(f"/api/v1/monitors/{mid}/events").json()
    assert {e["event_type"] for e in events} >= {"paused", "resumed"}


def test_missing_monitor_404(auth_client):
    assert auth_client.get("/api/v1/monitors/999999").status_code == 404
    assert auth_client.delete("/api/v1/monitors/999999").status_code == 404


def test_uptime_and_history_empty_ok(auth_client):
    mid = _create(auth_client).json()["id"]
    assert auth_client.get(f"/api/v1/monitors/{mid}/uptime").json() == {"pct_24h": None}
    assert auth_client.get(f"/api/v1/monitors/{mid}/history").json() == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/backend && python -m pytest tests/api/test_monitor_api.py -v`
Expected: FAIL (old hardware-id routes).

- [ ] **Step 3: Rewrite `api/monitor.py`**

```python
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.monitor import (
    HardwareMonitorSummary,
    MonitorCreate,
    MonitorEventRead,
    MonitorHistoryPoint,
    MonitorRead,
    MonitorUpdate,
)
from app.services import monitor_service

_NOT_FOUND = "Monitor not found"
_logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitors"])


@router.get("", response_model=list[MonitorRead])
def list_monitors(
    target_type: str | None = Query(default=None),
    target_id: int | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Any:
    return monitor_service.list_monitors(
        db, target_type=target_type, target_id=target_id, enabled=enabled
    )


@router.get("/hardware-summary", response_model=list[HardwareMonitorSummary])
def hardware_summary(db: Session = Depends(get_db)) -> Any:
    """Per-hardware monitor rollup for the map and integrations panels."""
    return monitor_service.list_hardware_summaries(db)


@router.post("", response_model=MonitorRead)
def create_monitor(
    payload: MonitorCreate,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    return monitor_service.create_monitor(db, payload)


@router.get("/{monitor_id}", response_model=MonitorRead)
def get_monitor(monitor_id: int, db: Session = Depends(get_db)) -> Any:
    monitor = monitor_service.get_monitor(db, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor


@router.patch("/{monitor_id}", response_model=MonitorRead)
def update_monitor(
    monitor_id: int,
    payload: MonitorUpdate,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    monitor = monitor_service.update_monitor(db, monitor_id, payload)
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor


@router.delete("/{monitor_id}", status_code=204)
def delete_monitor(
    monitor_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> None:
    if not monitor_service.delete_monitor(db, monitor_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)


@router.post("/{monitor_id}/pause", response_model=MonitorRead)
def pause_monitor(
    monitor_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    monitor = monitor_service.set_paused(db, monitor_id, True)
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor


@router.post("/{monitor_id}/resume", response_model=MonitorRead)
def resume_monitor(
    monitor_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    monitor = monitor_service.set_paused(db, monitor_id, False)
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor


@router.post("/{monitor_id}/check", response_model=MonitorRead)
def run_immediate_check(
    monitor_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    monitor = monitor_service.get_monitor(db, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    monitor_service.run_immediate_check(db, monitor_id)
    return monitor


@router.get("/{monitor_id}/events", response_model=list[MonitorEventRead])
def get_events(
    monitor_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Any:
    if not monitor_service.get_monitor(db, monitor_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor_service.get_events(db, monitor_id, limit=limit)


@router.get("/{monitor_id}/history", response_model=list[MonitorHistoryPoint])
def get_history(
    monitor_id: int,
    metric: str = Query(default="latency_ms"),
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
) -> Any:
    if not monitor_service.get_monitor(db, monitor_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor_service.get_history(db, monitor_id, metric=metric, hours=hours)


@router.get("/{monitor_id}/uptime")
def get_uptime(monitor_id: int, db: Session = Depends(get_db)) -> Any:
    if not monitor_service.get_monitor(db, monitor_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor_service.get_uptime(db, monitor_id)
```

**Route-order note:** `/hardware-summary` is declared before `/{monitor_id}` so it isn't captured by the int path param.

- [ ] **Step 4: Fix old API-test fallout**

Run: `cd apps/backend && grep -rn "monitors/" tests/ --include="*.py" -l` and update every test that hit hardware-id routes (e.g. anything calling `/api/v1/monitors/{hardware_id}` semantics) to either the new monitor-id routes or `/hardware-summary`.

- [ ] **Step 5: Run API tests**

Run: `cd apps/backend && python -m pytest tests/api/test_monitor_api.py tests/api -k monitor -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/api/monitor.py apps/backend/tests
git commit -m "feat(monitoring): monitor-id REST API with pause/resume, events, history, uptime"
```

---

### Task 9: WebSocket bridge

**Files:**
- Create: `apps/backend/src/app/api/ws_monitors.py`
- Modify: `apps/backend/src/app/main.py` (mount next to the ws_telemetry router)
- Test: `apps/backend/tests/api/test_ws_monitors.py` (new)

**Interfaces:**
- Consumes: Redis pub/sub channels `monitor:{id}` (published by Task 6).
- Produces: `WS /api/v1/monitors/stream`. Protocol identical to `ws_telemetry.py`: first message JWT; then `{"subscribe": [monitor_ids]}` / `{"unsubscribe": [...]}` / ping-pong; server pushes `{"type": "monitor_status", "monitor_id": N, "status": "up|down", "msg": "...", "ts": "..."}`.

- [ ] **Step 1: Implement by cloning the established pattern**

Copy `apps/backend/src/app/api/ws_telemetry.py` to `apps/backend/src/app/api/ws_monitors.py`, then apply exactly these deltas (keep the auth handshake, WSS enforcement, CIDR whitelist, per-IP caps, Redis-degradation, and ping/pong logic **identical**):

- Module docstring: describe `WS /api/v1/monitors/stream`, channels `monitor:{id}`, push type `monitor_status`.
- Env knobs: `CB_WS_MON_MAX_CONNECTIONS` (default 100), `CB_WS_MON_MAX_PER_IP` (default 10); `_MAX_SUBSCRIPTIONS = 500`.
- Channel prefix: `telemetry:{entity_id}` → `monitor:{monitor_id}`.
- Outbound frame: where ws_telemetry emits `{"type": "telemetry", "entity_id": ...}`, emit instead:

```python
await websocket.send_text(json.dumps({
    "type": "monitor_status",
    "monitor_id": monitor_id,
    **payload,  # status, msg, ts from the Redis message
}))
```

- Route decorator: `@router.websocket("/monitors/stream")` (matching how ws_telemetry declares its path — mirror its prefixing so the final URL is `/api/v1/monitors/stream`).

In `main.py`, find where the ws_telemetry router is included and add the new router with the same include pattern:

```python
from app.api.ws_monitors import router as ws_monitors_router
# ... alongside the ws_telemetry include:
app.include_router(ws_monitors_router, prefix="/api/v1")
```

(Match the exact prefix style used for `ws_telemetry` in main.py — copy its `include_router` line and change the router name.)

- [ ] **Step 2: Write the smoke test**

`tests/api/test_ws_monitors.py`, modeled on the existing `tests/api` WS test for telemetry (find it with `grep -rln "telemetry/stream" tests/`; clone its fixture usage):

```python
def test_ws_monitors_requires_auth(client):
    with client.websocket_connect("/api/v1/monitors/stream") as ws:
        ws.send_text("not-a-valid-token")
        msg = ws.receive_json()
        assert msg.get("error") in {"unauthorized", "auth_timeout"}


def test_ws_monitors_happy_path(client, auth_token):
    with client.websocket_connect("/api/v1/monitors/stream") as ws:
        ws.send_text(auth_token)
        assert ws.receive_json() == {"status": "connected"}
        ws.send_text('{"subscribe": [1, 2]}')
        ws.send_text('{"type": "ping"}')
        assert ws.receive_json()["type"] == "pong"
```

Adjust fixture names to whatever the telemetry WS test actually uses.

- [ ] **Step 3: Run tests**

Run: `cd apps/backend && python -m pytest tests/api/test_ws_monitors.py -v`
Expected: PASS (Redis-unavailable degradation keeps the socket open — same as telemetry tests).

- [ ] **Step 4: Commit**

```bash
git add apps/backend/src/app/api/ws_monitors.py apps/backend/src/app/main.py apps/backend/tests/api/test_ws_monitors.py
git commit -m "feat(monitoring): live monitor status WebSocket bridge"
```

---

### Task 10: Frontend API client + live-status hook + legacy-caller migration

**Files:**
- Rewrite: `apps/frontend/src/api/monitor.js`
- Create: `apps/frontend/src/hooks/useMonitorStream.js`
- Modify: `apps/frontend/src/pages/MapPage.jsx`, `apps/frontend/src/hooks/useMapRealTimeUpdates.js`, `apps/frontend/src/components/settings/IntegrationsManager.jsx`, `apps/frontend/src/__tests__/map-page.test.jsx`, `apps/frontend/src/__tests__/map-realtime-updates.test.jsx`

**Interfaces:**
- Produces `api/monitor.js` exports: `listMonitors(params)`, `getMonitor(id)`, `createMonitor(data)`, `updateMonitor(id, data)`, `deleteMonitor(id)`, `pauseMonitor(id)`, `resumeMonitor(id)`, `runCheck(id)`, `getMonitorEvents(id, limit)`, `getMonitorHistory(id, {metric, hours})`, `getMonitorUptime(id)`, `getHardwareSummary()`.
- Produces `useMonitorStream({ monitorIds }) -> { statuses: Map<monitorId, {status, msg, ts}>, connected }`.

- [ ] **Step 1: Rewrite `api/monitor.js`**

```javascript
import client from './client.jsx';

export const listMonitors = (params = {}) => client.get('/monitors', { params });
export const getMonitor = (id) => client.get(`/monitors/${id}`);
export const createMonitor = (data) => client.post('/monitors', data);
export const updateMonitor = (id, data) => client.patch(`/monitors/${id}`, data);
export const deleteMonitor = (id) => client.delete(`/monitors/${id}`);
export const pauseMonitor = (id) => client.post(`/monitors/${id}/pause`);
export const resumeMonitor = (id) => client.post(`/monitors/${id}/resume`);
export const runCheck = (id) => client.post(`/monitors/${id}/check`);
export const getMonitorEvents = (id, limit = 50) =>
  client.get(`/monitors/${id}/events`, { params: { limit } });
export const getMonitorHistory = (id, { metric = 'latency_ms', hours = 24 } = {}) =>
  client.get(`/monitors/${id}/history`, { params: { metric, hours } });
export const getMonitorUptime = (id) => client.get(`/monitors/${id}/uptime`);
export const getHardwareSummary = () => client.get('/monitors/hardware-summary');
```

(Check the current file's import line first — mirror how it imports `client` today.)

- [ ] **Step 2: Migrate legacy callers**

`grep -rn "listMonitors\|getMonitorHistory\|runImmediateCheck\|from '../api/monitor'" apps/frontend/src --include="*.jsx" --include="*.js"` and in `MapPage.jsx`, `useMapRealTimeUpdates.js`, `IntegrationsManager.jsx` (and their two tests): replace hardware-keyed `listMonitors()` calls with `getHardwareSummary()` — the response shape is identical to today's list response (per-hardware synthesized rows), so only the function name changes. Update the two `__tests__` mocks to mock `getHardwareSummary` instead.

- [ ] **Step 3: Create `useMonitorStream.js`**

Clone `apps/frontend/src/hooks/useTelemetryStream.js` (223 lines) into `useMonitorStream.js` with exactly these deltas — keep backoff, visibility-reconnect, hard-stop errors, ping/pong, and auth handshake identical:

- `getTelemetryWsUrl` → `getMonitorsWsUrl`, path `/api/v1/monitors/stream`.
- Hook signature: `useMonitorStream({ monitorIds = [] } = {})`; internal ref `monitorIdsRef`.
- Emitter: `export const monitorStatusEmitter = mitt();`
- Message handling block (replacing the `msg.type === 'telemetry'` branch):

```javascript
      if (msg.type === 'monitor_status' && msg.monitor_id != null) {
        setStatuses((prev) => {
          const next = new Map(prev);
          next.set(msg.monitor_id, msg);
          return next;
        });
        monitorStatusEmitter.emit(`monitor:${msg.monitor_id}`, msg);
        monitorStatusEmitter.emit('monitor:any', msg);
      }
```

- State variable named `statuses`; return `{ statuses, connected }`.
- Re-subscribe effect keys off `monitorIds.join(',')`.

- [ ] **Step 4: Run frontend tests**

Run: `cd apps/frontend && npx vitest run src/__tests__/map-page.test.jsx src/__tests__/map-realtime-updates.test.jsx` (use the repo's actual test runner — check `package.json` `scripts.test` and use that).
Expected: PASS after mock updates.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/api/monitor.js apps/frontend/src/hooks/useMonitorStream.js \
  apps/frontend/src/pages/MapPage.jsx apps/frontend/src/hooks/useMapRealTimeUpdates.js \
  apps/frontend/src/components/settings/IntegrationsManager.jsx apps/frontend/src/__tests__
git commit -m "feat(frontend): monitor-id API client, live status hook, hardware-summary migration"
```

---

### Task 11: Monitors dashboard — list page, check-history bar, form

**Files:**
- Create: `apps/frontend/src/pages/MonitorsPage.jsx`, `apps/frontend/src/components/monitors/CheckHistoryBar.jsx`, `apps/frontend/src/components/monitors/MonitorForm.jsx`
- Modify: `apps/frontend/src/App.jsx` (route), `apps/frontend/src/data/navigation.js` (nav entry)

**Interfaces:**
- Consumes: everything from Task 10.
- Produces: route `/monitors`; `CheckHistoryBar({ events })` (also used by Task 12); `MonitorForm({ initial, onSubmit, onCancel })`.

**Styling note:** Before writing JSX, open 2–3 existing pages (`CertificatesPage.jsx`, `ServicesPage.jsx`) and reuse their layout primitives, table/card components, button classes, and i18n approach exactly — the code below is structural; adapt class names/components to the app's actual design system rather than inventing new styles.

- [ ] **Step 1: `CheckHistoryBar.jsx`**

A compact bar of recent state segments (newest right), colored by status:

```jsx
import React from 'react';

const COLORS = {
  up: 'var(--color-success, #22c55e)',
  down: 'var(--color-danger, #ef4444)',
  pending: 'var(--color-warning, #eab308)',
  maintenance: 'var(--color-info, #3b82f6)',
  paused: 'var(--color-muted, #9ca3af)',
  resumed: 'var(--color-muted, #9ca3af)',
};

/** events: MonitorEventRead[] newest-first (as the API returns them). */
export default function CheckHistoryBar({ events = [], max = 40 }) {
  const segments = [...events].slice(0, max).reverse();
  if (segments.length === 0) {
    return <span className="text-muted">no history</span>;
  }
  return (
    <div style={{ display: 'flex', gap: 2, alignItems: 'center' }} aria-label="check history">
      {segments.map((ev) => (
        <span
          key={ev.id}
          title={`${ev.status_to} — ${ev.msg || ev.event_type} (${new Date(ev.created_at).toLocaleString()})`}
          style={{
            width: 6, height: 18, borderRadius: 2,
            background: COLORS[ev.status_to] || COLORS.paused,
          }}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 2: `MonitorForm.jsx`**

Check-type selector drives per-type fields (field sets mirror the Task 7 config models):

```jsx
import React, { useState } from 'react';

const CHECK_TYPES = ['http', 'icmp', 'tcp', 'dns'];
const DNS_RECORDS = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SOA', 'PTR', 'SRV', 'CAA'];

const DEFAULTS = {
  name: '', check_type: 'http', host: '', interval_secs: 60,
  max_retries: 0, retry_interval_secs: null, enabled: true,
  target_type: null, target_id: null, config: {},
};

export default function MonitorForm({ initial = null, onSubmit, onCancel }) {
  const [form, setForm] = useState({ ...DEFAULTS, ...(initial || {}) });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const setCfg = (k, v) => setForm((f) => ({ ...f, config: { ...f.config, [k]: v } }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit(form);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to save monitor');
    } finally {
      setSaving(false);
    }
  };

  const cfg = form.config || {};
  return (
    <form onSubmit={handleSubmit}>
      <label>Name
        <input required value={form.name} onChange={(e) => set('name', e.target.value)} />
      </label>
      <label>Check type
        <select
          value={form.check_type}
          disabled={!!initial}
          onChange={(e) => set('check_type', e.target.value) || set('config', {})}
        >
          {CHECK_TYPES.map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}
        </select>
      </label>
      <label>Host
        <input required value={form.host} onChange={(e) => set('host', e.target.value)} />
      </label>

      {form.check_type === 'http' && (
        <>
          <label>URL
            <input placeholder="https://…" value={cfg.url || ''}
              onChange={(e) => setCfg('url', e.target.value)} />
          </label>
          <label>Method
            <select value={cfg.method || 'GET'} onChange={(e) => setCfg('method', e.target.value)}>
              {['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'].map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label>Accepted statuses (comma-separated, e.g. 200-299,301)
            <input
              value={(cfg.accepted_statuses || ['200-299']).join(',')}
              onChange={(e) =>
                setCfg('accepted_statuses', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))}
            />
          </label>
          <label>Keyword (optional)
            <input value={cfg.keyword || ''} onChange={(e) => setCfg('keyword', e.target.value || null)} />
          </label>
          <label>
            <input type="checkbox" checked={!!cfg.keyword_invert}
              onChange={(e) => setCfg('keyword_invert', e.target.checked)} />
            Alert when keyword IS present
          </label>
          <label>JSON path (optional)
            <input placeholder="status.state" value={cfg.json_path || ''}
              onChange={(e) => setCfg('json_path', e.target.value || null)} />
          </label>
          {cfg.json_path && (
            <label>Expected value
              <input value={cfg.expected_value || ''}
                onChange={(e) => setCfg('expected_value', e.target.value || null)} />
            </label>
          )}
          <label>
            <input type="checkbox" checked={cfg.verify_tls !== false}
              onChange={(e) => setCfg('verify_tls', e.target.checked)} />
            Verify TLS certificate
          </label>
        </>
      )}

      {form.check_type === 'tcp' && (
        <label>Port
          <input type="number" min="1" max="65535" value={cfg.port || ''}
            onChange={(e) => setCfg('port', Number(e.target.value) || null)} />
        </label>
      )}

      {form.check_type === 'icmp' && (
        <label>Packet count
          <input type="number" min="1" max="20" value={cfg.packet_count || 5}
            onChange={(e) => setCfg('packet_count', Number(e.target.value) || 5)} />
        </label>
      )}

      {form.check_type === 'dns' && (
        <>
          <label>Record type
            <select value={cfg.record_type || 'A'}
              onChange={(e) => setCfg('record_type', e.target.value)}>
              {DNS_RECORDS.map((r) => <option key={r}>{r}</option>)}
            </select>
          </label>
          <label>Resolver (optional)
            <input placeholder="1.1.1.1" value={cfg.resolver || ''}
              onChange={(e) => setCfg('resolver', e.target.value || null)} />
          </label>
          <label>Expected values (comma-separated, optional)
            <input
              value={(cfg.expected_values || []).join(',')}
              onChange={(e) =>
                setCfg('expected_values', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))}
            />
          </label>
        </>
      )}

      <label>Interval (seconds)
        <input type="number" min="10" value={form.interval_secs}
          onChange={(e) => set('interval_secs', Number(e.target.value))} />
      </label>
      <label>Retries before down
        <input type="number" min="0" max="10" value={form.max_retries}
          onChange={(e) => set('max_retries', Number(e.target.value))} />
      </label>
      {form.max_retries > 0 && (
        <label>Retry interval (seconds)
          <input type="number" min="5" value={form.retry_interval_secs || ''}
            onChange={(e) => set('retry_interval_secs', Number(e.target.value) || null)} />
        </label>
      )}

      {error && <div role="alert">{error}</div>}
      <button type="submit" disabled={saving}>{initial ? 'Save' : 'Create monitor'}</button>
      <button type="button" onClick={onCancel}>Cancel</button>
    </form>
  );
}
```

- [ ] **Step 3: `MonitorsPage.jsx`**

```jsx
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  createMonitor, deleteMonitor, getMonitorEvents, listMonitors,
  pauseMonitor, resumeMonitor, updateMonitor,
} from '../api/monitor';
import { useMonitorStream } from '../hooks/useMonitorStream';
import CheckHistoryBar from '../components/monitors/CheckHistoryBar';
import MonitorForm from '../components/monitors/MonitorForm';

const STATUS_LABEL = { up: 'Up', down: 'Down', pending: 'Pending', maintenance: 'Maintenance' };

export default function MonitorsPage() {
  const [monitors, setMonitors] = useState([]);
  const [eventsById, setEventsById] = useState({});
  const [editing, setEditing] = useState(null); // null | 'new' | monitor object
  const [loading, setLoading] = useState(true);

  const monitorIds = useMemo(() => monitors.map((m) => m.id), [monitors]);
  const { statuses } = useMonitorStream({ monitorIds });

  const refresh = useCallback(async () => {
    const { data } = await listMonitors();
    setMonitors(data);
    const entries = await Promise.all(
      data.map(async (m) => [m.id, (await getMonitorEvents(m.id, 40)).data])
    );
    setEventsById(Object.fromEntries(entries));
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 60000); // REST safety net under the WS push
    return () => clearInterval(t);
  }, [refresh]);

  const liveStatus = (m) => statuses.get(m.id)?.status || m.status;

  const handleSubmit = async (form) => {
    if (editing === 'new') await createMonitor(form);
    else await updateMonitor(editing.id, form);
    setEditing(null);
    await refresh();
  };

  const togglePause = async (m) => {
    await (m.enabled ? pauseMonitor(m.id) : resumeMonitor(m.id));
    await refresh();
  };

  const handleDelete = async (m) => {
    if (!window.confirm(`Delete monitor "${m.name}"?`)) return;
    await deleteMonitor(m.id);
    await refresh();
  };

  if (loading) return <div>Loading monitors…</div>;

  return (
    <div>
      <header>
        <h1>Monitors</h1>
        <button onClick={() => setEditing('new')}>Add monitor</button>
      </header>

      {editing && (
        <MonitorForm
          initial={editing === 'new' ? null : editing}
          onSubmit={handleSubmit}
          onCancel={() => setEditing(null)}
        />
      )}

      <table>
        <thead>
          <tr>
            <th>Status</th><th>Name</th><th>Type</th><th>Target</th>
            <th>History</th><th>Uptime 24h</th><th>Latency</th><th />
          </tr>
        </thead>
        <tbody>
          {monitors.map((m) => (
            <tr key={m.id}>
              <td>
                <span className={`status-pill status-${liveStatus(m)}`}>
                  {m.enabled ? (STATUS_LABEL[liveStatus(m)] || liveStatus(m)) : 'Paused'}
                </span>
              </td>
              <td><Link to={`/monitors/${m.id}`}>{m.name}</Link></td>
              <td>{m.check_type.toUpperCase()}</td>
              <td>{m.config?.url || m.host}</td>
              <td><CheckHistoryBar events={eventsById[m.id] || []} /></td>
              <td>{m.uptime_pct_24h != null ? `${m.uptime_pct_24h}%` : '—'}</td>
              <td>{m.latency_ms != null ? `${Math.round(m.latency_ms)} ms` : '—'}</td>
              <td>
                <button onClick={() => setEditing(m)}>Edit</button>
                <button onClick={() => togglePause(m)}>{m.enabled ? 'Pause' : 'Resume'}</button>
                <button onClick={() => handleDelete(m)}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {monitors.length === 0 && <p>No monitors yet — add one to start watching a service.</p>}
    </div>
  );
}
```

- [ ] **Step 4: Route + navigation**

In `App.jsx`, add with the other lazy pages and routes:

```jsx
const MonitorsPage = React.lazy(() => import('./pages/MonitorsPage'));
// in the authed <Routes> block, near /certificates:
<Route path="/monitors" element={<MonitorsPage />} />
```

In `data/navigation.js`, add a "Monitors" entry adjacent to the Certificates/Notifications entries, copying the exact object shape used there (label, path `/monitors`, icon key from the set the file already uses).

- [ ] **Step 5: Verify build + lint**

Run: `cd apps/frontend && npm run lint && npm run build`
Expected: clean lint, successful build.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/pages/MonitorsPage.jsx apps/frontend/src/components/monitors \
  apps/frontend/src/App.jsx apps/frontend/src/data/navigation.js
git commit -m "feat(frontend): monitors dashboard with live status and check history"
```

---

### Task 12: Monitor detail page

**Files:**
- Create: `apps/frontend/src/pages/MonitorDetailPage.jsx`
- Modify: `apps/frontend/src/App.jsx` (route)

**Interfaces:**
- Consumes: `getMonitor`, `getMonitorEvents`, `getMonitorHistory`, `getMonitorUptime`, `runCheck`, `pauseMonitor`, `resumeMonitor` (Task 10); `CheckHistoryBar` (Task 11); `useMonitorStream`.

**Charting note:** check what the app already uses for charts (`grep -rn "recharts\|chart" apps/frontend/package.json apps/frontend/src/components | head`) and use that library for the latency chart. If none exists, render an inline SVG polyline (no new dependency).

- [ ] **Step 1: Implement `MonitorDetailPage.jsx`**

```jsx
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  getMonitor, getMonitorEvents, getMonitorHistory, getMonitorUptime,
  pauseMonitor, resumeMonitor, runCheck,
} from '../api/monitor';
import { useMonitorStream } from '../hooks/useMonitorStream';
import CheckHistoryBar from '../components/monitors/CheckHistoryBar';

function LatencyChart({ points }) {
  // Replace with the app's charting component if one exists (see task note).
  if (points.length < 2) return <p>Not enough data yet.</p>;
  const w = 600, h = 120;
  const values = points.map((p) => p.value);
  const max = Math.max(...values), min = Math.min(...values);
  const span = max - min || 1;
  const path = points
    .map((p, i) => `${(i / (points.length - 1)) * w},${h - ((p.value - min) / span) * (h - 10) - 5}`)
    .join(' ');
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img" aria-label="latency chart">
      <polyline fill="none" stroke="currentColor" strokeWidth="1.5" points={path} />
      <text x="4" y="12" fontSize="10">{Math.round(max)} ms</text>
      <text x="4" y={h - 4} fontSize="10">{Math.round(min)} ms</text>
    </svg>
  );
}

export default function MonitorDetailPage() {
  const { id } = useParams();
  const monitorId = Number(id);
  const navigate = useNavigate();
  const [monitor, setMonitor] = useState(null);
  const [events, setEvents] = useState([]);
  const [history, setHistory] = useState([]);
  const [uptime, setUptime] = useState(null);
  const { statuses } = useMonitorStream({ monitorIds: [monitorId] });

  const refresh = useCallback(async () => {
    const [m, ev, hist, up] = await Promise.all([
      getMonitor(monitorId), getMonitorEvents(monitorId, 100),
      getMonitorHistory(monitorId, { hours: 24 }), getMonitorUptime(monitorId),
    ]);
    setMonitor(m.data);
    setEvents(ev.data);
    setHistory(hist.data);
    setUptime(up.data.pct_24h);
  }, [monitorId]);

  useEffect(() => {
    refresh().catch(() => navigate('/monitors'));
    const t = setInterval(refresh, 60000);
    return () => clearInterval(t);
  }, [refresh, navigate]);

  if (!monitor) return <div>Loading…</div>;

  const status = statuses.get(monitorId)?.status || monitor.status;
  const tls = monitor.check_type === 'http' && monitor.config?.url?.startsWith('https');

  return (
    <div>
      <header>
        <h1>{monitor.name}</h1>
        <span className={`status-pill status-${status}`}>{status}</span>
        <button onClick={() => runCheck(monitorId).then(refresh)}>Check now</button>
        <button onClick={() =>
          (monitor.enabled ? pauseMonitor(monitorId) : resumeMonitor(monitorId)).then(refresh)}>
          {monitor.enabled ? 'Pause' : 'Resume'}
        </button>
      </header>

      <dl>
        <dt>Type</dt><dd>{monitor.check_type.toUpperCase()}</dd>
        <dt>Target</dt><dd>{monitor.config?.url || monitor.host}</dd>
        <dt>Interval</dt><dd>{monitor.interval_secs}s</dd>
        <dt>Uptime (24h)</dt><dd>{uptime != null ? `${uptime}%` : '—'}</dd>
        <dt>Last check</dt>
        <dd>{monitor.last_polled_at ? new Date(monitor.last_polled_at).toLocaleString() : '—'}</dd>
      </dl>

      <section>
        <h2>Recent checks</h2>
        <CheckHistoryBar events={events} max={80} />
      </section>

      <section>
        <h2>Latency (24h)</h2>
        <LatencyChart points={history} />
      </section>

      {tls && (
        <section>
          <h2>Certificate</h2>
          <p>
            Certificate details are captured on each check; days remaining appears in
            the latency history as <code>cert_days_remaining</code>.
          </p>
        </section>
      )}

      <section>
        <h2>Events</h2>
        <table>
          <thead>
            <tr><th>When</th><th>Event</th><th>Message</th><th>Duration</th></tr>
          </thead>
          <tbody>
            {events.map((ev) => (
              <tr key={ev.id}>
                <td>{new Date(ev.created_at).toLocaleString()}</td>
                <td>{ev.status_from ? `${ev.status_from} → ${ev.status_to}` : ev.status_to}</td>
                <td>{ev.msg}</td>
                <td>{ev.duration_secs != null ? `${Math.round(ev.duration_secs)}s` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Route**

In `App.jsx`:

```jsx
const MonitorDetailPage = React.lazy(() => import('./pages/MonitorDetailPage'));
// below the /monitors route:
<Route path="/monitors/:id" element={<MonitorDetailPage />} />
```

- [ ] **Step 3: Verify build + lint**

Run: `cd apps/frontend && npm run lint && npm run build`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/pages/MonitorDetailPage.jsx apps/frontend/src/App.jsx
git commit -m "feat(frontend): monitor detail page with latency chart and event log"
```

---

### Task 13: End-to-end verification

**Files:** none (verification only; fix fallout where found)

- [ ] **Step 1: Full backend suite**

Run: `cd apps/backend && python -m pytest tests/ -x -q --ignore=tests/stress`
Expected: green except the documented pre-existing host failures (pg_dump, nmap gate, webhooks) and dist-dependent 404→405 flips. Anything else introduced by this slice gets fixed before proceeding.

- [ ] **Step 2: Nomenclature sweep**

Run: `grep -rin "kuma" apps/backend/src/app/services/monitoring apps/backend/src/app/api/monitor.py apps/backend/src/app/api/ws_monitors.py apps/backend/src/app/workers/monitor_poll_worker.py apps/backend/src/app/schemas/monitor.py apps/frontend/src/pages/MonitorsPage.jsx apps/frontend/src/pages/MonitorDetailPage.jsx apps/frontend/src/components/monitors apps/frontend/src/hooks/useMonitorStream.js apps/backend/migrations/versions/0086_native_monitors.py`
Expected: **zero matches**. (The pre-existing integration bridge still matches elsewhere — that's slice 4's removal.)

- [ ] **Step 3: Fresh-volume mono boot**

Per the fresh-install migration convention:

```bash
docker compose down
docker volume rm $(docker volume ls -q | grep circuitbreaker) 2>/dev/null || true
docker compose up -d --build
# wait for health, then:
curl -sf http://localhost/api/v1/health
docker compose exec circuitbreaker alembic current   # expect 0086_native_monitors (head)
```

Expected: container healthy on a fresh volume; migrations applied; no bootstrap/exclusion-list errors in the migration log (`docker compose logs | grep -i alembic`).

- [ ] **Step 4: Live smoke test (in-app only)**

1. Log in to the UI → Monitors → Add monitor (HTTP, `https://example.com`, interval 60, retries 1).
2. Within ~60 s the list shows status Up, latency, and a first `up` event in the bar.
3. Add a monitor for an unreachable host (`http://192.0.2.99/`, retries 1, retry interval 15): watch it go pending → down, and confirm a `down` event and (if a NotificationSink is configured) an alert delivery.
4. Open the detail page: latency chart populates; Check now inserts a fresh sample.
5. Kill the page's network (devtools offline) and restore — WS reconnects (backoff), statuses resume.

- [ ] **Step 5: Commit any fixes and update the plan checkboxes**

```bash
git add -A && git commit -m "test(monitoring): slice 1 verification fixes"
```

---

## Self-Review Notes

- **Spec coverage (slice 1):** schema/state machine (Tasks 1, 5), full HTTP/DNS collectors (Tasks 3–4), moved icmp/tcp (Task 2), events + alert publishing (Tasks 1, 6), REST API (Tasks 7–8), WS bridge (Task 9), dashboard list/detail/forms (Tasks 10–12), `.gitignore` for the reference repo (Task 1), fresh-boot + nomenclature verification (Task 13). Cert-expiry *alerting* is intentionally out of scope (spec: display only — `cert_days_remaining` sample + `details.tls`).
- **Deferred to later slices (per spec):** push monitors, maintenance-window evaluation (status value reserved), infra probes, new notification sinks, bridge removal.
- **Type consistency:** `CheckResult(up, samples, msg, details)` defined in Task 2 and consumed with those exact names in Tasks 3, 4, 6. `apply_result(db, item_id, up, msg, checked_at)` defined in Task 5, called with keywords in Task 6. Service function names in Task 7 match router calls in Task 8 and JS client paths in Task 10.
- **Existing-code reuse:** `_synthesize_monitor` retained verbatim behind `/hardware-summary`; WS endpoint and hook are clones of the telemetry pair with minimal deltas; rollup worker untouched (uptime now computed from `avail` telemetry directly).
