# Monitors Dashboard Facelift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `EntityTable`-based `/monitors` page with a purpose-built card wall — filtering summary tiles, status groups with pulsing pings, and cards that expand in place — fed by a single new overview endpoint.

**Architecture:** One new backend endpoint (`GET /api/v1/monitors/overview`) returns every monitor plus a short latency series and recent check list, both bulk-computed with window functions. The page becomes an orchestrator over eight small presentational components plus a stylesheet; live status keeps arriving through the existing `useMonitorStream` WebSocket hook, and expanding a card lazily fetches its full history and event log.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (window functions via `func.row_number().over(...)`), React 18, react-router `useSearchParams`, recharts (already a dependency), vitest + React Testing Library, pytest.

**Spec:** `specs/2026-07-26-monitors-dashboard-facelift-design.md`

## Global Constraints

- Circuit Breaker nomenclature only — no "kuma"/"uptime-kuma"/"beat"/"heartbeat" in identifiers, comments, API fields, UI strings or tests. Use *check*, *sample*, *event*.
- Backend: `ruff check` and `ruff format` clean (line length 100). Run via `/home/shawnji/workspace/CircuitBreaker/.venv/bin/ruff`.
- Frontend: `npx eslint` must report 0 errors; `npx prettier --write` on every touched file.
- New routes in `api/monitor.py` must be declared **before** `@router.get("/{monitor_id}")` or the literal path segment is parsed as a monitor id.
- Colours come from CSS custom properties only — no hardcoded hex in components.
- Every animation must be disabled under `prefers-reduced-motion: reduce`.
- Tests: backend `cd apps/backend && /home/shawnji/workspace/CircuitBreaker/.venv/bin/python -m pytest <path> -q --no-cov -o addopts=""`; frontend `cd apps/frontend && npx vitest run <path>`.
- Commit after each task. No `Co-Authored-By: Claude` trailers.

---

### Task 1: Theme tokens and status colour cleanup

`StatusPill` and `CheckHistoryBar` reference `--color-warning`, `--color-info` and `--color-muted`, none of which exist, so pending/maintenance/paused render off-palette hex fallbacks. Add the tokens and drop the fallbacks. `CheckHistoryBar` also gains the `size` prop the card face and expanded body need.

**Files:**
- Modify: `apps/frontend/src/styles/main.css:11-31` (the `:root` block)
- Modify: `apps/frontend/src/components/monitors/StatusPill.jsx`
- Modify: `apps/frontend/src/components/monitors/CheckHistoryBar.jsx`
- Test: `apps/frontend/src/__tests__/monitor-status-colors.test.jsx` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: CSS vars `--color-warning`, `--color-info`, `--color-muted`; `CheckHistoryBar({ events, max, size })` where `size` is `'sm' | 'md'` (default `'sm'`), `'sm'` = 4×15px segments, `'md'` = 6×18px.

- [ ] **Step 1: Write the failing test**

```jsx
// apps/frontend/src/__tests__/monitor-status-colors.test.jsx
import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import StatusPill from '../components/monitors/StatusPill.jsx';
import CheckHistoryBar from '../components/monitors/CheckHistoryBar.jsx';

describe('monitor status colours', () => {
  it('pulls every status colour from a theme token', () => {
    for (const status of ['up', 'down', 'pending', 'maintenance']) {
      const { unmount } = render(<StatusPill status={status} />);
      const pill = screen.getByText(new RegExp(status, 'i'));
      expect(pill.style.background).toContain('var(--color-');
      expect(pill.style.background).not.toMatch(/#[0-9a-f]{6}/i);
      unmount();
    }
  });

  it('renders a paused pill from the muted token', () => {
    render(<StatusPill status="up" enabled={false} />);
    const pill = screen.getByText('Paused');
    expect(pill.style.background).toBe('var(--color-muted)');
  });

  it('sizes check-history segments by the size prop', () => {
    const events = [{ id: 1, status_to: 'up', msg: 'ok', created_at: '2026-07-26T00:00:00Z' }];
    const { container, unmount } = render(<CheckHistoryBar events={events} />);
    expect(container.querySelector('span > span').style.width).toBe('4px');
    unmount();

    const { container: md } = render(<CheckHistoryBar events={events} size="md" />);
    expect(md.querySelector('span > span').style.width).toBe('6px');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-status-colors.test.jsx`
Expected: FAIL — pill backgrounds still contain `#22c55e`-style fallbacks and `size` is ignored (both widths report `4px`… actually `6px`, the current hardcoded value).

- [ ] **Step 3: Add the tokens**

In `apps/frontend/src/styles/main.css`, inside `:root`, after `--color-success`:

```css
  --color-warning: #d79921;
  --color-info: #83a598;
  --color-muted: var(--color-text-muted);
```

- [ ] **Step 4: Drop the hex fallbacks in `StatusPill.jsx`**

```jsx
export const STATUS_COLORS = {
  up: 'var(--color-success)',
  down: 'var(--color-danger)',
  pending: 'var(--color-warning)',
  maintenance: 'var(--color-info)',
  paused: 'var(--color-muted)',
};
```

- [ ] **Step 5: Add the `size` prop to `CheckHistoryBar.jsx`**

Replace the component body so colours use tokens and segments are sized:

```jsx
const COLORS = {
  up: 'var(--color-success)',
  down: 'var(--color-danger)',
  pending: 'var(--color-warning)',
  maintenance: 'var(--color-info)',
  paused: 'var(--color-muted)',
  resumed: 'var(--color-muted)',
};

const SIZES = { sm: { width: 4, height: 15, gap: 1.5 }, md: { width: 6, height: 18, gap: 2 } };

/** events: MonitorEventRead[] newest-first (as the API returns them). */
export default function CheckHistoryBar({ events = [], max = 40, size = 'sm' }) {
  const segments = [...events].slice(0, max).reverse();
  const dim = SIZES[size] || SIZES.sm;
  if (segments.length === 0) {
    return <span className="text-muted">no history</span>;
  }
  return (
    <div style={{ display: 'flex', gap: dim.gap, alignItems: 'center' }} aria-label="check history">
      {segments.map((ev) => (
        <span
          key={ev.id}
          title={`${ev.status_to} — ${ev.msg || ev.event_type} (${new Date(ev.created_at).toLocaleString()})`}
          style={{
            width: dim.width,
            height: dim.height,
            borderRadius: 2,
            background: COLORS[ev.status_to] || COLORS.paused,
          }}
        />
      ))}
    </div>
  );
}
```

Keep the existing `/* eslint-disable security/detect-object-injection */` header comment if present.

- [ ] **Step 6: Run tests and lint**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-status-colors.test.jsx src/__tests__/monitor-cell.test.jsx`
Expected: PASS
Run: `npx eslint src/components/monitors/ src/__tests__/monitor-status-colors.test.jsx && npx prettier --write src/styles/main.css src/components/monitors/StatusPill.jsx src/components/monitors/CheckHistoryBar.jsx src/__tests__/monitor-status-colors.test.jsx`

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/styles/main.css apps/frontend/src/components/monitors/StatusPill.jsx apps/frontend/src/components/monitors/CheckHistoryBar.jsx apps/frontend/src/__tests__/monitor-status-colors.test.jsx
git commit -m "fix(monitors): status colours come from theme tokens"
```

---

### Task 2: `GET /monitors/overview`

One request returning every monitor plus `latency_series` (last 12 samples, oldest→newest) and `recent_checks` (last 20 events, newest-first), each from one bulk window-function query.

**Files:**
- Modify: `apps/backend/src/app/services/monitor_service.py`
- Modify: `apps/backend/src/app/schemas/monitor.py`
- Modify: `apps/backend/src/app/api/monitor.py`
- Modify: `apps/frontend/src/api/monitor.js`
- Test: `apps/backend/tests/api/test_monitor_api.py`

**Interfaces:**
- Consumes: `monitor_service._to_dict`, `_uptime_pct_map`, `_latest_metric_map` (existing).
- Produces:
  - `monitor_service.list_overview(db, *, latency_points=12, check_points=20) -> list[dict]`
  - `schemas.monitor.MonitorCheckPoint` = `{id: int, status_to: str, msg: str, created_at: datetime}`
  - `schemas.monitor.MonitorOverview(MonitorRead)` adding `latency_series: list[float]`, `recent_checks: list[MonitorCheckPoint]`
  - `GET /api/v1/monitors/overview` → `list[MonitorOverview]`
  - JS `getMonitorsOverview()` → axios promise of `MonitorOverview[]`

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/api/test_monitor_api.py`:

```python
# ── Overview (the dashboard's single fetch) ──────────────────────────────────


@pytest.mark.asyncio
async def test_overview_includes_series_and_checks(client, auth_headers, db_session):
    from app.db.models import MonitorEvent, TelemetryTimeseries

    mid = (await _create(client, auth_headers, name="overview-target")).json()["id"]
    base = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    for i, value in enumerate([10.0, 20.0, 30.0]):
        db_session.add(
            TelemetryTimeseries(
                entity_type="monitor",
                entity_id=0,
                item_id=mid,
                metric="latency_ms",
                value=value,
                source="monitor",
                ts=base + timedelta(minutes=i),
            )
        )
    for i, status in enumerate(["up", "down", "up"]):
        db_session.add(
            MonitorEvent(
                item_id=mid,
                event_type=status,
                status_to=status,
                msg=f"event {i}",
                created_at=base + timedelta(minutes=i),
            )
        )
    db_session.commit()

    resp = await client.get("/api/v1/monitors/overview", headers=auth_headers)
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == mid)

    # every MonitorRead field the page renders is still present
    assert row["name"] == "overview-target"
    assert row["check_type"] == "http"
    assert row["status"] == "pending"

    # latency series is oldest → newest, for the sparkline
    assert row["latency_series"] == [10.0, 20.0, 30.0]

    # checks are newest first, matching GET /events and CheckHistoryBar
    assert [c["msg"] for c in row["recent_checks"]] == ["event 2", "event 1", "event 0"]
    assert row["recent_checks"][0]["status_to"] == "up"
    assert set(row["recent_checks"][0]) == {"id", "status_to", "msg", "created_at"}


@pytest.mark.asyncio
async def test_overview_caps_series_lengths(client, auth_headers, db_session):
    from app.db.models import MonitorEvent, TelemetryTimeseries

    mid = (await _create(client, auth_headers, name="chatty")).json()["id"]
    base = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    for i in range(30):
        db_session.add(
            TelemetryTimeseries(
                entity_type="monitor",
                entity_id=0,
                item_id=mid,
                metric="latency_ms",
                value=float(i),
                source="monitor",
                ts=base + timedelta(seconds=i),
            )
        )
        db_session.add(
            MonitorEvent(
                item_id=mid,
                event_type="up",
                status_to="up",
                msg=f"e{i}",
                created_at=base + timedelta(seconds=i),
            )
        )
    db_session.commit()

    row = next(
        r
        for r in (await client.get("/api/v1/monitors/overview", headers=auth_headers)).json()
        if r["id"] == mid
    )
    assert len(row["latency_series"]) == 12
    assert row["latency_series"] == [float(i) for i in range(18, 30)]  # newest 12, oldest first
    assert len(row["recent_checks"]) == 20
    assert row["recent_checks"][0]["msg"] == "e29"  # newest first


@pytest.mark.asyncio
async def test_overview_empty_series_for_fresh_monitor(client, auth_headers):
    mid = (await _create(client, auth_headers, name="fresh")).json()["id"]
    row = next(
        r
        for r in (await client.get("/api/v1/monitors/overview", headers=auth_headers)).json()
        if r["id"] == mid
    )
    assert row["latency_series"] == []
    assert row["recent_checks"] == []


@pytest.mark.asyncio
async def test_overview_route_wins_over_monitor_id(client, auth_headers):
    """"/overview" must not be parsed as a monitor id."""
    resp = await client.get("/api/v1/monitors/overview", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
```

Add the imports the tests need at the top of the file:

```python
from datetime import UTC, datetime, timedelta

import pytest
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && /home/shawnji/workspace/CircuitBreaker/.venv/bin/python -m pytest tests/api/test_monitor_api.py -q --no-cov -o addopts="" -k overview`
Expected: FAIL — 422 or 404, because `/overview` currently falls through to `GET /{monitor_id}`.

- [ ] **Step 3: Add the bulk query helpers to `monitor_service.py`**

Place immediately after `_uptime_pct_map`:

```python
def _latency_series_map(
    db: Session, item_ids: list[int], limit: int
) -> dict[int, list[float]]:
    """Last `limit` latency samples per monitor, oldest → newest (sparkline order)."""
    if not item_ids:
        return {}
    ranked = (
        select(
            TelemetryTimeseries.item_id,
            TelemetryTimeseries.value,
            TelemetryTimeseries.ts,
            func.row_number()
            .over(
                partition_by=TelemetryTimeseries.item_id,
                order_by=TelemetryTimeseries.ts.desc(),
            )
            .label("rn"),
        )
        .where(
            TelemetryTimeseries.item_id.in_(item_ids),
            TelemetryTimeseries.metric == "latency_ms",
        )
        .subquery()
    )
    rows = db.execute(
        select(ranked.c.item_id, ranked.c.value)
        .where(ranked.c.rn <= limit)
        .order_by(ranked.c.item_id, ranked.c.ts.asc())
    ).all()
    series: dict[int, list[float]] = {}
    for item_id, value in rows:
        series.setdefault(item_id, []).append(value)
    return series


def _recent_checks_map(db: Session, item_ids: list[int], limit: int) -> dict[int, list[dict]]:
    """Last `limit` events per monitor, newest first — the shape CheckHistoryBar takes."""
    if not item_ids:
        return {}
    ranked = (
        select(
            MonitorEvent.id,
            MonitorEvent.item_id,
            MonitorEvent.status_to,
            MonitorEvent.msg,
            MonitorEvent.created_at,
            func.row_number()
            .over(partition_by=MonitorEvent.item_id, order_by=MonitorEvent.created_at.desc())
            .label("rn"),
        )
        .where(MonitorEvent.item_id.in_(item_ids))
        .subquery()
    )
    rows = db.execute(
        select(
            ranked.c.id,
            ranked.c.item_id,
            ranked.c.status_to,
            ranked.c.msg,
            ranked.c.created_at,
        )
        .where(ranked.c.rn <= limit)
        .order_by(ranked.c.item_id, ranked.c.created_at.desc())
    ).all()
    checks: dict[int, list[dict]] = {}
    for ev_id, item_id, status_to, msg, created_at in rows:
        checks.setdefault(item_id, []).append(
            {"id": ev_id, "status_to": status_to, "msg": msg, "created_at": created_at}
        )
    return checks
```

- [ ] **Step 4: Add `list_overview` after `list_monitors`**

```python
def list_overview(
    db: Session, *, latency_points: int = 12, check_points: int = 20
) -> list[dict]:
    """Everything the monitors dashboard renders, in one round trip.

    Four bulk queries total regardless of monitor count — the page used to fetch
    events per monitor.
    """
    items = list(db.scalars(select(MonitorItem).order_by(MonitorItem.name, MonitorItem.id)).all())
    if not items:
        return []
    ids = [i.id for i in items]
    uptimes = _uptime_pct_map(db, ids)
    latencies = _latest_metric_map(db, ids, "latency_ms")
    series = _latency_series_map(db, ids, latency_points)
    checks = _recent_checks_map(db, ids, check_points)
    return [
        {
            **_to_dict(item, uptimes.get(item.id), latencies.get(item.id)),
            "latency_series": series.get(item.id, []),
            "recent_checks": checks.get(item.id, []),
        }
        for item in items
    ]
```

- [ ] **Step 5: Add the schemas to `schemas/monitor.py`**

After `MonitorHistoryPoint`:

```python
class MonitorCheckPoint(BaseModel):
    """One past check, trimmed to what the dashboard's history bar draws."""

    id: int
    status_to: str
    msg: str
    created_at: datetime


class MonitorOverview(MonitorRead):
    """A monitor plus the compact series the dashboard cards render."""

    latency_series: list[float] = Field(default_factory=list)
    recent_checks: list[MonitorCheckPoint] = Field(default_factory=list)
```

- [ ] **Step 6: Add the route to `api/monitor.py`**

Import `MonitorOverview` in the existing `from app.schemas.monitor import (...)` block, then add this **above** the `# ── Target-scoped actions` comment block (both are already above `/{monitor_id}`):

```python
@router.get("/overview", response_model=list[MonitorOverview])
def monitors_overview(db: Session = Depends(get_db)) -> Any:
    """Every monitor plus its compact latency series and recent checks — one request."""
    return monitor_service.list_overview(db)
```

- [ ] **Step 7: Add the frontend client function**

In `apps/frontend/src/api/monitor.js`, after `listMonitors`:

```js
export const getMonitorsOverview = () => client.get('/monitors/overview');
```

- [ ] **Step 8: Run tests and lint**

Run: `cd apps/backend && /home/shawnji/workspace/CircuitBreaker/.venv/bin/python -m pytest tests/api/test_monitor_api.py -q --no-cov -o addopts=""`
Expected: PASS (all, including the pre-existing target tests)
Run: `/home/shawnji/workspace/CircuitBreaker/.venv/bin/ruff format src/app tests && /home/shawnji/workspace/CircuitBreaker/.venv/bin/ruff check src/app tests`

- [ ] **Step 9: Commit**

```bash
git add apps/backend/src/app/services/monitor_service.py apps/backend/src/app/schemas/monitor.py apps/backend/src/app/api/monitor.py apps/backend/tests/api/test_monitor_api.py apps/frontend/src/api/monitor.js
git commit -m "feat(monitors): overview endpoint with compact latency and check series"
```

---

### Task 3: Extract the shared latency chart

`MonitorDetailPage` defines `LatencyChart` inline; the expanded card needs the same chart. Extract it unchanged.

**Files:**
- Create: `apps/frontend/src/components/monitors/LatencyChart.jsx`
- Modify: `apps/frontend/src/pages/MonitorDetailPage.jsx` (delete the inline component and the recharts imports, import the new one)
- Test: `apps/frontend/src/__tests__/latency-chart.test.jsx` (create)

**Interfaces:**
- Produces: `LatencyChart({ points, height })` where `points` is `[{ts, value}]` and `height` defaults to `160`. Renders "Not enough data yet." when fewer than 2 points.

- [ ] **Step 1: Write the failing test**

```jsx
// apps/frontend/src/__tests__/latency-chart.test.jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }) => <div data-testid="chart">{children}</div>,
  LineChart: ({ children }) => <div>{children}</div>,
  Line: () => null,
  CartesianGrid: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
}));

import LatencyChart from '../components/monitors/LatencyChart.jsx';

describe('LatencyChart', () => {
  it('explains itself when there is not enough data', () => {
    render(<LatencyChart points={[{ ts: '2026-07-26T00:00:00Z', value: 5 }]} />);
    expect(screen.getByText('Not enough data yet.')).toBeTruthy();
  });

  it('renders a chart once there are two points', () => {
    render(
      <LatencyChart
        points={[
          { ts: '2026-07-26T00:00:00Z', value: 5 },
          { ts: '2026-07-26T00:01:00Z', value: 7 },
        ]}
      />
    );
    expect(screen.getByTestId('chart')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/latency-chart.test.jsx`
Expected: FAIL — cannot resolve `../components/monitors/LatencyChart.jsx`.

- [ ] **Step 3: Create the component**

Move the body verbatim from `MonitorDetailPage.jsx`, adding a `height` prop and propTypes:

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

/**
 * LatencyChart — 24h latency series for one monitor. Shared by the monitors
 * dashboard's expanded cards and the monitor detail page.
 */
export default function LatencyChart({ points = [], height = 160 }) {
  if (points.length < 2) return <p className="text-muted">Not enough data yet.</p>;
  const data = points.map((p) => ({ ts: new Date(p.ts).getTime(), value: p.value }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
        <XAxis
          dataKey="ts"
          type="number"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(t) => new Date(t).toLocaleTimeString()}
          stroke="var(--color-text-muted)"
          fontSize={11}
        />
        <YAxis
          stroke="var(--color-text-muted)"
          fontSize={11}
          tickFormatter={(v) => `${Math.round(v)}`}
          width={40}
        />
        <Tooltip
          labelFormatter={(t) => new Date(t).toLocaleString()}
          formatter={(v) => [`${Math.round(v)} ms`, 'Latency']}
        />
        <Line
          type="monotone"
          dataKey="value"
          stroke="var(--color-primary)"
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

LatencyChart.propTypes = {
  points: PropTypes.arrayOf(PropTypes.object),
  height: PropTypes.number,
};
```

- [ ] **Step 4: Update `MonitorDetailPage.jsx`**

Delete the recharts import block and the local `function LatencyChart(...)`, then add:

```jsx
import LatencyChart from '../components/monitors/LatencyChart';
```

Its two usages (`<LatencyChart points={history} />`) stay as they are.

- [ ] **Step 5: Run tests and lint**

Run: `cd apps/frontend && npx vitest run src/__tests__/latency-chart.test.jsx`
Expected: PASS
Run: `npx eslint src/components/monitors/LatencyChart.jsx src/pages/MonitorDetailPage.jsx && npx prettier --write src/components/monitors/LatencyChart.jsx src/pages/MonitorDetailPage.jsx src/__tests__/latency-chart.test.jsx`

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/monitors/LatencyChart.jsx apps/frontend/src/pages/MonitorDetailPage.jsx apps/frontend/src/__tests__/latency-chart.test.jsx
git commit -m "refactor(monitors): extract the shared latency chart"
```

---

### Task 4: `StatusPing` and the dashboard stylesheet

**Files:**
- Create: `apps/frontend/src/components/monitors/StatusPing.jsx`
- Create: `apps/frontend/src/styles/monitors.css`
- Test: `apps/frontend/src/__tests__/status-ping.test.jsx` (create)

**Interfaces:**
- Produces: `StatusPing({ status, size })` — `status` is `up | down | pending | maintenance | paused`, `size` defaults to `8` (px). Renders `<span class="mon-ping" data-status=… aria-hidden="true">` containing a `.mon-ping-core` always and a `.mon-ping-ring` for every status except `paused`.
- Produces: `styles/monitors.css` with the class names Tasks 5–11 use: `.mon-ping`, `.mon-ping-core`, `.mon-ping-ring`, `.mon-spark`, `.mon-tiles`, `.mon-tile`, `.mon-toolbar`, `.mon-chip`, `.mon-search`, `.mon-group`, `.mon-group-title`, `.mon-wall`, `.mon-card`, `.mon-card-face`, `.mon-card-detail`, `.mon-badge`, `.mon-target`, `.mon-headline`, `.mon-stats`, `.mon-events`, `.mon-actions`, `.mon-empty`, `.mon-skeleton`.

- [ ] **Step 1: Write the failing test**

```jsx
// apps/frontend/src/__tests__/status-ping.test.jsx
import React from 'react';
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import StatusPing from '../components/monitors/StatusPing.jsx';

describe('StatusPing', () => {
  it('pulses for every live status, with a faster ring while down', () => {
    const { container: down } = render(<StatusPing status="down" />);
    const downRing = down.querySelector('.mon-ping-ring');
    expect(downRing).toBeTruthy();
    expect(downRing.style.animationDuration).toBe('1.1s');

    const { container: up } = render(<StatusPing status="up" />);
    expect(up.querySelector('.mon-ping-ring').style.animationDuration).toBe('1.9s');

    const { container: pending } = render(<StatusPing status="pending" />);
    expect(pending.querySelector('.mon-ping-ring').style.animationDuration).toBe('1.5s');
  });

  it('is a static dot when paused — nothing is being checked', () => {
    const { container } = render(<StatusPing status="paused" />);
    expect(container.querySelector('.mon-ping-ring')).toBeNull();
    expect(container.querySelector('.mon-ping-core')).toBeTruthy();
  });

  it('carries the status for CSS and hides itself from screen readers', () => {
    const { container } = render(<StatusPing status="up" size={10} />);
    const ping = container.querySelector('.mon-ping');
    expect(ping.dataset.status).toBe('up');
    expect(ping.getAttribute('aria-hidden')).toBe('true');
    expect(ping.style.width).toBe('10px');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/status-ping.test.jsx`
Expected: FAIL — cannot resolve `StatusPing.jsx`.

- [ ] **Step 3: Create `StatusPing.jsx`**

```jsx
import React from 'react';
import PropTypes from 'prop-types';

// Ring period per status — trouble pulses faster so it reads as more urgent.
// Paused is absent on purpose: a paused monitor is not being checked, so its
// ping is a static dot.
const PERIODS = {
  down: '1.1s',
  pending: '1.5s',
  maintenance: '1.9s',
  up: '1.9s',
};

/**
 * StatusPing — the pulsing status dot beside a monitor group heading. Purely
 * decorative: the group heading always carries the status word and count as
 * text, so this is aria-hidden.
 */
export default function StatusPing({ status, size = 8 }) {
  const period = Object.hasOwn(PERIODS, status) ? PERIODS[status] : undefined;
  return (
    <span
      className="mon-ping"
      data-status={status}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {period && <span className="mon-ping-ring" style={{ animationDuration: period }} />}
      <span className="mon-ping-core" />
    </span>
  );
}

StatusPing.propTypes = {
  status: PropTypes.oneOf(['up', 'down', 'pending', 'maintenance', 'paused']).isRequired,
  size: PropTypes.number,
};
```

- [ ] **Step 4: Create `styles/monitors.css`**

```css
/* ── Monitors dashboard ─────────────────────────────────────────────────────
   The card wall on /monitors. Keyframes, :hover and prefers-reduced-motion
   can't live in inline styles, which is why this page has a stylesheet while
   the smaller monitor components use inline styles. */

/* Status ping — solid core plus an expanding ring, per group heading. */
.mon-ping {
  position: relative;
  flex: none;
  display: inline-block;
}
.mon-ping[data-status='up'] {
  --mon-ping-color: var(--color-success);
}
.mon-ping[data-status='down'] {
  --mon-ping-color: var(--color-danger);
}
.mon-ping[data-status='pending'] {
  --mon-ping-color: var(--color-warning);
}
.mon-ping[data-status='maintenance'] {
  --mon-ping-color: var(--color-info);
}
.mon-ping[data-status='paused'] {
  --mon-ping-color: var(--color-muted);
}
.mon-ping-core,
.mon-ping-ring {
  position: absolute;
  inset: 0;
  border-radius: 999px;
  background: var(--mon-ping-color);
}
.mon-ping-ring {
  opacity: 0.7;
  animation-name: mon-ripple;
  animation-timing-function: cubic-bezier(0, 0, 0.2, 1);
  animation-iteration-count: infinite;
}
@keyframes mon-ripple {
  0% {
    transform: scale(1);
    opacity: 0.7;
  }
  70%,
  100% {
    transform: scale(3.4);
    opacity: 0;
  }
}

/* Summary tiles — counts that double as status filters. */
.mon-tiles {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}
.mon-tile {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 8px 12px;
  text-align: left;
  cursor: pointer;
  color: var(--color-text);
  font: inherit;
}
.mon-tile:hover {
  border-color: var(--color-primary);
}
.mon-tile[aria-pressed='true'] {
  border-color: var(--color-primary);
  box-shadow: inset 0 0 0 1px var(--color-primary);
}
.mon-tile b {
  display: block;
  font-size: 1.35rem;
  line-height: 1.15;
}
.mon-tile span {
  color: var(--color-text-muted);
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
}

/* Toolbar — search, type chips, sort. */
.mon-toolbar {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 4px;
}
.mon-search {
  flex: 1 1 180px;
  min-width: 140px;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  padding: 5px 9px;
  color: var(--color-text);
  font-size: 0.8rem;
}
.mon-chip {
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 0.68rem;
  color: var(--color-text-muted);
  background: transparent;
  cursor: pointer;
}
.mon-chip:hover {
  border-color: var(--color-primary);
}
.mon-chip[aria-pressed='true'] {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: rgba(var(--color-primary-rgb), 0.08);
}

/* Groups and the wall. */
.mon-group {
  margin-top: 14px;
}
.mon-group-title {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--color-text-muted);
  font-size: 0.66rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  margin: 0 0 7px;
}
.mon-group-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--color-border);
}
.mon-wall {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
@media (max-width: 1280px) {
  .mon-wall {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 900px) {
  .mon-wall {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .mon-tiles {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 640px) {
  .mon-wall {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* Cards. */
.mon-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-top: 2px solid var(--mon-status-color, var(--color-border));
  border-radius: var(--radius);
  overflow: hidden;
  transition: border-color 120ms ease;
}
.mon-card[data-status='up'] {
  --mon-status-color: var(--color-success);
}
.mon-card[data-status='down'] {
  --mon-status-color: var(--color-danger);
}
.mon-card[data-status='pending'] {
  --mon-status-color: var(--color-warning);
}
.mon-card[data-status='maintenance'] {
  --mon-status-color: var(--color-info);
}
.mon-card[data-status='paused'] {
  --mon-status-color: var(--color-muted);
  opacity: 0.62;
}
.mon-card:hover {
  border-color: var(--color-primary);
}
.mon-card[data-expanded='true'] {
  grid-column: 1 / -1;
  border-color: var(--color-primary);
}
.mon-card-face {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: 0;
  padding: 9px 10px;
  color: var(--color-text);
  font: inherit;
  cursor: pointer;
}
.mon-card-face:focus-visible,
.mon-tile:focus-visible,
.mon-chip:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.mon-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.mon-card-name {
  font-weight: 700;
  font-size: 0.82rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mon-badge {
  border: 1px solid var(--color-border);
  border-radius: 3px;
  padding: 0 4px;
  font-size: 0.58rem;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  flex: none;
}
.mon-target {
  color: var(--color-text-muted);
  font-size: 0.64rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mon-card-mid {
  min-height: 20px;
  margin: 7px 0;
}
.mon-card-foot {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
}
.mon-headline {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--mon-status-color);
}
.mon-uptime {
  color: var(--color-text-muted);
  font-size: 0.64rem;
}

/* Sparkline. */
.mon-spark {
  display: flex;
  align-items: flex-end;
  gap: 1px;
}
.mon-spark span {
  width: 3px;
  border-radius: 1px;
  background: var(--color-primary);
  opacity: 0.7;
}

/* Expanded body. */
.mon-card-detail {
  border-top: 1px solid var(--color-border);
  padding: 10px;
  animation: mon-expand 140ms ease-out;
}
@keyframes mon-expand {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
.mon-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 8px 0;
}
.mon-stats b {
  display: block;
  font-size: 0.95rem;
}
.mon-stats span {
  color: var(--color-text-muted);
  font-size: 0.6rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.mon-events {
  border-top: 1px solid var(--color-border);
  margin-top: 8px;
  padding-top: 6px;
  color: var(--color-text-muted);
  font-size: 0.68rem;
  list-style: none;
}
.mon-events li {
  display: flex;
  gap: 8px;
}
.mon-events time {
  flex: none;
  font-variant-numeric: tabular-nums;
}
.mon-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 10px;
}

/* Empty and loading states. */
.mon-empty {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 28px;
  text-align: center;
  margin-top: 16px;
}
.mon-skeleton {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  height: 96px;
}

@media (prefers-reduced-motion: reduce) {
  .mon-ping-ring {
    animation: none;
    opacity: 0;
  }
  .mon-card-detail {
    animation: none;
  }
  .mon-card {
    transition: none;
  }
}
```

- [ ] **Step 5: Run tests and lint**

Run: `cd apps/frontend && npx vitest run src/__tests__/status-ping.test.jsx`
Expected: PASS
Run: `npx eslint src/components/monitors/StatusPing.jsx && npx prettier --write src/components/monitors/StatusPing.jsx src/styles/monitors.css src/__tests__/status-ping.test.jsx`

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/monitors/StatusPing.jsx apps/frontend/src/styles/monitors.css apps/frontend/src/__tests__/status-ping.test.jsx
git commit -m "feat(monitors): status ping and dashboard stylesheet"
```

---

### Task 5: `LatencySparkline` and the format helpers

**Files:**
- Create: `apps/frontend/src/components/monitors/LatencySparkline.jsx`
- Create: `apps/frontend/src/components/monitors/monitorFormat.js`
- Test: `apps/frontend/src/__tests__/monitor-sparkline.test.jsx` (create)

**Interfaces:**
- Produces: `LatencySparkline({ series, height })` — returns `null` for an empty series; otherwise one `<span>` per point, tallest bar equal to `height`.
- Produces: `formatAgo(iso, now = Date.now())` → `'—' | '4s ago' | '3m ago' | '2h ago' | '5d ago'`.
- Produces: `formatSince(iso, now = Date.now())` → `'—' | '42s' | '6m 12s' | '3h 04m' | '2d 5h'`.

- [ ] **Step 1: Write the failing test**

```jsx
// apps/frontend/src/__tests__/monitor-sparkline.test.jsx
import React from 'react';
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import LatencySparkline from '../components/monitors/LatencySparkline.jsx';
import { formatAgo, formatSince } from '../components/monitors/monitorFormat.js';

describe('LatencySparkline', () => {
  it('draws one bar per sample, scaled to the tallest', () => {
    const { container } = render(<LatencySparkline series={[5, 10, 20]} height={20} />);
    const bars = container.querySelectorAll('.mon-spark span');
    expect(bars).toHaveLength(3);
    expect(bars[2].style.height).toBe('20px');
    expect(bars[0].style.height).toBe('5px');
  });

  it('renders nothing without samples', () => {
    const { container } = render(<LatencySparkline series={[]} />);
    expect(container.querySelector('.mon-spark')).toBeNull();
  });

  it('keeps a flat series visible', () => {
    const { container } = render(<LatencySparkline series={[0, 0]} height={20} />);
    const bars = container.querySelectorAll('.mon-spark span');
    expect(bars[0].style.height).toBe('2px');
  });
});

describe('monitor time formats', () => {
  const now = Date.parse('2026-07-26T12:00:00Z');

  it('formats how long ago a check landed', () => {
    expect(formatAgo(null, now)).toBe('—');
    expect(formatAgo('2026-07-26T11:59:56Z', now)).toBe('4s ago');
    expect(formatAgo('2026-07-26T11:57:00Z', now)).toBe('3m ago');
    expect(formatAgo('2026-07-26T10:00:00Z', now)).toBe('2h ago');
    expect(formatAgo('2026-07-21T12:00:00Z', now)).toBe('5d ago');
  });

  it('formats time spent in the current state', () => {
    expect(formatSince(null, now)).toBe('—');
    expect(formatSince('2026-07-26T11:59:18Z', now)).toBe('42s');
    expect(formatSince('2026-07-26T11:53:48Z', now)).toBe('6m 12s');
    expect(formatSince('2026-07-26T08:56:00Z', now)).toBe('3h 04m');
    expect(formatSince('2026-07-24T07:00:00Z', now)).toBe('2d 5h');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-sparkline.test.jsx`
Expected: FAIL — neither module resolves.

- [ ] **Step 3: Create `monitorFormat.js`**

```js
/** Time formatting for the monitors dashboard. Pure functions — `now` is injectable for tests. */

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "4s ago" / "3m ago" / "2h ago" / "5d ago" — for the header's last-check ticker. */
export function formatAgo(iso, now = Date.now()) {
  if (!iso) return '—';
  const delta = Math.max(0, now - Date.parse(iso));
  if (delta < MINUTE) return `${Math.floor(delta / SECOND)}s ago`;
  if (delta < HOUR) return `${Math.floor(delta / MINUTE)}m ago`;
  if (delta < DAY) return `${Math.floor(delta / HOUR)}h ago`;
  return `${Math.floor(delta / DAY)}d ago`;
}

/** "42s" / "6m 12s" / "3h 04m" / "2d 5h" — for time spent in the current state. */
export function formatSince(iso, now = Date.now()) {
  if (!iso) return '—';
  const delta = Math.max(0, now - Date.parse(iso));
  if (delta < MINUTE) return `${Math.floor(delta / SECOND)}s`;
  if (delta < HOUR) {
    const m = Math.floor(delta / MINUTE);
    return `${m}m ${Math.floor((delta - m * MINUTE) / SECOND)}s`;
  }
  if (delta < DAY) {
    const h = Math.floor(delta / HOUR);
    return `${h}h ${String(Math.floor((delta - h * HOUR) / MINUTE)).padStart(2, '0')}m`;
  }
  const d = Math.floor(delta / DAY);
  return `${d}d ${Math.floor((delta - d * DAY) / HOUR)}h`;
}
```

- [ ] **Step 4: Create `LatencySparkline.jsx`**

```jsx
import React from 'react';
import PropTypes from 'prop-types';

const MIN_BAR = 2;

/**
 * LatencySparkline — the card face's latency trend, drawn from the compact
 * `latency_series` the overview endpoint returns (oldest → newest). Decorative:
 * the current figure is in the card footer, so this is aria-hidden.
 */
export default function LatencySparkline({ series = [], height = 18 }) {
  if (series.length === 0) return null;
  const peak = Math.max(...series);
  return (
    <div className="mon-spark" style={{ height }} aria-hidden="true">
      {series.map((value, i) => (
        <span
          key={i}
          style={{ height: peak > 0 ? Math.max(MIN_BAR, Math.round((value / peak) * height)) : MIN_BAR }}
        />
      ))}
    </div>
  );
}

LatencySparkline.propTypes = {
  series: PropTypes.arrayOf(PropTypes.number),
  height: PropTypes.number,
};
```

- [ ] **Step 5: Run tests and lint**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-sparkline.test.jsx`
Expected: PASS
Run: `npx eslint src/components/monitors/ && npx prettier --write src/components/monitors/LatencySparkline.jsx src/components/monitors/monitorFormat.js src/__tests__/monitor-sparkline.test.jsx`

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/monitors/LatencySparkline.jsx apps/frontend/src/components/monitors/monitorFormat.js apps/frontend/src/__tests__/monitor-sparkline.test.jsx
git commit -m "feat(monitors): latency sparkline and time formatters"
```

---

### Task 6: `MonitorSummaryStrip`

**Files:**
- Create: `apps/frontend/src/components/monitors/MonitorSummaryStrip.jsx`
- Test: `apps/frontend/src/__tests__/monitor-summary-strip.test.jsx` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `MonitorSummaryStrip({ counts, active, onSelect })` where `counts` is `{total, up, down, pending, paused}`, `active` is a status string or `null`, and `onSelect(statusOrNull)` fires on click — the Total tile and a click on the already-active tile both emit `null`.

- [ ] **Step 1: Write the failing test**

```jsx
// apps/frontend/src/__tests__/monitor-summary-strip.test.jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import MonitorSummaryStrip from '../components/monitors/MonitorSummaryStrip.jsx';

const counts = { total: 18, up: 13, down: 2, pending: 1, paused: 2 };

describe('MonitorSummaryStrip', () => {
  it('shows a count per status', () => {
    render(<MonitorSummaryStrip counts={counts} active={null} onSelect={() => {}} />);
    expect(screen.getByRole('button', { name: /Total 18/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Down 2/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Paused 2/ })).toBeTruthy();
  });

  it('selects a status filter and clears it on a second click', () => {
    const onSelect = vi.fn();
    const { rerender } = render(
      <MonitorSummaryStrip counts={counts} active={null} onSelect={onSelect} />
    );
    fireEvent.click(screen.getByRole('button', { name: /Down 2/ }));
    expect(onSelect).toHaveBeenCalledWith('down');

    rerender(<MonitorSummaryStrip counts={counts} active="down" onSelect={onSelect} />);
    expect(screen.getByRole('button', { name: /Down 2/ }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: /Down 2/ }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it('clears the filter from the Total tile', () => {
    const onSelect = vi.fn();
    render(<MonitorSummaryStrip counts={counts} active="up" onSelect={onSelect} />);
    fireEvent.click(screen.getByRole('button', { name: /Total 18/ }));
    expect(onSelect).toHaveBeenCalledWith(null);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-summary-strip.test.jsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the component**

```jsx
import React from 'react';
import PropTypes from 'prop-types';

const TILES = [
  { key: 'total', label: 'Total', status: null, color: 'var(--color-text)' },
  { key: 'up', label: 'Up', status: 'up', color: 'var(--color-success)' },
  { key: 'down', label: 'Down', status: 'down', color: 'var(--color-danger)' },
  { key: 'pending', label: 'Pending', status: 'pending', color: 'var(--color-warning)' },
  { key: 'paused', label: 'Paused', status: 'paused', color: 'var(--color-muted)' },
];

/**
 * MonitorSummaryStrip — fleet counts that double as the status filter. Clicking
 * the active tile (or Total) clears the filter.
 */
export default function MonitorSummaryStrip({ counts, active, onSelect }) {
  return (
    <div className="mon-tiles">
      {TILES.map((tile) => {
        const isActive = tile.status !== null && active === tile.status;
        return (
          <button
            key={tile.key}
            type="button"
            className="mon-tile"
            aria-pressed={tile.status === null ? undefined : isActive}
            onClick={() => onSelect(isActive || tile.status === null ? null : tile.status)}
          >
            <b style={{ color: tile.color }}>{counts[tile.key] ?? 0}</b>
            <span>{tile.label}</span>
          </button>
        );
      })}
    </div>
  );
}

MonitorSummaryStrip.propTypes = {
  counts: PropTypes.objectOf(PropTypes.number).isRequired,
  active: PropTypes.string,
  onSelect: PropTypes.func.isRequired,
};
```

Note the accessible name is "13 Up" / "18 Total" (count then label), which the test's `/Total 18/` regex would miss — order the markup label-first via `aria-label` instead:

```jsx
          <button
            key={tile.key}
            type="button"
            className="mon-tile"
            aria-label={`${tile.label} ${counts[tile.key] ?? 0}`}
            aria-pressed={tile.status === null ? undefined : isActive}
            onClick={() => onSelect(isActive || tile.status === null ? null : tile.status)}
          >
```

- [ ] **Step 4: Run tests and lint**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-summary-strip.test.jsx`
Expected: PASS
Run: `npx eslint src/components/monitors/MonitorSummaryStrip.jsx && npx prettier --write src/components/monitors/MonitorSummaryStrip.jsx src/__tests__/monitor-summary-strip.test.jsx`

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/monitors/MonitorSummaryStrip.jsx apps/frontend/src/__tests__/monitor-summary-strip.test.jsx
git commit -m "feat(monitors): summary tiles that filter by status"
```

---

### Task 7: `MonitorFilterBar`

**Files:**
- Create: `apps/frontend/src/components/monitors/MonitorFilterBar.jsx`
- Test: `apps/frontend/src/__tests__/monitor-filter-bar.test.jsx` (create)

**Interfaces:**
- Produces: `MonitorFilterBar({ q, onQ, type, onType, typeCounts, sort, onSort })`.
  - `typeCounts`: `{http: 6, icmp: 9, ...}` — only types present in the fleet get a chip.
  - `type`: a check type or `null`; clicking the active chip emits `null`.
  - `sort`: one of `'worst' | 'name' | 'latency' | 'uptime'`.
- Produces: exported `SORT_OPTIONS = [{ value, label }]` for the page to validate URL params against.

- [ ] **Step 1: Write the failing test**

```jsx
// apps/frontend/src/__tests__/monitor-filter-bar.test.jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import MonitorFilterBar from '../components/monitors/MonitorFilterBar.jsx';

const base = {
  q: '',
  onQ: () => {},
  type: null,
  onType: () => {},
  typeCounts: { http: 6, icmp: 9 },
  sort: 'worst',
  onSort: () => {},
};

describe('MonitorFilterBar', () => {
  it('renders a chip per present check type with its count', () => {
    render(<MonitorFilterBar {...base} />);
    expect(screen.getByRole('button', { name: 'HTTP 6' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'ICMP 9' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /DNS/ })).toBeNull();
  });

  it('toggles a type filter', () => {
    const onType = vi.fn();
    const { rerender } = render(<MonitorFilterBar {...base} onType={onType} />);
    fireEvent.click(screen.getByRole('button', { name: 'HTTP 6' }));
    expect(onType).toHaveBeenCalledWith('http');

    rerender(<MonitorFilterBar {...base} type="http" onType={onType} />);
    fireEvent.click(screen.getByRole('button', { name: 'HTTP 6' }));
    expect(onType).toHaveBeenLastCalledWith(null);
  });

  it('reports search text and sort changes', () => {
    const onQ = vi.fn();
    const onSort = vi.fn();
    render(<MonitorFilterBar {...base} onQ={onQ} onSort={onSort} />);
    fireEvent.change(screen.getByPlaceholderText('Search name or target…'), {
      target: { value: 'graf' },
    });
    expect(onQ).toHaveBeenCalledWith('graf');
    fireEvent.change(screen.getByLabelText('Sort monitors'), { target: { value: 'latency' } });
    expect(onSort).toHaveBeenCalledWith('latency');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-filter-bar.test.jsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the component**

```jsx
import React from 'react';
import PropTypes from 'prop-types';

export const SORT_OPTIONS = [
  { value: 'worst', label: 'Worst first' },
  { value: 'name', label: 'Name' },
  { value: 'latency', label: 'Latency' },
  { value: 'uptime', label: 'Uptime' },
];

const TYPE_ORDER = ['http', 'icmp', 'tcp', 'dns'];

/**
 * MonitorFilterBar — search, check-type chips and sort for the monitors wall.
 * Every value is owned by the page (and mirrored into the URL), so this stays
 * presentational.
 */
export default function MonitorFilterBar({ q, onQ, type, onType, typeCounts, sort, onSort }) {
  const types = TYPE_ORDER.filter((t) => Object.hasOwn(typeCounts, t));
  return (
    <div className="mon-toolbar">
      <input
        className="mon-search"
        type="search"
        value={q}
        placeholder="Search name or target…"
        aria-label="Search monitors"
        onChange={(e) => onQ(e.target.value)}
      />
      {types.map((t) => (
        <button
          key={t}
          type="button"
          className="mon-chip"
          aria-pressed={type === t}
          onClick={() => onType(type === t ? null : t)}
        >
          {t.toUpperCase()} {typeCounts[t]}
        </button>
      ))}
      <select
        className="mon-chip"
        aria-label="Sort monitors"
        value={sort}
        onChange={(e) => onSort(e.target.value)}
      >
        {SORT_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

MonitorFilterBar.propTypes = {
  q: PropTypes.string.isRequired,
  onQ: PropTypes.func.isRequired,
  type: PropTypes.string,
  onType: PropTypes.func.isRequired,
  typeCounts: PropTypes.objectOf(PropTypes.number).isRequired,
  sort: PropTypes.string.isRequired,
  onSort: PropTypes.func.isRequired,
};
```

Add `/* eslint-disable security/detect-object-injection -- keys are our own check types */` at the top of the file.

- [ ] **Step 4: Run tests and lint**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-filter-bar.test.jsx`
Expected: PASS
Run: `npx eslint src/components/monitors/MonitorFilterBar.jsx && npx prettier --write src/components/monitors/MonitorFilterBar.jsx src/__tests__/monitor-filter-bar.test.jsx`

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/monitors/MonitorFilterBar.jsx apps/frontend/src/__tests__/monitor-filter-bar.test.jsx
git commit -m "feat(monitors): dashboard search, type chips and sort"
```

---

### Task 8: `MonitorCardDetail`

The expanded body: chart, four stats, full check history, recent events, actions.

**Files:**
- Create: `apps/frontend/src/components/monitors/MonitorCardDetail.jsx`
- Test: `apps/frontend/src/__tests__/monitor-card-detail.test.jsx` (create)

**Interfaces:**
- Consumes: `LatencyChart` (Task 3), `CheckHistoryBar` with `size="md"` (Task 1), `formatSince` (Task 5).
- Produces: `MonitorCardDetail({ monitor, history, events, loading, busy, onCheckNow, onPause, onEdit, onDelete })`. `monitor` is a `MonitorOverview` row; `history` is `[{ts, value}]`; `events` is the newest-first check list.

- [ ] **Step 1: Write the failing test**

```jsx
// apps/frontend/src/__tests__/monitor-card-detail.test.jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../components/monitors/LatencyChart.jsx', () => ({
  default: ({ points }) => <div data-testid="chart">{points.length} points</div>,
}));

import MonitorCardDetail from '../components/monitors/MonitorCardDetail.jsx';

const monitor = {
  id: 4,
  name: 'grafana',
  check_type: 'http',
  host: 'grafana.lan',
  config: { url: 'https://grafana.lan/login' },
  status: 'down',
  enabled: true,
  interval_secs: 60,
  retries: 2,
  max_retries: 2,
  uptime_pct_24h: 41,
  latency_ms: null,
  last_status_change_at: new Date(Date.now() - 372_000).toISOString(),
  target_type: 'service',
  target_id: 9,
};

const events = [
  { id: 2, status_to: 'down', msg: 'connect timeout after 10s', created_at: '2026-07-26T12:41:09Z' },
  { id: 1, status_to: 'pending', msg: 'retry 1/2', created_at: '2026-07-26T12:39:07Z' },
];

function renderDetail(overrides = {}) {
  const props = {
    monitor,
    history: [
      { ts: '2026-07-26T12:00:00Z', value: 30 },
      { ts: '2026-07-26T12:01:00Z', value: 34 },
    ],
    events,
    loading: false,
    busy: false,
    onCheckNow: vi.fn(),
    onPause: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  };
  render(<MonitorCardDetail {...props} />);
  return props;
}

describe('MonitorCardDetail', () => {
  it('shows the chart, the four stats and the recent events', () => {
    renderDetail();
    expect(screen.getByTestId('chart').textContent).toBe('2 points');
    expect(screen.getByText('41%')).toBeTruthy();
    expect(screen.getByText('2 / 2')).toBeTruthy();
    expect(screen.getByText('6m 12s')).toBeTruthy();
    expect(screen.getByText('connect timeout after 10s')).toBeTruthy();
  });

  it('runs each action', () => {
    const props = renderDetail();
    fireEvent.click(screen.getByRole('button', { name: 'Check now' }));
    expect(props.onCheckNow).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    expect(props.onPause).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(props.onEdit).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(props.onDelete).toHaveBeenCalled();
  });

  it('offers Resume for a paused monitor', () => {
    renderDetail({ monitor: { ...monitor, enabled: false } });
    expect(screen.getByRole('button', { name: 'Resume' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Pause' })).toBeNull();
  });

  it('disables the actions while a request is in flight', () => {
    renderDetail({ busy: true });
    expect(screen.getByRole('button', { name: 'Check now' }).disabled).toBe(true);
  });

  it('says so while the detail is still loading', () => {
    renderDetail({ loading: true, history: [], events: [] });
    expect(screen.getByText('Loading check history…')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-card-detail.test.jsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the component**

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import CheckHistoryBar from './CheckHistoryBar';
import LatencyChart from './LatencyChart';
import { formatSince } from './monitorFormat';

/**
 * MonitorCardDetail — the body a monitor card reveals when expanded: 24h
 * latency, headline stats, the full check history, the latest events and the
 * actions. The full-page view stays available for deep links.
 */
export default function MonitorCardDetail({
  monitor,
  history,
  events,
  loading,
  busy,
  onCheckNow,
  onPause,
  onEdit,
  onDelete,
}) {
  const target = monitor.config?.url || monitor.host;
  return (
    <div className="mon-card-detail">
      <p className="mon-target">
        {target} · every {monitor.interval_secs}s
        {monitor.target_type ? ` · ${monitor.target_type.replace('_', ' ')}` : ''}
      </p>

      {loading ? (
        <p className="text-muted">Loading check history…</p>
      ) : (
        <>
          <LatencyChart points={history} height={140} />

          <div className="mon-stats">
            <div>
              <b>{monitor.uptime_pct_24h != null ? `${monitor.uptime_pct_24h}%` : '—'}</b>
              <span>Uptime 24h</span>
            </div>
            <div>
              <b>{monitor.latency_ms != null ? `${Math.round(monitor.latency_ms)} ms` : '—'}</b>
              <span>Latency</span>
            </div>
            <div>
              <b>
                {monitor.retries} / {monitor.max_retries}
              </b>
              <span>Retries used</span>
            </div>
            <div>
              <b>{formatSince(monitor.last_status_change_at)}</b>
              <span>In state</span>
            </div>
          </div>

          <CheckHistoryBar events={events} size="md" />

          {events.length > 0 && (
            <ul className="mon-events">
              {events.slice(0, 5).map((ev) => (
                <li key={ev.id}>
                  <time dateTime={ev.created_at}>
                    {new Date(ev.created_at).toLocaleTimeString()}
                  </time>
                  <span>
                    {ev.status_to} — {ev.msg}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <div className="mon-actions">
        <button type="button" className="btn btn-sm" disabled={busy} onClick={onCheckNow}>
          Check now
        </button>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={onPause}>
          {monitor.enabled ? 'Pause' : 'Resume'}
        </button>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={onEdit}>
          Edit
        </button>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={onDelete}>
          Delete
        </button>
        <Link className="btn btn-sm" to={`/monitors/${monitor.id}`}>
          Open full page →
        </Link>
      </div>
    </div>
  );
}

MonitorCardDetail.propTypes = {
  monitor: PropTypes.object.isRequired,
  history: PropTypes.arrayOf(PropTypes.object).isRequired,
  events: PropTypes.arrayOf(PropTypes.object).isRequired,
  loading: PropTypes.bool,
  busy: PropTypes.bool,
  onCheckNow: PropTypes.func.isRequired,
  onPause: PropTypes.func.isRequired,
  onEdit: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
```

The test renders this without a router, so wrap the render in `MemoryRouter` — update the test's `renderDetail` to:

```jsx
import { MemoryRouter } from 'react-router-dom';
// …
  render(
    <MemoryRouter>
      <MonitorCardDetail {...props} />
    </MemoryRouter>
  );
```

- [ ] **Step 4: Run tests and lint**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-card-detail.test.jsx`
Expected: PASS
Run: `npx eslint src/components/monitors/MonitorCardDetail.jsx && npx prettier --write src/components/monitors/MonitorCardDetail.jsx src/__tests__/monitor-card-detail.test.jsx`

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/monitors/MonitorCardDetail.jsx apps/frontend/src/__tests__/monitor-card-detail.test.jsx
git commit -m "feat(monitors): expanded card body"
```

---

### Task 9: `MonitorCard`

**Files:**
- Create: `apps/frontend/src/components/monitors/MonitorCard.jsx`
- Test: `apps/frontend/src/__tests__/monitor-card.test.jsx` (create)

**Interfaces:**
- Consumes: `LatencySparkline`, `CheckHistoryBar`, `MonitorCardDetail`.
- Produces: `MonitorCard({ monitor, expanded, onToggle, detail, busy, onCheckNow, onPause, onEdit, onDelete })`.
  - `detail`: `{ history: [], events: [], loading: bool }` or `undefined` before the fetch starts.
  - `onToggle(monitorId)` — the page owns the expanded set and the lazy fetch.
  - Exports `groupStatusOf(monitor)` → `'paused'` when `!monitor.enabled`, else `monitor.status`, and `headlineOf(monitor)` → the footer figure string.

- [ ] **Step 1: Write the failing test**

```jsx
// apps/frontend/src/__tests__/monitor-card.test.jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../components/monitors/MonitorCardDetail.jsx', () => ({
  default: ({ monitor }) => <div data-testid="detail">detail for {monitor.name}</div>,
}));

import MonitorCard, { groupStatusOf, headlineOf } from '../components/monitors/MonitorCard.jsx';

const up = {
  id: 1,
  name: 'pve',
  check_type: 'icmp',
  host: '192.168.0.4',
  config: {},
  status: 'up',
  enabled: true,
  latency_ms: 13.6,
  uptime_pct_24h: 100,
  retries: 0,
  max_retries: 0,
  target_type: 'hardware',
  latency_series: [4, 8, 12],
  recent_checks: [],
};

const down = {
  ...up,
  id: 2,
  name: 'grafana',
  check_type: 'http',
  config: { url: 'https://grafana.lan/login' },
  status: 'down',
  latency_ms: null,
  uptime_pct_24h: 41,
  latency_series: [],
  recent_checks: [
    { id: 9, status_to: 'down', msg: 'timeout', created_at: '2026-07-26T12:41:09Z' },
  ],
};

function renderCard(monitor, overrides = {}) {
  const props = {
    monitor,
    expanded: false,
    onToggle: vi.fn(),
    detail: undefined,
    busy: false,
    onCheckNow: vi.fn(),
    onPause: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  };
  const utils = render(
    <MemoryRouter>
      <MonitorCard {...props} />
    </MemoryRouter>
  );
  return { ...utils, props };
}

describe('MonitorCard', () => {
  it('shows a sparkline and latency for a healthy monitor', () => {
    const { container } = renderCard(up);
    expect(screen.getByText('pve')).toBeTruthy();
    expect(screen.getByText('ICMP')).toBeTruthy();
    expect(screen.getByText('192.168.0.4 · hardware')).toBeTruthy();
    expect(screen.getByText('14 ms')).toBeTruthy();
    expect(container.querySelector('.mon-spark')).toBeTruthy();
    expect(container.querySelector('.mon-card').dataset.status).toBe('up');
  });

  it('shows the check history and the target URL for a failing monitor', () => {
    const { container } = renderCard(down);
    expect(screen.getByText('Down')).toBeTruthy();
    expect(screen.getByText('https://grafana.lan/login')).toBeTruthy();
    expect(container.querySelector('.mon-spark')).toBeNull();
    expect(container.querySelector('[aria-label="check history"]')).toBeTruthy();
    expect(container.querySelector('.mon-card').dataset.status).toBe('down');
  });

  it('reads as paused when disabled, whatever its last status', () => {
    const { container } = renderCard({ ...up, enabled: false });
    expect(screen.getByText('Paused')).toBeTruthy();
    expect(container.querySelector('.mon-card').dataset.status).toBe('paused');
  });

  it('toggles on click and on keyboard, and reports its expanded state', () => {
    const { props, rerender } = renderCard(up);
    const face = screen.getByRole('button', { expanded: false });
    fireEvent.click(face);
    expect(props.onToggle).toHaveBeenCalledWith(1);

    rerender(
      <MemoryRouter>
        <MonitorCard {...props} expanded detail={{ history: [], events: [], loading: false }} />
      </MemoryRouter>
    );
    expect(screen.getByRole('button', { expanded: true })).toBeTruthy();
    expect(screen.getByTestId('detail')).toBeTruthy();
  });

  it('derives its group and headline', () => {
    expect(groupStatusOf(up)).toBe('up');
    expect(groupStatusOf({ ...up, enabled: false })).toBe('paused');
    expect(headlineOf(up)).toBe('14 ms');
    expect(headlineOf({ ...up, latency_ms: null })).toBe('Up');
    expect(headlineOf(down)).toBe('Down');
    expect(headlineOf({ ...up, status: 'pending', retries: 1, max_retries: 2 })).toBe('Retry 1/2');
    expect(headlineOf({ ...up, status: 'pending', max_retries: 0 })).toBe('Pending');
    expect(headlineOf({ ...up, enabled: false })).toBe('Paused');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-card.test.jsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the component**

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import CheckHistoryBar from './CheckHistoryBar';
import LatencySparkline from './LatencySparkline';
import MonitorCardDetail from './MonitorCardDetail';

/** Which group a monitor belongs to — a disabled monitor is paused, whatever it last reported. */
export function groupStatusOf(monitor) {
  return monitor.enabled ? monitor.status || 'pending' : 'paused';
}

/** The card footer's headline figure. */
export function headlineOf(monitor) {
  if (!monitor.enabled) return 'Paused';
  switch (monitor.status) {
    case 'up':
      return monitor.latency_ms != null ? `${Math.round(monitor.latency_ms)} ms` : 'Up';
    case 'down':
      return 'Down';
    case 'maintenance':
      return 'Maintenance';
    case 'pending':
      return monitor.max_retries > 0 ? `Retry ${monitor.retries}/${monitor.max_retries}` : 'Pending';
    default:
      return monitor.status || 'Pending';
  }
}

/**
 * MonitorCard — one monitor on the wall. The face is a button that expands the
 * card in place; the expanded body's own buttons sit outside it so they never
 * toggle the card.
 */
export default function MonitorCard({
  monitor,
  expanded,
  onToggle,
  detail,
  busy,
  onCheckNow,
  onPause,
  onEdit,
  onDelete,
}) {
  const status = groupStatusOf(monitor);
  const target = monitor.config?.url || monitor.host;
  const showSparkline = status === 'up' && (monitor.latency_series?.length ?? 0) > 0;

  return (
    <article className="mon-card" data-status={status} data-expanded={expanded || undefined}>
      <button
        type="button"
        className="mon-card-face"
        aria-expanded={expanded}
        onClick={() => onToggle(monitor.id)}
      >
        <span className="mon-card-head">
          <span className="mon-card-name">{monitor.name}</span>
          <span className="mon-badge">{monitor.check_type.toUpperCase()}</span>
        </span>
        <span className="mon-target" style={{ display: 'block' }}>
          {monitor.target_type ? `${target} · ${monitor.target_type.replace('_', ' ')}` : target}
        </span>
        <span className="mon-card-mid" style={{ display: 'block' }}>
          {showSparkline ? (
            <LatencySparkline series={monitor.latency_series} />
          ) : (
            <CheckHistoryBar events={monitor.recent_checks || []} max={20} />
          )}
        </span>
        <span className="mon-card-foot">
          <span className="mon-headline">{headlineOf(monitor)}</span>
          <span className="mon-uptime">
            {monitor.uptime_pct_24h != null ? `${monitor.uptime_pct_24h}% · 24h` : '—'}
          </span>
        </span>
      </button>

      {expanded && (
        <MonitorCardDetail
          monitor={monitor}
          history={detail?.history || []}
          events={detail?.events || monitor.recent_checks || []}
          loading={detail?.loading ?? true}
          busy={busy}
          onCheckNow={onCheckNow}
          onPause={onPause}
          onEdit={onEdit}
          onDelete={onDelete}
        />
      )}
    </article>
  );
}

MonitorCard.propTypes = {
  monitor: PropTypes.object.isRequired,
  expanded: PropTypes.bool,
  onToggle: PropTypes.func.isRequired,
  detail: PropTypes.object,
  busy: PropTypes.bool,
  onCheckNow: PropTypes.func.isRequired,
  onPause: PropTypes.func.isRequired,
  onEdit: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
```

- [ ] **Step 4: Run tests and lint**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-card.test.jsx`
Expected: PASS
Run: `npx eslint src/components/monitors/MonitorCard.jsx && npx prettier --write src/components/monitors/MonitorCard.jsx src/__tests__/monitor-card.test.jsx`

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/monitors/MonitorCard.jsx apps/frontend/src/__tests__/monitor-card.test.jsx
git commit -m "feat(monitors): monitor card with click-to-expand"
```

---

### Task 10: `MonitorGroup`

**Files:**
- Create: `apps/frontend/src/components/monitors/MonitorGroup.jsx`
- Test: `apps/frontend/src/__tests__/monitor-group.test.jsx` (create)

**Interfaces:**
- Consumes: `StatusPing`, `MonitorCard`.
- Produces: `MonitorGroup({ status, monitors, expandedIds, detailsById, busyId, onToggle, onCheckNow, onPause, onEdit, onDelete })`. Renders nothing when `monitors` is empty. Exports `GROUP_LABELS` (`{up: 'Up', down: 'Down', pending: 'Pending', maintenance: 'Maintenance', paused: 'Paused'}`).
- The per-monitor handlers are called as `onCheckNow(monitor)` etc., so the page does not need to close over each row.

- [ ] **Step 1: Write the failing test**

```jsx
// apps/frontend/src/__tests__/monitor-group.test.jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../components/monitors/MonitorCard.jsx', () => ({
  default: ({ monitor }) => <div data-testid="card">{monitor.name}</div>,
}));

import MonitorGroup from '../components/monitors/MonitorGroup.jsx';

const monitors = [
  { id: 1, name: 'grafana' },
  { id: 2, name: 'unifi' },
];

const handlers = {
  onToggle: vi.fn(),
  onCheckNow: vi.fn(),
  onPause: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
};

describe('MonitorGroup', () => {
  it('labels the group, counts it, and pings in its status colour', () => {
    const { container } = render(
      <MemoryRouter>
        <MonitorGroup
          status="down"
          monitors={monitors}
          expandedIds={new Set()}
          detailsById={{}}
          {...handlers}
        />
      </MemoryRouter>
    );
    expect(screen.getByRole('heading', { name: /Down · 2/ })).toBeTruthy();
    expect(container.querySelector('.mon-ping').dataset.status).toBe('down');
    expect(screen.getAllByTestId('card')).toHaveLength(2);
  });

  it('renders nothing for an empty group', () => {
    const { container } = render(
      <MemoryRouter>
        <MonitorGroup
          status="up"
          monitors={[]}
          expandedIds={new Set()}
          detailsById={{}}
          {...handlers}
        />
      </MemoryRouter>
    );
    expect(container.querySelector('.mon-group')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-group.test.jsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the component**

```jsx
/* eslint-disable security/detect-object-injection -- keys are our own status strings */
import React from 'react';
import PropTypes from 'prop-types';
import MonitorCard from './MonitorCard';
import StatusPing from './StatusPing';

export const GROUP_LABELS = {
  down: 'Down',
  pending: 'Pending',
  maintenance: 'Maintenance',
  up: 'Up',
  paused: 'Paused',
};

/**
 * MonitorGroup — one status band of the wall: a heading with its pulsing ping
 * and count, then the cards. Empty groups render nothing.
 */
export default function MonitorGroup({
  status,
  monitors,
  expandedIds,
  detailsById,
  busyId,
  onToggle,
  onCheckNow,
  onPause,
  onEdit,
  onDelete,
}) {
  if (monitors.length === 0) return null;
  return (
    <section className="mon-group">
      <h3 className="mon-group-title">
        <StatusPing status={status} />
        {GROUP_LABELS[status] || status} · {monitors.length}
      </h3>
      <div className="mon-wall">
        {monitors.map((m) => (
          <MonitorCard
            key={m.id}
            monitor={m}
            expanded={expandedIds.has(m.id)}
            detail={detailsById[m.id]}
            busy={busyId === m.id}
            onToggle={onToggle}
            onCheckNow={() => onCheckNow(m)}
            onPause={() => onPause(m)}
            onEdit={() => onEdit(m)}
            onDelete={() => onDelete(m)}
          />
        ))}
      </div>
    </section>
  );
}

MonitorGroup.propTypes = {
  status: PropTypes.string.isRequired,
  monitors: PropTypes.arrayOf(PropTypes.object).isRequired,
  expandedIds: PropTypes.instanceOf(Set).isRequired,
  detailsById: PropTypes.object.isRequired,
  busyId: PropTypes.number,
  onToggle: PropTypes.func.isRequired,
  onCheckNow: PropTypes.func.isRequired,
  onPause: PropTypes.func.isRequired,
  onEdit: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
```

- [ ] **Step 4: Run tests and lint**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitor-group.test.jsx`
Expected: PASS
Run: `npx eslint src/components/monitors/MonitorGroup.jsx && npx prettier --write src/components/monitors/MonitorGroup.jsx src/__tests__/monitor-group.test.jsx`

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/monitors/MonitorGroup.jsx apps/frontend/src/__tests__/monitor-group.test.jsx
git commit -m "feat(monitors): status group band for the wall"
```

---

### Task 11: Rewrite `MonitorsPage`

**Files:**
- Modify: `apps/frontend/src/pages/MonitorsPage.jsx` (full rewrite)
- Test: `apps/frontend/src/__tests__/monitors-dashboard.test.jsx` (create)

**Interfaces:**
- Consumes: `getMonitorsOverview` (Task 2), `MonitorSummaryStrip`, `MonitorFilterBar` + `SORT_OPTIONS`, `MonitorGroup`, `groupStatusOf` (Task 9), `formatAgo` (Task 5), plus the existing `createMonitor`, `updateMonitor`, `deleteMonitor`, `pauseMonitor`, `resumeMonitor`, `runCheck`, `getMonitorEvents`, `getMonitorHistory`, `useMonitorStream`, `MonitorForm`, `ConfirmDialog`, `useToast`.
- Produces: the page. No exports beyond the default.

- [ ] **Step 1: Write the failing test**

```jsx
// apps/frontend/src/__tests__/monitors-dashboard.test.jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/monitor', () => ({
  getMonitorsOverview: vi.fn(),
  getMonitorEvents: vi.fn().mockResolvedValue({ data: [] }),
  getMonitorHistory: vi.fn().mockResolvedValue({ data: [] }),
  createMonitor: vi.fn().mockResolvedValue({ data: {} }),
  updateMonitor: vi.fn().mockResolvedValue({ data: {} }),
  deleteMonitor: vi.fn().mockResolvedValue({ data: {} }),
  pauseMonitor: vi.fn().mockResolvedValue({ data: {} }),
  resumeMonitor: vi.fn().mockResolvedValue({ data: {} }),
  runCheck: vi.fn().mockResolvedValue({ data: {} }),
}));

let mockStatuses = new Map();
vi.mock('../hooks/useMonitorStream', () => ({
  useMonitorStream: () => ({ statuses: mockStatuses, connected: true }),
}));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));
vi.mock('../components/monitors/MonitorForm', () => ({
  default: ({ onCancel }) => (
    <div data-testid="form">
      <button onClick={onCancel}>close form</button>
    </div>
  ),
}));
vi.mock('../components/monitors/LatencyChart', () => ({ default: () => <div>chart</div> }));

import {
  getMonitorEvents,
  getMonitorHistory,
  getMonitorsOverview,
  pauseMonitor,
  runCheck,
} from '../api/monitor';
import MonitorsPage from '../pages/MonitorsPage.jsx';

const row = (over) => ({
  id: 1,
  name: 'pve',
  check_type: 'icmp',
  host: '192.168.0.4',
  config: {},
  status: 'up',
  enabled: true,
  interval_secs: 60,
  retries: 0,
  max_retries: 0,
  uptime_pct_24h: 100,
  latency_ms: 13,
  last_polled_at: new Date().toISOString(),
  last_status_change_at: new Date().toISOString(),
  target_type: 'hardware',
  target_id: 30,
  latency_series: [10, 12, 13],
  recent_checks: [],
  ...over,
});

const fleet = [
  row({ id: 1, name: 'pve' }),
  row({
    id: 2,
    name: 'grafana',
    check_type: 'http',
    config: { url: 'https://grafana.lan' },
    status: 'down',
    latency_ms: null,
    uptime_pct_24h: 41,
    latency_series: [],
    recent_checks: [
      { id: 5, status_to: 'down', msg: 'timeout', created_at: '2026-07-26T12:41:09Z' },
    ],
  }),
  row({ id: 3, name: 'old-nas', enabled: false, status: 'up' }),
];

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/monitors']}>
      <MonitorsPage />
    </MemoryRouter>
  );
}

describe('MonitorsPage dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStatuses = new Map();
    getMonitorsOverview.mockResolvedValue({ data: fleet });
    getMonitorEvents.mockResolvedValue({ data: [] });
    getMonitorHistory.mockResolvedValue({ data: [] });
  });

  it('costs exactly one request for the whole wall', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());
    expect(getMonitorsOverview).toHaveBeenCalledTimes(1);
    expect(getMonitorEvents).not.toHaveBeenCalled();
  });

  it('summarises the fleet and groups it worst-first', async () => {
    const { container } = renderPage();
    await waitFor(() => expect(screen.getByText('grafana')).toBeTruthy());

    expect(screen.getByRole('button', { name: 'Total 3' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Up 1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Down 1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Paused 1' })).toBeTruthy();

    const headings = [...container.querySelectorAll('.mon-group-title')].map((h) =>
      h.textContent.trim()
    );
    expect(headings[0]).toContain('Down');
    expect(headings[headings.length - 1]).toContain('Paused');
  });

  it('filters by status from a tile', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Down 1' }));
    await waitFor(() => expect(screen.queryByText('pve')).toBeNull());
    expect(screen.getByText('grafana')).toBeTruthy();
  });

  it('filters by check type and by search text', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'HTTP 1' }));
    await waitFor(() => expect(screen.queryByText('pve')).toBeNull());

    fireEvent.click(screen.getByRole('button', { name: 'HTTP 1' }));
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Search monitors'), { target: { value: 'graf' } });
    await waitFor(() => expect(screen.queryByText('pve')).toBeNull());
    expect(screen.getByText('grafana')).toBeTruthy();
  });

  it('offers a way back when filters hide everything', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('Search monitors'), { target: { value: 'zzz' } });
    await waitFor(() => expect(screen.getByText('No monitors match.')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());
  });

  it('fetches a card detail once when expanded', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());

    const face = screen.getByText('pve').closest('button');
    fireEvent.click(face);
    await waitFor(() => expect(getMonitorHistory).toHaveBeenCalledWith(1, { hours: 24 }));
    expect(getMonitorEvents).toHaveBeenCalledWith(1, 40);

    fireEvent.click(face);
    fireEvent.click(face);
    await waitFor(() => expect(screen.getByText('Check now')).toBeTruthy());
    expect(getMonitorHistory).toHaveBeenCalledTimes(1);
  });

  it('runs actions from the expanded card', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('pve')).toBeTruthy());
    fireEvent.click(screen.getByText('pve').closest('button'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Check now' })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Check now' }));
    await waitFor(() => expect(runCheck).toHaveBeenCalledWith(1));

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(pauseMonitor).toHaveBeenCalledWith(1));
  });

  it('folds live status pushes into the wall', async () => {
    const { rerender } = renderPage();
    await waitFor(() => expect(screen.getByText('14 ms')).toBeTruthy());

    mockStatuses = new Map([
      [1, { status: 'down', msg: 'timeout', ts: new Date().toISOString() }],
    ]);
    rerender(
      <MemoryRouter initialEntries={['/monitors']}>
        <MonitorsPage />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByRole('button', { name: 'Down 2' })).toBeTruthy());
  });

  it('invites the first monitor when there are none', async () => {
    getMonitorsOverview.mockResolvedValue({ data: [] });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/No monitors yet/)).toBeTruthy()
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitors-dashboard.test.jsx`
Expected: FAIL — the page still calls `listMonitors` and renders `EntityTable`.

- [ ] **Step 3: Rewrite the page**

```jsx
/* eslint-disable security/detect-object-injection -- keys are monitor ids and our own status strings */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Activity } from 'lucide-react';
import {
  createMonitor,
  deleteMonitor,
  getMonitorEvents,
  getMonitorHistory,
  getMonitorsOverview,
  pauseMonitor,
  resumeMonitor,
  runCheck,
  updateMonitor,
} from '../api/monitor';
import { useMonitorStream } from '../hooks/useMonitorStream';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import MonitorForm from '../components/monitors/MonitorForm';
import MonitorFilterBar, { SORT_OPTIONS } from '../components/monitors/MonitorFilterBar';
import MonitorGroup from '../components/monitors/MonitorGroup';
import MonitorSummaryStrip from '../components/monitors/MonitorSummaryStrip';
import { groupStatusOf } from '../components/monitors/MonitorCard';
import { formatAgo } from '../components/monitors/monitorFormat';
import '../styles/monitors.css';

const GROUP_ORDER = ['down', 'pending', 'maintenance', 'up', 'paused'];
const REFRESH_MS = 60000;
const SERIES_MAX = 12;
const CHECKS_MAX = 20;
const SORT_VALUES = SORT_OPTIONS.map((o) => o.value);

function groupRank(status) {
  const i = GROUP_ORDER.indexOf(status);
  return i === -1 ? GROUP_ORDER.length : i;
}

function sortMonitors(monitors, sort) {
  const byName = (a, b) => a.name.localeCompare(b.name);
  const nullsLast = (v) => (v == null ? Number.POSITIVE_INFINITY : v);
  const copy = [...monitors];
  switch (sort) {
    case 'name':
      return copy.sort(byName);
    case 'latency':
      return copy.sort((a, b) => nullsLast(b.latency_ms) - nullsLast(a.latency_ms) || byName(a, b));
    case 'uptime':
    case 'worst':
    default:
      return copy.sort(
        (a, b) => nullsLast(a.uptime_pct_24h) - nullsLast(b.uptime_pct_24h) || byName(a, b)
      );
  }
}

export default function MonitorsPage() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [monitors, setMonitors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedIds, setExpandedIds] = useState(() => new Set());
  const [detailsById, setDetailsById] = useState({});
  const [busyId, setBusyId] = useState(null);
  const [editing, setEditing] = useState(null); // null | 'new' | monitor
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });
  const [now, setNow] = useState(() => Date.now());

  const statusFilter = params.get('status');
  const typeFilter = params.get('type');
  const q = params.get('q') || '';
  const sort = SORT_VALUES.includes(params.get('sort')) ? params.get('sort') : 'worst';

  const setParam = useCallback(
    (key, value) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value) next.set(key, value);
          else next.delete(key);
          return next;
        },
        { replace: true }
      );
    },
    [setParams]
  );

  const refresh = useCallback(async () => {
    try {
      const { data } = await getMonitorsOverview();
      setMonitors(data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to load monitors');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    refreshRef.current();
    const t = setInterval(() => refreshRef.current(), REFRESH_MS); // safety net under the WS push
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000); // the header's last-check ticker
    return () => clearInterval(t);
  }, []);

  const monitorIds = useMemo(() => monitors.map((m) => m.id), [monitors]);
  const { statuses } = useMonitorStream({ monitorIds });

  // Fold live pushes onto the fetched rows: status, latency, and both series.
  const live = useMemo(() => {
    if (statuses.size === 0) return monitors;
    return monitors.map((m) => {
      const push = statuses.get(m.id);
      if (!push) return m;
      const check = {
        id: `live-${push.ts}`,
        status_to: push.status,
        msg: push.msg || '',
        created_at: push.ts,
      };
      const alreadyLogged = (m.recent_checks || [])[0]?.created_at === push.ts;
      return {
        ...m,
        status: push.status,
        last_polled_at: push.ts || m.last_polled_at,
        recent_checks: alreadyLogged
          ? m.recent_checks
          : [check, ...(m.recent_checks || [])].slice(0, CHECKS_MAX),
        latency_series:
          push.latency_ms != null
            ? [...(m.latency_series || []), push.latency_ms].slice(-SERIES_MAX)
            : m.latency_series,
      };
    });
  }, [monitors, statuses]);

  const counts = useMemo(() => {
    const acc = { total: live.length, up: 0, down: 0, pending: 0, paused: 0, maintenance: 0 };
    for (const m of live) {
      const status = groupStatusOf(m);
      if (Object.hasOwn(acc, status)) acc[status] += 1;
    }
    return acc;
  }, [live]);

  const typeCounts = useMemo(() => {
    const acc = {};
    for (const m of live) acc[m.check_type] = (acc[m.check_type] || 0) + 1;
    return acc;
  }, [live]);

  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return live.filter((m) => {
      if (statusFilter && groupStatusOf(m) !== statusFilter) return false;
      if (typeFilter && m.check_type !== typeFilter) return false;
      if (!needle) return true;
      const target = `${m.name} ${m.host} ${m.config?.url || ''}`.toLowerCase();
      return target.includes(needle);
    });
  }, [live, statusFilter, typeFilter, q]);

  const groups = useMemo(() => {
    const byStatus = {};
    for (const m of visible) {
      const status = groupStatusOf(m);
      (byStatus[status] = byStatus[status] || []).push(m);
    }
    return Object.entries(byStatus)
      .map(([status, list]) => [status, sortMonitors(list, sort)])
      .sort((a, b) => groupRank(a[0]) - groupRank(b[0]));
  }, [visible, sort]);

  const lastCheck = useMemo(() => {
    const times = live.map((m) => m.last_polled_at).filter(Boolean);
    return times.length ? times.reduce((a, b) => (a > b ? a : b)) : null;
  }, [live]);

  const loadDetail = useCallback(async (monitorId) => {
    setDetailsById((prev) => ({ ...prev, [monitorId]: { history: [], events: [], loading: true } }));
    try {
      const [hist, ev] = await Promise.all([
        getMonitorHistory(monitorId, { hours: 24 }),
        getMonitorEvents(monitorId, 40),
      ]);
      setDetailsById((prev) => ({
        ...prev,
        [monitorId]: { history: hist.data, events: ev.data, loading: false },
      }));
    } catch {
      setDetailsById((prev) => ({
        ...prev,
        [monitorId]: { history: [], events: [], loading: false },
      }));
    }
  }, []);

  const handleToggle = useCallback(
    (monitorId) => {
      setExpandedIds((prev) => {
        const next = new Set(prev);
        if (next.has(monitorId)) next.delete(monitorId);
        else next.add(monitorId);
        return next;
      });
      setDetailsById((prev) => {
        if (!prev[monitorId]) loadDetail(monitorId);
        return prev;
      });
    },
    [loadDetail]
  );

  const runAction = useCallback(
    async (monitor, fn, successMsg, { reloadDetail = false } = {}) => {
      setBusyId(monitor.id);
      try {
        await fn();
        toast.success(successMsg);
        await refreshRef.current();
        if (reloadDetail && expandedIds.has(monitor.id)) await loadDetail(monitor.id);
      } catch (err) {
        toast.error(err?.response?.data?.detail || 'Failed to update monitor');
      } finally {
        setBusyId(null);
      }
    },
    [expandedIds, loadDetail, toast]
  );

  const handleCheckNow = useCallback(
    (m) => runAction(m, () => runCheck(m.id), 'Probe triggered.', { reloadDetail: true }),
    [runAction]
  );
  const handlePause = useCallback(
    (m) =>
      runAction(
        m,
        () => (m.enabled ? pauseMonitor(m.id) : resumeMonitor(m.id)),
        m.enabled ? 'Monitoring paused.' : 'Monitoring resumed.'
      ),
    [runAction]
  );
  const handleEdit = useCallback((m) => setEditing(m), []);
  const handleDelete = useCallback(
    (m) =>
      setConfirmState({
        open: true,
        message: `Delete monitor "${m.name}"? This cannot be undone.`,
        onConfirm: async () => {
          setConfirmState((s) => ({ ...s, open: false }));
          await runAction(m, () => deleteMonitor(m.id), 'Monitor deleted.');
        },
      }),
    [runAction]
  );

  const handleSubmit = async (form) => {
    if (editing === 'new') await createMonitor(form);
    else await updateMonitor(editing.id, form);
    setEditing(null);
    toast.success('Monitor saved.');
    await refreshRef.current();
  };

  const clearFilters = () =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        ['status', 'type', 'q'].forEach((k) => next.delete(k));
        return next;
      },
      { replace: true }
    );

  const filtersActive = Boolean(statusFilter || typeFilter || q);

  return (
    <div className="page">
      <div className="page-header">
        <div className="tw-flex tw-items-center tw-gap-3">
          <Activity className="tw-text-cb-primary" size={24} />
          <h2>Monitors</h2>
          {lastCheck && (
            <span className="mon-uptime">last check {formatAgo(lastCheck, now)}</span>
          )}
        </div>
        <button className="btn btn-primary" onClick={() => setEditing('new')}>
          + Add monitor
        </button>
      </div>

      {loading ? (
        <div className="mon-wall">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="mon-skeleton" />
          ))}
        </div>
      ) : monitors.length === 0 ? (
        <div className="mon-empty">
          <p>No monitors yet — add one to start watching a host, service or URL.</p>
          <p className="text-muted" style={{ fontSize: '0.8rem', marginTop: 6 }}>
            You can also switch monitoring on for anything in your inventory from the Hardware,
            Compute, Services and External pages.
          </p>
          <button
            className="btn btn-primary"
            style={{ marginTop: 12 }}
            onClick={() => setEditing('new')}
          >
            + Add monitor
          </button>
        </div>
      ) : (
        <>
          <MonitorSummaryStrip
            counts={counts}
            active={statusFilter}
            onSelect={(status) => setParam('status', status)}
          />
          <MonitorFilterBar
            q={q}
            onQ={(value) => setParam('q', value)}
            type={typeFilter}
            onType={(value) => setParam('type', value)}
            typeCounts={typeCounts}
            sort={sort}
            onSort={(value) => setParam('sort', value === 'worst' ? null : value)}
          />

          {visible.length === 0 ? (
            <div className="mon-empty">
              <p>No monitors match.</p>
              <button className="btn" style={{ marginTop: 12 }} onClick={clearFilters}>
                Clear filters
              </button>
            </div>
          ) : (
            groups.map(([status, list]) => (
              <MonitorGroup
                key={status}
                status={status}
                monitors={list}
                expandedIds={expandedIds}
                detailsById={detailsById}
                busyId={busyId}
                onToggle={handleToggle}
                onCheckNow={handleCheckNow}
                onPause={handlePause}
                onEdit={handleEdit}
                onDelete={handleDelete}
              />
            ))
          )}
        </>
      )}

      {filtersActive && !loading && monitors.length > 0 && visible.length > 0 && (
        <p className="text-muted" style={{ marginTop: 12, fontSize: '0.75rem' }}>
          Showing {visible.length} of {monitors.length} monitors ·{' '}
          <button className="btn btn-sm" onClick={clearFilters}>
            Clear filters
          </button>
        </p>
      )}

      {editing && (
        <MonitorForm
          initial={editing === 'new' ? null : editing}
          onSubmit={handleSubmit}
          onCancel={() => setEditing(null)}
        />
      )}

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}
```

- [ ] **Step 4: Run the page tests**

Run: `cd apps/frontend && npx vitest run src/__tests__/monitors-dashboard.test.jsx`
Expected: PASS

- [ ] **Step 5: Run the whole frontend suite and lint**

Run: `cd apps/frontend && npx vitest run`
Expected: PASS — no other test imports `MonitorsPage`, but `map-page`, `hardware-page` and the monitor component tests all exercise shared components.
Run: `npx eslint src/ && npx prettier --write src/pages/MonitorsPage.jsx src/__tests__/monitors-dashboard.test.jsx`

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/pages/MonitorsPage.jsx apps/frontend/src/__tests__/monitors-dashboard.test.jsx
git commit -m "feat(monitors): card-wall dashboard with filters and expandable cards"
```

---

### Task 12: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Backend suite**

Run:
```bash
cd apps/backend && /home/shawnji/workspace/CircuitBreaker/.venv/bin/python -m pytest tests/api tests/services -q --no-cov -o addopts="" --deselect tests/services/test_snapshot.py
```
Expected: PASS. `test_snapshot.py` is deselected because `pg_dump` is broken on this host (pre-existing).

- [ ] **Step 2: Frontend suite and lint**

Run: `cd apps/frontend && npx vitest run && npx eslint src/`
Expected: all tests pass, eslint reports 0 errors (10 pre-existing warnings in untouched files are fine).

- [ ] **Step 3: Production build**

Run: `cd apps/frontend && npx vite build`
Expected: succeeds — catches any bad import path the tests' module mocks hid.

- [ ] **Step 4: Live check against the dev stack**

With `make deps-up` running plus the backend and monitor workers:
```bash
curl -s localhost:8000/api/v1/monitors/overview | head -c 400
```
Expected: a JSON array whose rows carry `latency_series` and `recent_checks`. Then load `/monitors` in the browser and confirm: tiles filter, chips filter, a card expands with a chart, the group pings pulse, and a paused monitor sits dimmed in its own group.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix(monitors): dashboard verification follow-ups"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 Page anatomy — header, tiles, toolbar, groups, grid | 11 (composition), 6, 7, 10 |
| §1 Card face | 9 |
| §1 Expanded card | 8 |
| §2 Components table | 4–11, one task per file |
| §2 Styling convention (`styles/monitors.css`) | 4 |
| §2 Theme tokens | 1 |
| §3 Group ping cadence + reduced motion | 4 |
| §4 Overview endpoint, orderings, bulk queries, route precedence | 2 |
| §4 Loading strategy (lazy detail, cache, invalidate on check) | 11 |
| §4 WebSocket folding | 11 |
| §4 Filter/sort/search in URL params | 11 |
| §5 States — skeleton, no monitors, no matches, toast on error | 11 |
| §6 Accessibility — `aria-expanded`, focus-visible, no colour-only status, aria-hidden pings | 4, 9, 11 |
| §7 Testing — backend shape/order/caps/precedence, frontend behaviour, N+1 guard | 2, 11 |

**Placeholder scan:** none — every step carries the code or command to run.

**Type consistency:** `latency_series: list[float]` and `recent_checks: [{id, status_to, msg, created_at}]` are produced in Task 2 and consumed with those exact names in Tasks 9 and 11. `groupStatusOf` is defined in Task 9 and imported by Tasks 10 and 11. `SORT_OPTIONS` is defined in Task 7 and imported in Task 11. `CheckHistoryBar`'s `size` prop is added in Task 1 and used in Task 8. `formatAgo`/`formatSince` are defined in Task 5 and used in Tasks 8 and 11.
