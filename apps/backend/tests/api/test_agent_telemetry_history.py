"""`GET /api/v1/agents/{id}/telemetry/history` — SQL aggregation contract.

Task 7 of `plans/2026-08-06-cbi-agent-slice12-cohesion-hardening-tasks.md`
replaced a full ORM materialization + Python bucketing + endpoint-preserving
decimation with a single grouped aggregate. These tests pin the four properties
that rewrite has to hold: the aggregate runs in SQL (never in Python, never
touching the `raw` JSONB), the bucket grid is the *epoch* grid, every range is
hard-bounded by a `LIMIT`, and the SQL is portable (no TimescaleDB-only
`time_bucket`, no `date_bin`).

The bucket/cap tables below are transcribed from decision D-2 rather than
imported from `app.api.agents`, so a change to the module constants shows up
here as a failure instead of silently redefining the contract.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, insert

from app.core.time import utcnow
from app.db.models import AgentHostSample

# D-2: bucket width per range, and the resulting hard point cap
# (cap == range duration / bucket width, enforced by SQL LIMIT).
_BUCKET_SECONDS = {"1h": 30, "6h": 60, "24h": 300, "7d": 1800, "30d": 3600}
_MAX_POINTS = {"1h": 120, "6h": 360, "24h": 288, "7d": 336, "30d": 720}
_RANGE_DURATION_S = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000}
_RANGES = ["1h", "6h", "24h", "7d", "30d"]

_SUMMARY_KEYS = {
    "cpu_pct",
    "mem_pct",
    "root_disk_pct",
    "net_rx_bps",
    "net_tx_bps",
    "max_temp_c",
    "load_1",
    "uptime_s",
}


def _grid(moment: datetime, width_seconds: int) -> datetime:
    """The newest epoch-grid point of `width_seconds` at or before `moment`."""
    return datetime.fromtimestamp(int(moment.timestamp()) // width_seconds * width_seconds, tz=UTC)


def _seed_samples(db_session, agent, specs) -> None:
    """Bulk-insert `(collected_at, {column: value})` pairs.

    One Core `insert()` with an executemany parameter list: the row counts here
    (720, 5,000) make per-row ORM flushes the dominant cost and would push the
    test past `pyproject.toml`'s 30 s timeout.
    """
    rows = []
    for index, (collected_at, values) in enumerate(specs):
        row: dict = {
            "agent_id": agent.id,
            "hardware_id": None,
            "sample_id": f"{index:032x}",
            "collected_at": collected_at,
            "status": "healthy",
            "raw": {"schema": 1, "summary": {}},
            "projected_at": None,
        }
        row.update({key: None for key in _SUMMARY_KEYS})
        row.update(values)
        rows.append(row)
    db_session.execute(insert(AgentHostSample), rows)
    db_session.flush()


@contextlib.contextmanager
def _capture_sql():
    """Record every statement the engine executes while the block is open."""
    from app.db.session import engine

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "after_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "after_cursor_execute", _record)


@pytest.mark.asyncio
async def test_1h_range_averages_into_30s_buckets(client, db_session, factories, viewer_headers):
    """5 s cadence must be *averaged* into 30 s buckets, not decimated.

    720 samples carrying a 0..719 ramp fill exactly 120 aligned 30 s buckets.
    The old code bucketed at 1 s (a no-op at any real cadence) and then kept
    `points[round(i * last / 119)]`, dropping 600 of the 720 samples.
    """
    agent = factories.agent(status="active")
    # Anchor one bucket into the future so the oldest sample keeps >30 s of
    # slack over the `utcnow() - 1h` window the request computes later.
    newest_bucket = _grid(utcnow(), 30) + timedelta(seconds=30)
    specs = []
    index = 0
    for bucket in range(120):
        bucket_start = newest_bucket - timedelta(seconds=30 * (119 - bucket))
        for offset in range(0, 30, 5):
            specs.append((bucket_start + timedelta(seconds=offset), {"cpu_pct": float(index)}))
            index += 1
    _seed_samples(db_session, agent, specs)

    resp = await client.get(
        f"/api/v1/agents/{agent.id}/telemetry/history?range=1h", headers=viewer_headers
    )

    assert resp.status_code == 200
    points = resp.json()["points"]
    assert len(points) <= _MAX_POINTS["1h"]
    assert len(points) == 120
    assert [p["sample_count"] for p in points] == [6] * 120
    # Bucket 0 averaged the ramp values 0..5.
    assert points[0]["summary"]["cpu_pct"] == pytest.approx(2.5)
    assert points[-1]["summary"]["cpu_pct"] == pytest.approx(716.5)
    stamps = [datetime.fromisoformat(p["collected_at"]) for p in points]
    assert all((b - a) == timedelta(seconds=30) for a, b in zip(stamps, stamps[1:], strict=False))


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_history_aggregates_in_sql_not_python(client, db_session, factories, viewer_headers):
    """The averaging is a GROUP BY, and `raw` is never selected.

    `raw` is the largest column in the table; the old endpoint hydrated a full
    ORM row per sample, so a busy range pulled tens of thousands of host
    payloads into the process to compute eight means.
    """
    agent = factories.agent(status="active")
    base = utcnow() - timedelta(minutes=58)
    _seed_samples(
        db_session,
        agent,
        (
            (base + timedelta(milliseconds=700 * i), {"cpu_pct": float(i % 100)})
            for i in range(5000)
        ),
    )

    with _capture_sql() as statements:
        resp = await client.get(
            f"/api/v1/agents/{agent.id}/telemetry/history?range=1h",
            headers=viewer_headers,
        )

    assert resp.status_code == 200
    lowered = [s.lower() for s in statements]
    assert any("avg(" in s and "group by" in s for s in lowered), lowered
    assert not any("agent_host_samples.raw" in s for s in lowered), lowered
    assert len(resp.json()["points"]) <= _MAX_POINTS["1h"]


@pytest.mark.asyncio
@pytest.mark.parametrize("range_name", _RANGES)
async def test_history_point_count_bounded_for_every_range(
    client, db_session, factories, viewer_headers, range_name
):
    """Every range is capped, and every bucket sits on the epoch grid.

    Grid alignment (not alignment to the first sample) is what makes two
    consecutive requests comparable and what the delta assertion below proves:
    decimation produced uneven spacing.
    """
    agent = factories.agent(status="active")
    width = _BUCKET_SECONDS[range_name]
    duration = _RANGE_DURATION_S[range_name]
    spacing = duration / 300
    newest = _grid(utcnow(), width)
    _seed_samples(
        db_session,
        agent,
        ((newest - timedelta(seconds=spacing * i), {"cpu_pct": float(i)}) for i in range(299)),
    )

    resp = await client.get(
        f"/api/v1/agents/{agent.id}/telemetry/history?range={range_name}",
        headers=viewer_headers,
    )

    assert resp.status_code == 200
    points = resp.json()["points"]
    assert 2 <= len(points) <= _MAX_POINTS[range_name]
    stamps = [datetime.fromisoformat(p["collected_at"]) for p in points]
    assert all(stamp.tzinfo is not None for stamp in stamps)
    assert all(int(stamp.timestamp()) % width == 0 for stamp in stamps)
    deltas = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:], strict=False)]
    assert all(d > 0 and d % width == 0 for d in deltas), deltas


@pytest.mark.asyncio
async def test_7d_range_merges_hourly_rows_when_raw_purged(client, factories, viewer_headers):
    """`7d` straddles the raw/hourly retention boundary.

    `retention.py` deletes raw rows older than `telemetry_hot_days` (default 7,
    configurable lower), so a `7d` request that only ever reads
    `agent_host_samples` silently returns a truncated series. Only the `30d`
    branch consulted the hourly rollup before Task 7.
    """
    agent = factories.agent(status="active")
    now = utcnow()
    # Anchor the raw block on the HOUR grid, offset by half a bucket, so
    # `raw_boundary` lands strictly after the newest hourly bucket
    # (`grid(now, 3600) - 2 days`). Anchoring it on the 30-minute grid instead
    # makes the two coincide whenever `now` falls in the first half of an hour,
    # and the endpoint's `bucket_at < raw_boundary` then drops one hourly point.
    raw_start = _grid(now, 3600) - timedelta(days=2) + timedelta(minutes=30)
    for index in range(96):
        factories.agent_host_sample(
            agent,
            sample_id=f"{index:032x}",
            collected_at=raw_start + timedelta(minutes=30 * index),
            cpu_pct=50.0,
        )
    # Days 7..2 back, hour-aligned, with a pre-Task-6 summary that has no
    # `uptime_s` key at all.
    hourly_start = _grid(now, 3600) - timedelta(days=7) + timedelta(hours=1)
    for index in range(120):
        factories.agent_host_sample_hourly(
            agent,
            bucket_at=hourly_start + timedelta(hours=index),
            sample_count=60,
            summary={"cpu_pct": 11.0, "mem_pct": 22.0},
        )

    resp = await client.get(
        f"/api/v1/agents/{agent.id}/telemetry/history?range=7d", headers=viewer_headers
    )

    assert resp.status_code == 200
    points = resp.json()["points"]
    assert len(points) <= _MAX_POINTS["7d"]
    stamps = [datetime.fromisoformat(p["collected_at"]) for p in points]
    assert stamps[-1] - stamps[0] >= timedelta(days=6, hours=12)
    assert all(set(p["summary"]) == _SUMMARY_KEYS for p in points)
    hourly_points = [p for p in points if p["sample_count"] == 60]
    assert len(hourly_points) == 120
    assert hourly_points[0]["summary"]["cpu_pct"] == pytest.approx(11.0)
    assert hourly_points[0]["summary"]["uptime_s"] is None


@pytest.mark.asyncio
async def test_history_response_shape_unchanged(client, factories, viewer_headers):
    """`AgentDetailPage.jsx` reads `data.points[].summary[metric]`."""
    agent = factories.agent(status="active")
    now = utcnow()
    for index in range(4):
        factories.agent_host_sample(
            agent,
            sample_id=f"{index:032x}",
            collected_at=now - timedelta(minutes=5 * index),
            cpu_pct=1.0,
            uptime_s=90,
        )

    resp = await client.get(
        f"/api/v1/agents/{agent.id}/telemetry/history?range=1h", headers=viewer_headers
    )

    assert resp.status_code == 200
    points = resp.json()["points"]
    assert points
    for point in points:
        assert set(point) == {"collected_at", "summary", "sample_count"}
        assert set(point["summary"]) == _SUMMARY_KEYS
        assert datetime.fromisoformat(point["collected_at"]).tzinfo is not None
        assert point["summary"]["uptime_s"] == pytest.approx(90.0)
        assert point["summary"]["max_temp_c"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("range_name", _RANGES)
async def test_history_sql_uses_no_timescale_functions(
    client, factories, viewer_headers, range_name
):
    """`docker-compose.deps.yml` runs `postgres:16-alpine` without TimescaleDB."""
    agent = factories.agent(status="active")
    factories.agent_host_sample(agent, collected_at=utcnow() - timedelta(minutes=1))

    with _capture_sql() as statements:
        resp = await client.get(
            f"/api/v1/agents/{agent.id}/telemetry/history?range={range_name}",
            headers=viewer_headers,
        )

    assert resp.status_code == 200
    lowered = [s.lower() for s in statements]
    assert not any("time_bucket" in s for s in lowered), lowered
    assert not any("date_bin" in s for s in lowered), lowered


@pytest.mark.asyncio
@pytest.mark.parametrize("range_name", _RANGES)
async def test_history_returns_empty_points_for_agent_with_no_samples(
    client, factories, viewer_headers, range_name
):
    """Covers the scalar `min(collected_at) -> NULL` boundary path."""
    agent = factories.agent(status="active")

    resp = await client.get(
        f"/api/v1/agents/{agent.id}/telemetry/history?range={range_name}",
        headers=viewer_headers,
    )

    assert resp.status_code == 200
    assert resp.json() == {"range": range_name, "points": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("range_name", _RANGES)
async def test_limit_truncates_the_boundary_bucket_for_every_range(
    client, db_session, factories, viewer_headers, range_name
):
    """The SQL `LIMIT` is load-bearing on every range, not just `1h`.

    D-2 sets cap == duration / width, so a naively seeded window holds exactly
    `cap` buckets and the LIMIT never fires — which is why the other bound test
    only pins `1h`. `cap + 1` buckets *do* fit, but only when the oldest sample
    sits near the END of its bucket: the span from there to a sample at the
    start of the newest bucket is `cap * width - (width - 1)`, just inside the
    `collected_at >= now - duration` window. That is the real boundary case,
    and it is what a partially-elapsed leading bucket looks like in production.

    Asserting `== cap` (not `<= cap`) also catches a cap raised upward, which a
    `<=` assertion cannot.

    On `7d`/`30d` the post-merge truncation is a second guard that holds the
    bound even without the SQL `LIMIT`; `1h`/`6h`/`24h` pin the `LIMIT` itself.
    """
    agent = factories.agent(status="active")
    width = _BUCKET_SECONDS[range_name]
    cap = _MAX_POINTS[range_name]
    anchor = _grid(utcnow(), width)
    specs = [(anchor - timedelta(seconds=width * i), {"cpu_pct": float(i)}) for i in range(cap)]
    # One more sample, one bucket further back, placed at the very end of that
    # bucket so it still clears `start`.
    oldest_bucket = anchor - timedelta(seconds=width * cap)
    specs.append((oldest_bucket + timedelta(seconds=width - 1), {"cpu_pct": -1.0}))
    _seed_samples(db_session, agent, specs)

    resp = await client.get(
        f"/api/v1/agents/{agent.id}/telemetry/history?range={range_name}",
        headers=viewer_headers,
    )

    assert resp.status_code == 200
    points = resp.json()["points"]
    assert len(points) == cap
    stamps = [datetime.fromisoformat(p["collected_at"]) for p in points]
    assert stamps == sorted(stamps)
    # The LIMIT must drop the OLDEST bucket, not the newest — the chart's right
    # edge is the live end.
    assert stamps[-1] == anchor
    assert oldest_bucket not in stamps
