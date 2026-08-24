# UI-4 — Business Intelligence

**Supports:** INC-10
**Depends on:** nothing
**Spec:** [Missing UIs](../10-missing-uis.md) §8

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the three implemented intelligence endpoints a user surface: capacity forecasts and right-sizing as ranked tables on a page, blast radius as a panel on the asset it describes.

**Architecture:** A new `/intel` page for the two precomputed tables, and a `BlastRadiusPanel` mounted into the four detail views whose asset types the endpoint accepts, following the existing `VulnerabilityPanel` pattern exactly.

**Tech Stack:** React 18, vitest + @testing-library/react; FastAPI, SQLAlchemy, pytest.

## Global Constraints

- **Every new surface is its own file. Host files gain a registration line, not a feature.**
- **Visible to all authenticated users** (spec D8). `main.py:1927` mounts the intel router with `dependencies=[Depends(require_auth)]` and no role check; the UI must not diverge from that in either direction — no role gate on the route, no role gate on the nav entry.
- **No table may render a bare integer where an asset name belongs.**
- **An empty table must never be indistinguishable from a broken one.** The empty state names the job that fills it and its schedule.
- **Zero impact is an answer, not an empty state.** "Nothing depends on this" is the most useful thing blast radius can say before maintenance.
- **Blast radius fetches on expand, not on detail mount** — it walks the dependency graph, and every hardware drawer opening should not pay for that.

---

## One spec item that turns out not to need backend work

Spec §8.2 lists **B9 — empty-state distinguishability** as a backend delta, so that "the analytics job has not run" can be told from "nothing to report".

On inspection it cannot be delivered that way without new state. `analytics_job` writes rows only when it finds something (`CronTrigger(hour=2, minute=30)`, `main.py:1318-1323`); a run that finds nothing writes nothing. So `max(evaluated_at)` — the only signal available without a new table — is `NULL` in **both** cases and distinguishes nothing. Genuine distinguishability needs job-run tracking, which is a scheduler-observability feature, not a BI one.

**This slice therefore delivers B9 as copy, not as an endpoint:** the empty state names the job, its schedule, and *both* reasons the list can be empty, so the operator is not left guessing which one they are looking at. Task 3 has the exact wording. Job-run tracking is noted in the register as the thing that would make it precise, and is not built here.

**B8 (names in the response) is a real backend delta and is Task 1.**

---

## File Structure

**Create**

| File | Responsibility |
|---|---|
| `apps/frontend/src/api/intel.js` | The three endpoints. |
| `apps/frontend/src/pages/IntelPage.jsx` | Both ranked tables and their empty/error states. |
| `apps/frontend/src/components/details/BlastRadiusPanel.jsx` | Per-asset impact, collapsed until expanded. |
| `apps/frontend/src/__tests__/intel-api.test.js` | Pins URLs. |
| `apps/frontend/src/__tests__/intel-page.test.jsx` | Tables, names, empty and error states. |
| `apps/frontend/src/__tests__/blast-radius-panel.test.jsx` | Lazy fetch, grouping, zero-impact. |
| `docs/business-intelligence-ui.md` | *(not created — `docs/business_intelligence.md` already exists and is edited in Task 6.)* |

**Modify**

| File | Change |
|---|---|
| `apps/backend/src/app/api/intel.py` | Names on both list responses. |
| `apps/backend/tests/api/test_intel_api.py` | Create if absent; name and ordering tests. |
| `apps/frontend/src/App.jsx` | One lazy import, one route. |
| `apps/frontend/src/data/navigation.js` | `NAV_ITEMS`, `NAV_MAP`, `DEFAULT_ORDER`. |
| `apps/frontend/src/components/details/{Hardware,Compute,Service,Storage}Detail.jsx` | One line each. |
| `docs/business_intelligence.md`, `mkdocs.yml`, `docs/1.0.0-incomplete-features.md` | Docs and register. |

---

## Task 1: Names in the intel responses (B8)

`CapacityForecastOut` returns `hardware_id`; `ResourceEfficiencyOut` returns `asset_type` + `asset_id`. Neither returns a name, so a table built on them shows bare integers.

**Files:**
- Modify: `apps/backend/src/app/api/intel.py`
- Test: `apps/backend/tests/api/test_intel_api.py`

**Interfaces:**
- Produces: `CapacityForecastOut.hardware_name: str | None`, `ResourceEfficiencyOut.asset_name: str | None`

**Query discipline:** forecasts join through the existing `CapacityForecast.hardware` relationship (`models.py:2682`) with `joinedload` — one query. Efficiency rows are polymorphic across four types, so they are resolved by grouping the page's rows by `asset_type` and issuing **at most one query per distinct type present** (four maximum, and only for types actually in the result). Never one query per row.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/api/test_intel_api.py`:

```python
"""Integration tests for the /api/v1/intel endpoints."""

from __future__ import annotations

import pytest

from app.db.models import CapacityForecast, ResourceEfficiencyRecommendation


@pytest.mark.asyncio
async def test_capacity_forecasts_include_the_hardware_name(
    client, auth_headers, factories, db_session
):
    """A table of bare hardware_id integers is unusable — the name must come
    from the response, not from four extra client-side lookups."""
    hw = factories.hardware(name="nas-01")
    db_session.add(
        CapacityForecast(
            hardware_id=hw.id,
            metric="disk",
            slope_per_day=0.9,
            current_value=87.0,
            warning_threshold_days=30,
        )
    )
    db_session.flush()

    resp = await client.get("/api/v1/intel/capacity-forecasts", headers=auth_headers)
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["hardware_id"] == hw.id
    assert row["hardware_name"] == "nas-01"


@pytest.mark.asyncio
async def test_resource_efficiency_includes_the_asset_name(
    client, auth_headers, factories, db_session
):
    cu = factories.compute_unit(name="vm-jellyfin")
    db_session.add(
        ResourceEfficiencyRecommendation(
            asset_type="compute_unit",
            asset_id=cu.id,
            classification="over_provisioned",
            cpu_avg_pct=3.0,
            cpu_peak_pct=11.0,
            mem_avg_pct=18.0,
            recommendation="Reduce from 8 vCPU to 2",
        )
    )
    db_session.flush()

    resp = await client.get("/api/v1/intel/resource-efficiency", headers=auth_headers)
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["asset_name"] == "vm-jellyfin"


@pytest.mark.asyncio
async def test_resource_efficiency_tolerates_a_deleted_asset(
    client, auth_headers, db_session
):
    """asset_id is not a foreign key (models.py:2693), so a recommendation can
    outlive its asset. That must render as a missing name, not a 500."""
    db_session.add(
        ResourceEfficiencyRecommendation(
            asset_type="service",
            asset_id=999_999,
            classification="under_provisioned",
            recommendation="Increase memory allocation",
        )
    )
    db_session.flush()

    resp = await client.get("/api/v1/intel/resource-efficiency", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()[0]["asset_name"] is None


@pytest.mark.asyncio
async def test_intel_requires_authentication_but_not_a_role(
    client, viewer_headers
):
    """Spec D8: the router is mounted with require_auth and no role check, so a
    viewer can read it. The UI must match this, not gate below it."""
    for path in ("capacity-forecasts", "resource-efficiency"):
        resp = await client.get(f"/api/v1/intel/{path}", headers=viewer_headers)
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_efficiency_names_do_not_scale_queries_with_row_count(
    client, auth_headers, factories, db_session
):
    """Resolving names must be per-asset-TYPE, never per row."""
    for i in range(15):
        cu = factories.compute_unit(name=f"vm-{i}")
        db_session.add(
            ResourceEfficiencyRecommendation(
                asset_type="compute_unit",
                asset_id=cu.id,
                classification="over_provisioned",
                recommendation="Reduce vCPU",
            )
        )
    db_session.flush()

    with _capture_sql() as statements:
        resp = await client.get("/api/v1/intel/resource-efficiency", headers=auth_headers)

    assert resp.status_code == 200
    assert len(resp.json()) == 15
    compute_selects = [
        s
        for s in statements
        if "compute_units" in s.lower() and s.lstrip().upper().startswith("SELECT")
    ]
    assert len(compute_selects) == 1, compute_selects
```

Add the SQL-capture helper at the top of the new file, copied from `tests/api/test_agents_api.py:45-56` so both files pin query counts the same way:

```python
import contextlib

from sqlalchemy import event


@contextlib.contextmanager
def _capture_sql():
    from app.db.session import engine

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "after_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "after_cursor_execute", _record)
```

Before running, confirm `factories.hardware` and `factories.compute_unit` exist and accept `name` — check `apps/backend/tests/factories.py`. If a factory is named differently, use the existing one rather than adding a new factory.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/backend/tests/api/test_intel_api.py -v`
Expected: FAIL — `KeyError: 'hardware_name'` / `'asset_name'`.

- [ ] **Step 3: Add the fields and resolve them**

In `apps/backend/src/app/api/intel.py`:

Add to `CapacityForecastOut`:

```python
    hardware_name: str | None = None
```

Add to `ResourceEfficiencyOut`:

```python
    asset_name: str | None = None
```

Replace `list_capacity_forecasts` and `list_resource_efficiency` with:

```python
@router.get("/capacity-forecasts", response_model=list[CapacityForecastOut])
def list_capacity_forecasts(db: Session = Depends(get_db)) -> list[CapacityForecastOut]:
    """Return all capacity forecasts ordered by projected saturation date.

    The hardware name is joined in rather than left to the caller: the table
    this feeds is unreadable as a list of integer ids, and resolving them
    client-side would be one extra request per row.
    """
    rows = (
        db.query(CapacityForecast)
        .options(joinedload(CapacityForecast.hardware))
        .order_by(CapacityForecast.projected_full_at.asc().nulls_last())
        .all()
    )
    out: list[CapacityForecastOut] = []
    for row in rows:
        item = CapacityForecastOut.model_validate(row)
        item.hardware_name = getattr(row.hardware, "name", None)
        out.append(item)
    return out


def _resolve_asset_names(
    db: Session, rows: list[ResourceEfficiencyRecommendation]
) -> dict[tuple[str, int], str]:
    """id -> name for every asset referenced by `rows`, in one query per
    asset TYPE present (at most four), never one per row.

    `asset_id` is not a foreign key (models.py:2693), so a recommendation can
    outlive the asset it describes. A missing entry here becomes a null name,
    which the UI renders as an unknown asset — deleting a host must not turn
    this endpoint into a 500.
    """
    from app.services.intelligence.dependency_graph import _MODEL_MAP

    by_type: dict[str, set[int]] = {}
    for row in rows:
        by_type.setdefault(row.asset_type, set()).add(row.asset_id)

    names: dict[tuple[str, int], str] = {}
    for asset_type, ids in by_type.items():
        model = _MODEL_MAP.get(asset_type)
        if model is None:
            continue
        for obj_id, name in db.query(model.id, model.name).filter(model.id.in_(ids)).all():
            names[(asset_type, obj_id)] = name
    return names


@router.get("/resource-efficiency", response_model=list[ResourceEfficiencyOut])
def list_resource_efficiency(
    db: Session = Depends(get_db),
) -> list[ResourceEfficiencyOut]:
    """Return right-sizing recommendations for all assessed assets."""
    rows = (
        db.query(ResourceEfficiencyRecommendation)
        .order_by(ResourceEfficiencyRecommendation.evaluated_at.desc())
        .all()
    )
    names = _resolve_asset_names(db, rows)
    out: list[ResourceEfficiencyOut] = []
    for row in rows:
        item = ResourceEfficiencyOut.model_validate(row)
        item.asset_name = names.get((row.asset_type, row.asset_id))
        out.append(item)
    return out
```

Add `from sqlalchemy.orm import Session, joinedload` (the module currently imports only `Session`).

`_MODEL_MAP` is imported from `dependency_graph` deliberately: it is already the one place that maps the four asset-type strings to models, and a second copy here is exactly the kind of drift that produces a table showing names for three types and integers for the fourth.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/backend/tests/api/test_intel_api.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/api/intel.py apps/backend/tests/api/test_intel_api.py
git commit -m "feat(intel): include asset names in forecast and efficiency responses (INC-10)"
```

---

## Task 2: Intel API module

**Files:**
- Create: `apps/frontend/src/api/intel.js`
- Test: `apps/frontend/src/__tests__/intel-api.test.js`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/intel-api.test.js`:

```javascript
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../api/client.jsx', () => ({
  default: { get: vi.fn(() => Promise.resolve({ data: [] })) },
}));

import client from '../api/client.jsx';
import { getBlastRadius, listCapacityForecasts, listResourceEfficiency } from '../api/intel';

beforeEach(() => vi.clearAllMocks());

describe('intel api module', () => {
  it('reads capacity forecasts', () => {
    listCapacityForecasts();
    expect(client.get).toHaveBeenCalledWith('/intel/capacity-forecasts');
  });

  it('reads resource efficiency', () => {
    listResourceEfficiency();
    expect(client.get).toHaveBeenCalledWith('/intel/resource-efficiency');
  });

  it('builds the blast-radius path from asset type and id', () => {
    getBlastRadius('compute_unit', 42);
    expect(client.get).toHaveBeenCalledWith('/intel/blast-radius/compute_unit/42');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/intel-api.test.js`
Expected: FAIL — cannot resolve `../api/intel`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/api/intel.js`:

```javascript
import client from './client.jsx';

// INC-10. The intel router is mounted with require_auth and no role check
// (main.py:1927), so these are readable by any signed-in user including viewer
// and demo. The UI deliberately matches that rather than gating below it.

export const listCapacityForecasts = () => client.get('/intel/capacity-forecasts');
export const listResourceEfficiency = () => client.get('/intel/resource-efficiency');

// assetType is one of hardware | compute_unit | service | storage — the
// backend's _VALID_TYPES (api/intel.py:19). Anything else is a 400.
export const getBlastRadius = (assetType, assetId) =>
  client.get(`/intel/blast-radius/${assetType}/${assetId}`);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/intel-api.test.js`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/api/intel.js apps/frontend/src/__tests__/intel-api.test.js
git commit -m "feat(intel): add intel API module (INC-10)"
```

---

## Task 3: IntelPage

**Files:**
- Create: `apps/frontend/src/pages/IntelPage.jsx`
- Test: `apps/frontend/src/__tests__/intel-page.test.jsx`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/intel-page.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('../api/intel', () => ({
  listCapacityForecasts: vi.fn(),
  listResourceEfficiency: vi.fn(),
  getBlastRadius: vi.fn(),
}));

import { listCapacityForecasts, listResourceEfficiency } from '../api/intel';
import IntelPage from '../pages/IntelPage.jsx';

const FORECAST = {
  id: 1,
  hardware_id: 12,
  hardware_name: 'nas-01',
  metric: 'disk',
  slope_per_day: 0.9,
  current_value: 87,
  projected_full_at: '2026-09-07T00:00:00Z',
  warning_threshold_days: 30,
  evaluated_at: '2026-08-24T02:30:00Z',
};

const EFFICIENCY = {
  id: 1,
  asset_type: 'compute_unit',
  asset_id: 7,
  asset_name: 'vm-jellyfin',
  classification: 'over_provisioned',
  cpu_avg_pct: 3,
  cpu_peak_pct: 11,
  mem_avg_pct: 18,
  recommendation: 'Reduce from 8 vCPU to 2',
  evaluated_at: '2026-08-24T02:30:00Z',
};

beforeEach(() => {
  vi.clearAllMocks();
  listCapacityForecasts.mockResolvedValue({ data: [] });
  listResourceEfficiency.mockResolvedValue({ data: [] });
});

describe('IntelPage', () => {
  it('renders asset names, never bare ids', async () => {
    listCapacityForecasts.mockResolvedValue({ data: [FORECAST] });
    listResourceEfficiency.mockResolvedValue({ data: [EFFICIENCY] });

    render(<IntelPage />);

    await waitFor(() => expect(screen.getByText('nas-01')).toBeInTheDocument());
    expect(screen.getByText('vm-jellyfin')).toBeInTheDocument();
  });

  it('falls back to a labelled id when the asset no longer exists', async () => {
    listResourceEfficiency.mockResolvedValue({
      data: [{ ...EFFICIENCY, asset_name: null, asset_id: 999 }],
    });

    render(<IntelPage />);

    await waitFor(() => expect(screen.getByText(/compute_unit #999/)).toBeInTheDocument());
  });

  it('marks a forecast projected to saturate inside its warning threshold', async () => {
    listCapacityForecasts.mockResolvedValue({ data: [FORECAST] });

    render(<IntelPage />);

    await waitFor(() =>
      expect(screen.getByTestId('forecast-row-1')).toHaveAttribute('data-warning', 'true')
    );
  });

  it('does not mark a forecast with no projected saturation', async () => {
    listCapacityForecasts.mockResolvedValue({
      data: [{ ...FORECAST, id: 2, projected_full_at: null }],
    });

    render(<IntelPage />);

    await waitFor(() =>
      expect(screen.getByTestId('forecast-row-2')).toHaveAttribute('data-warning', 'false')
    );
  });

  it('names the job and both reasons a list can be empty', async () => {
    render(<IntelPage />);

    await waitFor(() => expect(screen.getAllByText(/analytics job/i).length).toBeGreaterThan(0));
    expect(screen.getAllByText(/02:30/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/has not run yet|enough history/i).length).toBeGreaterThan(0);
  });

  it('renders an error with retry rather than an empty table', async () => {
    listCapacityForecasts.mockRejectedValue(new Error('boom'));

    render(<IntelPage />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/intel-page.test.jsx`
Expected: FAIL — cannot resolve `../pages/IntelPage.jsx`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/pages/IntelPage.jsx`:

```jsx
import React, { useCallback, useEffect, useState } from 'react';
import { listCapacityForecasts, listResourceEfficiency } from '../api/intel';

// Both tables are filled by the analytics job (main.py:1318, CronTrigger at
// 02:30). An empty list has two causes that the data cannot tell apart — the
// job writes nothing when it finds nothing, so there is no timestamp to read.
// Rather than imply a distinction we cannot make, the empty state names both.
const ANALYTICS_SCHEDULE = 'nightly at 02:30';

const EMPTY_FORECASTS = `No capacity forecasts. The analytics job runs ${ANALYTICS_SCHEDULE} and writes a forecast for each host with enough telemetry history — an empty list means either it has not run yet on this install, or no host has enough history to project from.`;

const EMPTY_EFFICIENCY = `No right-sizing recommendations. The analytics job runs ${ANALYTICS_SCHEDULE} and writes a recommendation for each asset it can assess — an empty list means either it has not run yet on this install, or nothing is far enough from its allocation to flag.`;

const pct = (v) => (v == null ? '—' : `${Math.round(v)}%`);

function assetLabel(row) {
  // Never a bare integer: a name when the asset still exists, a labelled id
  // when it does not (asset_id is not a foreign key, so rows outlive assets).
  return row.asset_name || `${row.asset_type} #${row.asset_id}`;
}

function formatDate(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString();
}

function daysUntil(iso) {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  return Number.isNaN(ms) ? null : Math.round(ms / 86400000);
}

function IntelPage() {
  const [forecasts, setForecasts] = useState([]);
  const [efficiency, setEfficiency] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [f, e] = await Promise.all([listCapacityForecasts(), listResourceEfficiency()]);
      setForecasts(f.data || []);
      setEfficiency(e.data || []);
    } catch (err) {
      setError(err?.userMessage || 'Could not load intelligence data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <div className="page">Loading…</div>;

  if (error) {
    return (
      <div className="page">
        <h2>Intelligence</h2>
        <div role="alert">
          <p>{error}</p>
          <button type="button" className="btn btn-sm" onClick={load}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <h2>Intelligence</h2>
      <p style={{ opacity: 0.7, fontSize: 12 }}>
        Computed by the analytics job, {ANALYTICS_SCHEDULE}.
      </p>

      <section>
        <h3>Capacity forecasts</h3>
        {forecasts.length === 0 ? (
          <p style={{ opacity: 0.75, fontSize: 13 }}>{EMPTY_FORECASTS}</p>
        ) : (
          <table className="entity-table">
            <thead>
              <tr>
                <th>Host</th>
                <th>Metric</th>
                <th>Current</th>
                <th>Trend / day</th>
                <th>Projected full</th>
                <th>Threshold</th>
              </tr>
            </thead>
            <tbody>
              {forecasts.map((row) => {
                const days = daysUntil(row.projected_full_at);
                const warning = days != null && days <= row.warning_threshold_days;
                return (
                  <tr
                    key={row.id}
                    data-testid={`forecast-row-${row.id}`}
                    data-warning={String(warning)}
                  >
                    <td>{row.hardware_name || `hardware #${row.hardware_id}`}</td>
                    <td>{row.metric}</td>
                    <td>{pct(row.current_value)}</td>
                    <td>
                      {row.slope_per_day >= 0 ? '+' : ''}
                      {row.slope_per_day.toFixed(2)}%
                    </td>
                    <td>
                      {days == null
                        ? 'no saturation projected'
                        : `${formatDate(row.projected_full_at)} (in ${days} days)`}
                    </td>
                    <td style={{ opacity: 0.7 }}>{row.warning_threshold_days}d</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section style={{ marginTop: 24 }}>
        <h3>Right-sizing</h3>
        {efficiency.length === 0 ? (
          <p style={{ opacity: 0.75, fontSize: 13 }}>{EMPTY_EFFICIENCY}</p>
        ) : (
          <table className="entity-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Class</th>
                <th>CPU avg / peak</th>
                <th>Mem avg</th>
                <th>Recommendation</th>
              </tr>
            </thead>
            <tbody>
              {efficiency.map((row) => (
                <tr key={row.id} data-testid={`efficiency-row-${row.id}`}>
                  <td>{assetLabel(row)}</td>
                  <td>{row.classification.replace(/_/g, ' ')}</td>
                  <td>
                    {pct(row.cpu_avg_pct)} / {pct(row.cpu_peak_pct)}
                  </td>
                  <td>{pct(row.mem_avg_pct)}</td>
                  <td style={{ opacity: 0.85 }}>{row.recommendation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export default IntelPage;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/intel-page.test.jsx`
Expected: PASS — 6 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/pages/IntelPage.jsx apps/frontend/src/__tests__/intel-page.test.jsx
git commit -m "feat(intel): add the Intelligence page (INC-10)"
```

---

## Task 4: BlastRadiusPanel

**Files:**
- Create: `apps/frontend/src/components/details/BlastRadiusPanel.jsx`
- Test: `apps/frontend/src/__tests__/blast-radius-panel.test.jsx`

**Interfaces:**
- Produces: `<BlastRadiusPanel assetType={string} assetId={number} />`

Prop names mirror `VulnerabilityPanel`'s `entityType`/`entityId` shape but use `asset*`, matching the endpoint's own vocabulary (`asset_type`, `asset_id`, `_VALID_TYPES`). The **values** are identical to the ones the detail views already pass to `VulnerabilityPanel` — `hardware`, `compute_unit`, `service`, `storage`.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/blast-radius-panel.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/intel', () => ({ getBlastRadius: vi.fn() }));

import { getBlastRadius } from '../api/intel';
import BlastRadiusPanel from '../components/details/BlastRadiusPanel.jsx';

const IMPACT = {
  root_asset: { asset_type: 'hardware', asset_id: 3, name: 'pve-01', status: 'online' },
  impacted_hardware: [],
  impacted_compute_units: [
    { asset_type: 'compute_unit', asset_id: 7, name: 'vm-postgres', status: 'running' },
    { asset_type: 'compute_unit', asset_id: 8, name: 'vm-jellyfin', status: 'running' },
  ],
  impacted_services: [
    { asset_type: 'service', asset_id: 11, name: 'nextcloud', status: 'up' },
  ],
  impacted_storage: [],
  total_impact_count: 3,
  summary: 'If pve-01 goes offline, 3 downstream assets lose availability.',
};

const NO_IMPACT = {
  root_asset: { asset_type: 'hardware', asset_id: 5, name: 'nuc-05', status: 'online' },
  impacted_hardware: [],
  impacted_compute_units: [],
  impacted_services: [],
  impacted_storage: [],
  total_impact_count: 0,
  summary: 'Nothing depends on nuc-05.',
};

const renderPanel = (props = {}) =>
  render(
    <MemoryRouter>
      <BlastRadiusPanel assetType="hardware" assetId={3} {...props} />
    </MemoryRouter>
  );

beforeEach(() => vi.clearAllMocks());

describe('BlastRadiusPanel', () => {
  it('does not fetch until expanded — it walks the dependency graph', () => {
    renderPanel();
    expect(getBlastRadius).not.toHaveBeenCalled();
  });

  it('fetches once on expand, with the asset type and id', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /impact/i }));

    await waitFor(() => expect(getBlastRadius).toHaveBeenCalledWith('hardware', 3));
  });

  it('does not refetch when collapsed and expanded again', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });

    renderPanel();
    const toggle = screen.getByRole('button', { name: /impact/i });
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByText('vm-postgres')).toBeInTheDocument());

    fireEvent.click(toggle);
    fireEvent.click(toggle);

    expect(getBlastRadius).toHaveBeenCalledTimes(1);
  });

  it('groups impacted assets by type and links each one', async () => {
    getBlastRadius.mockResolvedValue({ data: IMPACT });

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /impact/i }));

    await waitFor(() => expect(screen.getByText('vm-postgres')).toBeInTheDocument());
    expect(screen.getByText('nextcloud')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'vm-postgres' })).toHaveAttribute(
      'href',
      '/compute-units?id=7'
    );
    expect(screen.getByRole('link', { name: 'nextcloud' })).toHaveAttribute(
      'href',
      '/services?id=11'
    );
  });

  it('renders zero impact as an answer, not an empty state', async () => {
    getBlastRadius.mockResolvedValue({ data: NO_IMPACT });

    renderPanel({ assetId: 5 });
    fireEvent.click(screen.getByRole('button', { name: /impact/i }));

    await waitFor(() => expect(screen.getByText(/nothing depends on this/i)).toBeInTheDocument());
    expect(screen.queryByText(/no data/i)).not.toBeInTheDocument();
  });

  it('renders an error with retry rather than an empty impact list', async () => {
    getBlastRadius.mockRejectedValue(new Error('boom'));

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /impact/i }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/blast-radius-panel.test.jsx`
Expected: FAIL — cannot resolve `../components/details/BlastRadiusPanel.jsx`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/frontend/src/components/details/BlastRadiusPanel.jsx`:

```jsx
import React, { useCallback, useState } from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import { getBlastRadius } from '../../api/intel';

// Where each impacted asset type lives, for the drill-through links.
const ROUTE_FOR_TYPE = {
  hardware: '/hardware',
  compute_unit: '/compute-units',
  service: '/services',
  storage: '/storage',
};

const GROUPS = [
  { key: 'impacted_hardware', label: 'Hardware' },
  { key: 'impacted_compute_units', label: 'Compute units' },
  { key: 'impacted_services', label: 'Services' },
  { key: 'impacted_storage', label: 'Storage' },
];

/**
 * Downstream impact of one asset going offline (INC-10).
 *
 * Mounted into the four detail views whose types the endpoint accepts, in the
 * same position as VulnerabilityPanel. Collapsed by default and fetched on
 * expand: calculate_blast_radius walks the dependency graph, and every drawer
 * opening should not pay for that.
 */
function BlastRadiusPanel({ assetType, assetId }) {
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchImpact = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getBlastRadius(assetType, assetId);
      setResult(res.data);
    } catch (err) {
      setError(err?.userMessage || 'Could not calculate impact.');
    } finally {
      setLoading(false);
    }
  }, [assetType, assetId]);

  const toggle = useCallback(() => {
    setOpen((wasOpen) => {
      // Fetch once, on first expand. The graph does not change while a drawer
      // is open, so collapsing and reopening must not pay for it again.
      if (!wasOpen && result == null && !loading) fetchImpact();
      return !wasOpen;
    });
  }, [result, loading, fetchImpact]);

  const count = result?.total_impact_count ?? null;

  return (
    <div className="blast-radius-panel">
      <button
        type="button"
        className="blast-radius-panel__toggle"
        aria-expanded={open}
        onClick={toggle}
      >
        Impact
        {count != null && (
          <span className="blast-radius-panel__count">
            {count === 0 ? 'nothing depends on this' : `${count} assets affected`}
          </span>
        )}
      </button>

      {open && (
        <div className="blast-radius-panel__body">
          {loading && <p>Calculating…</p>}

          {error && (
            <div role="alert">
              <p>{error}</p>
              <button type="button" className="btn btn-sm" onClick={fetchImpact}>
                Retry
              </button>
            </div>
          )}

          {!loading && !error && result && result.total_impact_count === 0 && (
            // Zero impact is the answer, not the absence of one — it is the
            // most useful thing this can say before maintenance.
            <p>
              <strong>Nothing depends on this.</strong> Taking{' '}
              {result.root_asset?.name || 'this asset'} offline affects nothing else that Circuit
              Breaker knows about.
            </p>
          )}

          {!loading && !error && result && result.total_impact_count > 0 && (
            <>
              <p>{result.summary}</p>
              {GROUPS.map(({ key, label }) => {
                const items = result[key] || [];
                if (items.length === 0) return null;
                return (
                  <div key={key} className="blast-radius-panel__group">
                    <span className="blast-radius-panel__group-label">
                      {label} ({items.length})
                    </span>
                    <ul>
                      {items.map((item) => (
                        <li key={`${item.asset_type}-${item.asset_id}`}>
                          <Link to={`${ROUTE_FOR_TYPE[item.asset_type]}?id=${item.asset_id}`}>
                            {item.name}
                          </Link>
                          {item.status && (
                            <span className="blast-radius-panel__status"> {item.status}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </>
          )}
        </div>
      )}
    </div>
  );
}

BlastRadiusPanel.propTypes = {
  // One of the backend's _VALID_TYPES: hardware | compute_unit | service | storage.
  assetType: PropTypes.string.isRequired,
  assetId: PropTypes.number.isRequired,
};

export default BlastRadiusPanel;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/frontend test -- src/__tests__/blast-radius-panel.test.jsx`
Expected: PASS — 6 tests.

If the link assertions fail, check the query-parameter convention the detail drawers actually use for deep links (search `?id=` in `HardwarePage.jsx` / `ServicesPage.jsx`) and align `ROUTE_FOR_TYPE`'s links and the test to whatever exists. Do not invent a second deep-link convention.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/details/BlastRadiusPanel.jsx apps/frontend/src/__tests__/blast-radius-panel.test.jsx
git commit -m "feat(intel): add blast-radius panel for detail views (INC-10)"
```

---

## Task 5: Mount the panel and register the page

**Files:**
- Modify: `apps/frontend/src/components/details/{HardwareDetail,ComputeDetail,ServiceDetail,StorageDetail}.jsx`
- Modify: `apps/frontend/src/App.jsx`, `apps/frontend/src/data/navigation.js`
- Modify: `apps/frontend/src/index.css`
- Test: `apps/frontend/src/__tests__/intel-nav.test.js`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/intel-nav.test.js`:

```javascript
import { describe, expect, it } from 'vitest';
import { NAV_ITEMS, NAV_MAP, DEFAULT_ORDER } from '../data/navigation';

const allItems = NAV_ITEMS.flatMap((g) => g.items);

describe('intelligence navigation', () => {
  it('is registered as a nav item', () => {
    expect(allItems.some((i) => i.path === '/intel')).toBe(true);
  });

  it('is not role-gated — the routes are readable by any authenticated user', () => {
    const item = allItems.find((i) => i.path === '/intel');
    expect(item.requireAdmin).toBeUndefined();
    expect(item.requireEditor).toBeUndefined();
  });

  it('is in the dock, unlike the audit sub-view', () => {
    expect(NAV_MAP).toHaveProperty('/intel');
    expect(DEFAULT_ORDER).toContain('/intel');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix apps/frontend test -- src/__tests__/intel-nav.test.js`
Expected: FAIL — no `/intel` item.

- [ ] **Step 3: Register the route and navigation**

In `apps/frontend/src/App.jsx`, add the lazy import beside the others:

```javascript
const IntelPage = React.lazy(() => import('./pages/IntelPage'));
```

and the route beside the other unguarded routes (no `RequireAdmin` / `RequireEditor` — spec D8):

```jsx
                  <Route path="/intel" element={<IntelPage />} />
```

In `apps/frontend/src/data/navigation.js`, add `TrendingUp` to the `lucide-react` import, then:

- In `NAV_ITEMS`, in the **Infrastructure** group after `/ipam`:

```javascript
      { path: '/intel', icon: TrendingUp, label: 'Intel', labelKey: 'header.intel' },
```

- In `NAV_MAP`:

```javascript
  '/intel': { icon: TrendingUp, label: 'Intel', labelKey: 'header.intel' },
```

- In `DEFAULT_ORDER`, after `'/ipam'`:

```javascript
  '/intel',
```

- [ ] **Step 4: Mount the panel in the four detail views**

Three of these already mount `VulnerabilityPanel`; put `BlastRadiusPanel` directly above it so the two analysis panels sit together.

`HardwareDetail.jsx` — import beside the other detail imports, then at line ~771:

```jsx
          <BlastRadiusPanel assetType="hardware" assetId={hardware.id} />
          <VulnerabilityPanel entityType="hardware" entityId={hardware.id} />
```

`ComputeDetail.jsx` — at line ~472:

```jsx
          <BlastRadiusPanel assetType="compute_unit" assetId={compute.id} />
          <VulnerabilityPanel entityType="compute_unit" entityId={compute.id} />
```

`ServiceDetail.jsx` — at line ~390:

```jsx
          <BlastRadiusPanel assetType="service" assetId={service.id} />
          <VulnerabilityPanel entityType="service" entityId={service.id} />
```

`StorageDetail.jsx` has **no** `VulnerabilityPanel`. It is a tabbed drawer (`activeTab` at line 23). Mount inside the `{activeTab === 'overview' && (` block that begins at line 63, immediately before that block's closing `</div>\n        )}` at line ~193 — so it appears on the overview tab only, never on the docs tab:

```jsx
            <BlastRadiusPanel assetType="storage" assetId={storage.id} />
```

Add `import BlastRadiusPanel from './BlastRadiusPanel';` to each of the four files.

- [ ] **Step 5: Add the panel's styles**

Append to `apps/frontend/src/index.css`:

```css
/* INC-10: blast radius, alongside VulnerabilityPanel in the detail drawers. */
.blast-radius-panel {
  border-top: 1px solid var(--color-border);
  padding-top: 10px;
  margin-top: 10px;
}

.blast-radius-panel__toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  background: none;
  border: none;
  color: inherit;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
  padding: 0;
}

.blast-radius-panel__count {
  font-weight: 400;
  opacity: 0.75;
  font-size: 12px;
}

.blast-radius-panel__body {
  margin-top: 8px;
  font-size: 12px;
}

.blast-radius-panel__group {
  margin-top: 8px;
}

.blast-radius-panel__group-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  opacity: 0.7;
}

.blast-radius-panel__status {
  opacity: 0.6;
}
```

- [ ] **Step 6: Run tests and lint**

Run: `npm --prefix apps/frontend test`
Run: `npm --prefix apps/frontend run lint`
Expected: PASS — including every pre-existing detail-view test.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/App.jsx apps/frontend/src/data/navigation.js \
        apps/frontend/src/components/details/ apps/frontend/src/index.css \
        apps/frontend/src/__tests__/intel-nav.test.js
git commit -m "feat(intel): register /intel and mount blast radius on detail views (INC-10)"
```

---

## Task 6: Docs and register

- [ ] **Step 1: Rewrite the BI docs**

`docs/business_intelligence.md:5-6` currently states *"In 1.0 these are API-only capabilities … no screen in the app calls them"*. That ceases to be true. Replace that passage with:

```markdown
## Where these appear

| Capability | Surface |
|---|---|
| Capacity forecasts | **Intel** page (`/intel`) |
| Resource efficiency | **Intel** page (`/intel`) |
| Blast radius | **Impact** panel on a hardware, compute unit, service, or storage detail view |

All three are readable by any signed-in user; they carry no role restriction.

## When the data appears

Capacity forecasts and right-sizing recommendations are written by the
`analytics_job` scheduled job, which runs nightly at 02:30. Both tables are
empty until it has run at least once, and stay empty for anything it has no
recommendation about — a host without enough telemetry history has no forecast,
and an asset sitting comfortably within its allocation has no recommendation.
The page states both possibilities, because the stored data cannot distinguish
them: the job writes nothing when it finds nothing.

Blast radius is computed on demand when you expand the **Impact** panel, not on
a schedule, because it reflects the dependency graph as it stands right now.
"Nothing depends on this" is a real answer and is displayed as one.
```

- [ ] **Step 2: Add the nav entry**

`docs/business_intelligence.md` is presumably already in `mkdocs.yml`. Confirm and skip if so:

```bash
grep -n "business_intelligence.md" mkdocs.yml || echo "NOT IN NAV — add it"
```

If absent, add it with **six spaces** of indentation next to the other operational pages, then:

```bash
python3 -c "import yaml; yaml.safe_load(open('mkdocs.yml')); print('mkdocs.yml parses')"
```

- [ ] **Step 3: Update the register**

Set INC-10's summary row to `Resolved`, update `**Last updated:**`, and replace the INC-10 body with:

```markdown
### INC-10. Business Intelligence has no UI

**Resolved.** `GET /intel/blast-radius/{type}/{id}`, `GET /intel/capacity-forecasts`
and `GET /intel/resource-efficiency` were implemented and backed by scheduled
jobs, with no frontend caller — a whole computed subsystem with a scheduler cost
and no user surface. Product chose to ship the screen rather than gate the jobs
off.

- `pages/IntelPage.jsx` at `/intel` — the two precomputed tables. No role gate,
  matching the router's own mount (`main.py:1927` uses `require_auth` with no
  role check); gating the nav below the API would have been cosmetic.
- `components/details/BlastRadiusPanel.jsx` — mounted in `HardwareDetail`,
  `ComputeDetail`, `ServiceDetail` and `StorageDetail`, exactly `intel.py`'s
  `_VALID_TYPES`, following `VulnerabilityPanel`'s existing pattern. It fetches
  on expand rather than on drawer mount, since `calculate_blast_radius` walks
  the dependency graph, and it fetches once — the graph does not change while a
  drawer is open. Zero impact renders as an answer, not an empty state.
- `api/intel.py` — both list responses now carry the asset's name.
  `CapacityForecastOut` joins through the existing `hardware` relationship;
  `ResourceEfficiencyOut` resolves names in one query per asset *type* present,
  never one per row, pinned by
  `test_efficiency_names_do_not_scale_queries_with_row_count`. It reuses
  `dependency_graph._MODEL_MAP` rather than keeping a second copy of the
  type→model mapping — two copies is how a table ends up showing names for
  three types and integers for the fourth. `asset_id` is not a foreign key, so
  a recommendation outliving its asset yields a null name rather than a 500.

**One spec item delivered differently:** §8.2 called for making "the analytics
job has not run" distinguishable from "nothing to report" as a backend change.
It cannot be, without new state — the job writes rows only when it finds
something, so `max(evaluated_at)` is NULL in both cases. Rather than imply a
distinction the data cannot support, the empty state names the job, its
schedule, and both reasons the list can be empty. Making it precise would
require job-run tracking, which is scheduler observability rather than BI and is
not built here.

No migration: the three tables from migration 0058 already existed.
```

- [ ] **Step 4: Run both suites**

Run: `npm --prefix apps/frontend test`
Run: `pytest apps/backend/tests/api/test_intel_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/business_intelligence.md mkdocs.yml docs/1.0.0-incomplete-features.md
git commit -m "docs(intel): document the Intelligence surfaces and close INC-10"
```

---

## Self-Review

**Spec coverage (§8).** `/intel` page with both ranked tables ✓ Task 3. Warning marking inside `warning_threshold_days` ✓ Task 3. Names in responses (B8) ✓ Task 1. Empty state naming the job and schedule (B9, delivered as copy) ✓ Task 3 + the register note. `BlastRadiusPanel` in the four detail views ✓ Tasks 4–5. Fetch on expand ✓ Task 4. Grouped lists linking to detail routes ✓ Task 4. Zero impact as an answer ✓ Task 4. All-authenticated visibility, D8 ✓ Tasks 1, 5 and asserted in both suites. Error never renders as empty (§9) ✓ Tasks 3–4.

**Placeholder scan.** None. The two conditional steps — whether `business_intelligence.md` is already in the nav, and the deep-link query convention — give the exact command to run and the exact rule to follow.

**Type consistency.** `assetType` values (`hardware`, `compute_unit`, `service`, `storage`) are identical in `intel.py`'s `_VALID_TYPES`, `dependency_graph._MODEL_MAP`, `ROUTE_FOR_TYPE`, `GROUPS`' response keys, and every mount site in Task 5. Response field names (`total_impact_count`, `summary`, `root_asset`, `impacted_*`) match `BlastRadiusOut` exactly. `hardware_name` and `asset_name` are spelled the same in Task 1's schema, Task 1's tests, and Task 3's rendering. `getBlastRadius(assetType, assetId)` has one signature across Tasks 2 and 4.
