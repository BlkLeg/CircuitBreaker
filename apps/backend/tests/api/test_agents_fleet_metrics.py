"""Fleet-read contract for `GET /agents/presence` and `GET /agents/metrics/series`.

The agents-page redesign (`docs/design/2026-08-14-agents-page-redesign-design.md`)
puts live head values on the bulk presence row and moves the sparkline series
to a second, slower endpoint. Both additions are cheap *today*; nothing in the
code stops a later change from making either one cost a query per agent, and
nothing would look wrong — the page would simply get slower as the fleet grows.
These tests pin the properties that make the design hold:

* the presence read costs a **fixed** number of statements no matter how many
  agents are in the fleet (design §5 — the headline test), and never
  materializes the `raw` JSONB payload,
* `latest` is genuinely the newest sample per agent, is `null` (never zeros)
  when an agent has no samples, and does not leak across agents,
* the spool backlog rides the same row, with `None` ("never reported") kept
  distinct from `0` ("reported, drained"),
* the series is bucketed and **capped by a SQL LIMIT**, so its payload cannot
  grow with the agent's sample cadence,
* both routes are behind `require_role("viewer")`.

The window/bucket/cap numbers below are transcribed from the contract rather
than imported from `app.api.agents`, for the same reason
`test_agent_telemetry_history.py` transcribes its own: a change to the module
constants must fail here instead of silently redefining the contract.
"""

from __future__ import annotations

import contextlib
import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, insert

from app.core.time import utcnow
from app.db.models import AgentHostSample

# Contract §A.3: a 30-minute window on a 75 s epoch grid, hence 24 buckets.
_SERIES_WINDOW = timedelta(minutes=30)
_SERIES_BUCKET_SECONDS = 75
_SERIES_MAX_POINTS = 24
_SERIES_FIELDS = ("cpu_pct", "mem_pct", "net_rx_bps", "net_tx_bps")

# Contract §A.1: the eight summary columns `AgentLatestSample` carries. It
# also carries `collected_at` — the stamp the client uses to judge staleness
# for itself — but that is not a seedable metric column, so it is added
# explicitly wherever the response shape is asserted.
_LATEST_FIELDS = (
    "cpu_pct",
    "mem_pct",
    "root_disk_pct",
    "net_rx_bps",
    "net_tx_bps",
    "max_temp_c",
    "load_1",
    "uptime_s",
)

# The two fleet sizes the query-count test compares. The absolute statement
# count is deliberately never asserted — only that it is the *same* at both
# sizes — so an unrelated future query cannot break this test while an N+1 can.
_SMALL_FLEET = 2
_LARGE_FLEET = 8

# Tables the fleet presence read touches. Auth's `users` lookup and the
# savepoint bookkeeping the `db_session` fixture emits are excluded on purpose:
# neither varies with fleet size, and including them would only add noise.
_FLEET_TABLES = ("agents", "agent_capability_grants", "agent_host_samples", "hardware")

# One raw sample every 5 s fills a 75 s bucket 15 times over — far denser than
# the cap, which is exactly the cadence-independence the LIMIT has to survive.
_DENSE_CADENCE_SECONDS = 5
_SAMPLES_PER_BUCKET = _SERIES_BUCKET_SECONDS // _DENSE_CADENCE_SECONDS


def _grid(moment: datetime, width_seconds: int) -> datetime:
    """The newest epoch-grid point of `width_seconds` at or before `moment`."""
    return datetime.fromtimestamp(int(moment.timestamp()) // width_seconds * width_seconds, tz=UTC)


def _seed_samples(db_session, agent, specs) -> None:
    """Bulk-insert `(collected_at, {column: value})` pairs for one agent.

    One Core `insert()` with an executemany parameter list, copied from
    `test_agent_telemetry_history.py`: the series tests seed hundreds of rows
    per agent and per-row ORM flushes are the dominant cost there — enough to
    push the module past `pyproject.toml`'s 30 s timeout.

    `sample_id` is a fresh random hex string rather than the row index so two
    `_seed_samples` calls against the same agent cannot collide on
    `uq_agent_host_sample` (agent_id, sample_id, collected_at).
    """
    rows = []
    for collected_at, values in specs:
        row: dict = {
            "agent_id": agent.id,
            "hardware_id": None,
            "sample_id": secrets.token_hex(16),
            "collected_at": collected_at,
            "status": "healthy",
            "raw": {"schema": 1, "summary": {}},
            "projected_at": None,
        }
        row.update({field: None for field in _LATEST_FIELDS})
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


def _fleet_reads(statements: list[str]) -> list[str]:
    """The SELECTs that make up the fleet presence read, in execution order."""
    return [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
        and any(table in statement for table in _FLEET_TABLES)
    ]


def _row_for(body: list[dict], agent) -> dict:
    """The presence row for `agent` — the endpoint's row order is the DB's."""
    return next(row for row in body if row["agent_id"] == agent.id)


def _offline_redis(monkeypatch) -> None:
    """Every agent reads offline without a live Redis.

    Presence state is irrelevant to all of these tests — they are about the
    SQL side of the row — and a `None` client is `bulk_presence`'s documented
    degrade path, so this keeps the suite off a real Redis entirely.
    """
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))


# ── `GET /agents/presence` — `latest` and the spool passthrough ──────────────


@pytest.mark.asyncio
async def test_presence_query_count_does_not_scale_with_fleet_size(
    client, db_session, factories, viewer_headers, monkeypatch
):
    """The whole justification for folding `latest` into the bulk endpoint.

    `_latest_samples` is a single `DISTINCT ON (agent_id)` over
    `agent_host_samples`; a rewrite into "newest sample per agent" issued
    per row would still return byte-identical JSON and would only show up as
    latency on a real fleet. Counting statements at two fleet sizes and
    asserting the counts match is what catches that — and, unlike a hardcoded
    absolute count, it stays true when some unrelated query is added later.
    """
    _offline_redis(monkeypatch)

    def seed_fleet(count: int) -> None:
        for _ in range(count):
            agent = factories.agent(status="active")
            _seed_samples(
                db_session, agent, [(utcnow() - timedelta(seconds=30), {"cpu_pct": 12.5})]
            )

    seed_fleet(_SMALL_FLEET)
    with _capture_sql() as small_statements:
        small = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    seed_fleet(_LARGE_FLEET - _SMALL_FLEET)
    with _capture_sql() as large_statements:
        large = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert small.status_code == 200
    assert large.status_code == 200
    # Relative, not absolute: proves the second request really did read a
    # bigger fleet without assuming this test owns every agent row.
    assert len(large.json()) == len(small.json()) + (_LARGE_FLEET - _SMALL_FLEET)

    small_reads = _fleet_reads(small_statements)
    large_reads = _fleet_reads(large_statements)
    assert len(large_reads) == len(small_reads), (small_reads, large_reads)

    sample_reads = [s for s in large_reads if "agent_host_samples" in s]
    assert len(sample_reads) == 1, sample_reads
    # `raw` is the largest column in the table. A fleet read must never
    # materialize a host payload just to show eight numbers in a row.
    assert not any("agent_host_samples.raw" in s.lower() for s in large_statements)


@pytest.mark.asyncio
async def test_presence_latest_is_the_newest_sample_for_each_agent(
    client, db_session, factories, viewer_headers, monkeypatch
):
    """`DISTINCT ON` must order by `collected_at DESC`, not by insertion order.

    Rows are seeded newest-first so physical table order is the *reverse* of
    chronological order: an implementation that takes the first or the last
    row it happens to see passes on well-ordered data and fails here. The
    second agent pins that the per-agent partition is real and one agent's
    newest sample cannot surface on another's row.
    """
    _offline_redis(monkeypatch)
    now = utcnow()
    agent_a = factories.agent(status="active")
    agent_b = factories.agent(status="active")
    newest_a = now - timedelta(seconds=60)
    newest_b = now - timedelta(seconds=30)

    # Newest first, then two older rows — deliberately out of order.
    _seed_samples(db_session, agent_a, [(newest_a, {"cpu_pct": 91.5, "uptime_s": 7200})])
    _seed_samples(
        db_session,
        agent_a,
        [
            (now - timedelta(minutes=10), {"cpu_pct": 11.0, "uptime_s": 60}),
            (now - timedelta(minutes=5), {"cpu_pct": 22.0, "uptime_s": 360}),
        ],
    )
    _seed_samples(db_session, agent_b, [(newest_b, {"cpu_pct": 44.0})])
    _seed_samples(db_session, agent_b, [(now - timedelta(minutes=15), {"cpu_pct": 99.0})])

    resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert resp.status_code == 200
    body = resp.json()
    latest_a = _row_for(body, agent_a)["latest"]
    latest_b = _row_for(body, agent_b)["latest"]

    assert set(latest_a) == {"collected_at", *_LATEST_FIELDS}
    assert latest_a["cpu_pct"] == pytest.approx(91.5)
    assert latest_a["uptime_s"] == 7200
    assert datetime.fromisoformat(latest_a["collected_at"]) == newest_a
    # The backend does not judge staleness — it hands the client the stamp and
    # lets the client decide (design §1.3), so this must be tz-aware.
    assert datetime.fromisoformat(latest_a["collected_at"]).tzinfo is not None
    # Columns the sample never carried stay null rather than becoming 0.0.
    assert latest_a["max_temp_c"] is None

    assert latest_b["cpu_pct"] == pytest.approx(44.0)
    assert datetime.fromisoformat(latest_b["collected_at"]) == newest_b


@pytest.mark.asyncio
async def test_presence_latest_is_null_for_an_agent_with_no_samples(
    client, db_session, factories, viewer_headers, monkeypatch
):
    """`latest: null` is a real state and must never render as `0%`.

    Design §4: an agent without host telemetry granted reads "telemetry off".
    Coercing the missing row to a zero-filled summary would make a healthy
    agent that simply has no telemetry look idle, and would be indistinguishable
    from a genuinely idle machine. The seeded neighbour rules out the other
    failure mode — a join that fills the gap from whatever row is at hand.
    """
    _offline_redis(monkeypatch)
    silent = factories.agent(status="active")
    reporting = factories.agent(status="active")
    _seed_samples(db_session, reporting, [(utcnow() - timedelta(seconds=45), {"cpu_pct": 7.5})])

    resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert _row_for(body, silent)["latest"] is None
    assert _row_for(body, reporting)["latest"]["cpu_pct"] == pytest.approx(7.5)


@pytest.mark.asyncio
async def test_presence_carries_the_spool_backlog_with_null_distinct_from_zero(
    client, factories, viewer_headers, monkeypatch
):
    """Spool depth is "the one signal that predicts trouble before anything
    goes red" (design §4), so it rides the presence row straight off the
    already-loaded `Agent` — no extra query.

    `None` (the agent has never reported a spool) and `0` (it reported, and the
    spool is drained) are different facts and the row must keep them apart:
    collapsing `None` to `0` would render a reassuring "drained" chip for an
    agent that has told us nothing at all.
    """
    _offline_redis(monkeypatch)
    reported_at = utcnow() - timedelta(seconds=20)
    backlogged = factories.agent(
        status="active", spool_depth=42, spool_bytes=8192, spool_reported_at=reported_at
    )
    drained = factories.agent(
        status="active", spool_depth=0, spool_bytes=0, spool_reported_at=reported_at
    )
    never_reported = factories.agent(status="active")

    resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert resp.status_code == 200
    body = resp.json()

    backlogged_row = _row_for(body, backlogged)
    assert backlogged_row["spool_depth"] == 42
    assert backlogged_row["spool_bytes"] == 8192
    assert datetime.fromisoformat(backlogged_row["spool_reported_at"]) == reported_at

    drained_row = _row_for(body, drained)
    assert drained_row["spool_depth"] == 0
    assert drained_row["spool_bytes"] == 0
    assert drained_row["spool_reported_at"] is not None

    silent_row = _row_for(body, never_reported)
    assert silent_row["spool_depth"] is None
    assert silent_row["spool_bytes"] is None
    assert silent_row["spool_reported_at"] is None


# ── `GET /agents/metrics/series` — bucketing, cap and scope ──────────────────


def _ramp_bucket_specs(newest_bucket: datetime, values):
    """`_seed_samples` specs filling 24 buckets at `_DENSE_CADENCE_SECONDS`.

    `values(index)` supplies the column dict for the `index`-th raw sample, so a
    caller can seed a monotone ramp (whose bucket means are nothing like any
    individual sample, which is what separates averaging from decimation) or a
    constant.
    """
    specs = []
    index = 0
    for bucket in range(_SERIES_MAX_POINTS):
        bucket_start = newest_bucket - timedelta(
            seconds=_SERIES_BUCKET_SECONDS * (_SERIES_MAX_POINTS - 1 - bucket)
        )
        for offset in range(0, _SERIES_BUCKET_SECONDS, _DENSE_CADENCE_SECONDS):
            specs.append((bucket_start + timedelta(seconds=offset), values(index)))
            index += 1
    return specs


@pytest.mark.asyncio
async def test_series_caps_points_per_agent_and_averages_into_buckets(
    client, db_session, factories, viewer_headers
):
    """The cap is a SQL `LIMIT` over an averaged grid, not a Python slice.

    Each agent is seeded with 360 raw samples inside the 30-minute window — 15×
    the cap. If the endpoint returned raw rows (or decimated them) the payload
    would grow with the agent's configured `interval_s`; the whole point of
    §1.2 is that it cannot. The ramp is what proves *averaging*: bucket 0's
    mean is 7.0, a value no individual sample in that bucket carries, so a
    decimating implementation cannot produce it by luck.
    """
    agent_ramp = factories.agent(status="active")
    agent_flat = factories.agent(status="active")
    # Anchor one bucket into the future so the oldest sample keeps a full
    # bucket of slack over the `utcnow() - 30m` window the request recomputes.
    newest_bucket = _grid(utcnow(), _SERIES_BUCKET_SECONDS) + timedelta(
        seconds=_SERIES_BUCKET_SECONDS
    )
    _seed_samples(
        db_session,
        agent_ramp,
        _ramp_bucket_specs(newest_bucket, lambda i: {"cpu_pct": float(i), "mem_pct": 50.0}),
    )
    _seed_samples(
        db_session, agent_flat, _ramp_bucket_specs(newest_bucket, lambda _: {"cpu_pct": 5.0})
    )

    with _capture_sql() as statements:
        resp = await client.get(
            "/api/v1/agents/metrics/series",
            params={"ids": [agent_ramp.id, agent_flat.id]},
            headers=viewer_headers,
        )

    assert resp.status_code == 200
    body = resp.json()
    series_by_agent = {entry["agent_id"]: entry["points"] for entry in body}
    assert set(series_by_agent) == {agent_ramp.id, agent_flat.id}

    for points in series_by_agent.values():
        assert len(points) <= _SERIES_MAX_POINTS
        # And `== cap`, not only `<= cap`: the seeded window fills exactly the
        # cap, so a LIMIT set too low — or applied per fleet instead of per
        # agent — truncates a legitimate series, which `<=` alone cannot see.
        assert len(points) == _SERIES_MAX_POINTS
        assert all(set(point) == {"collected_at", *_SERIES_FIELDS} for point in points)

    ramp_points = series_by_agent[agent_ramp.id]
    # Means of 0..14 and of 345..359 — averaged, not sampled.
    assert ramp_points[0]["cpu_pct"] == pytest.approx((_SAMPLES_PER_BUCKET - 1) / 2)
    assert ramp_points[-1]["cpu_pct"] == pytest.approx(352.0)
    assert ramp_points[0]["mem_pct"] == pytest.approx(50.0)
    # A column no sample ever carried averages to NULL and stays a gap.
    assert all(point["net_rx_bps"] is None for point in ramp_points)
    assert all(point["cpu_pct"] == pytest.approx(5.0) for point in series_by_agent[agent_flat.id])

    stamps = [datetime.fromisoformat(point["collected_at"]) for point in ramp_points]
    assert stamps == sorted(stamps)
    assert all(int(stamp.timestamp()) % _SERIES_BUCKET_SECONDS == 0 for stamp in stamps)
    assert all(
        (later - earlier) == timedelta(seconds=_SERIES_BUCKET_SECONDS)
        for earlier, later in zip(stamps, stamps[1:], strict=False)
    )

    lowered = [statement.lower() for statement in statements]
    # The cap has to be expressed to the database, otherwise the rows are still
    # transferred and only then thrown away.
    assert any("avg(" in s and "group by" in s and "limit" in s for s in lowered), lowered


@pytest.mark.asyncio
async def test_series_scopes_to_the_requested_ids(client, db_session, factories, viewer_headers):
    """`ids` follows `/agents/presence`'s convention exactly.

    Omitted means the whole fleet; an explicit list means those agents;
    present-but-empty means *no* agents — a distinction the page relies on so
    that "I have filtered everything out" never silently re-fetches everything.

    The empty-list branch is asserted by calling the endpoint function directly
    because it is unreachable over the wire: httpx (like the frontend's axios
    serializer) drops an empty list from the query string entirely, which the
    route would correctly read as "omitted".
    """
    from app.api.agents import get_agents_metrics_series

    recent = utcnow() - timedelta(minutes=2)
    agent_a = factories.agent(status="active")
    agent_b = factories.agent(status="active")
    _seed_samples(db_session, agent_a, [(recent, {"cpu_pct": 10.0})])
    _seed_samples(db_session, agent_b, [(recent, {"cpu_pct": 20.0})])

    whole_fleet = await client.get("/api/v1/agents/metrics/series", headers=viewer_headers)
    assert whole_fleet.status_code == 200
    assert {entry["agent_id"] for entry in whole_fleet.json()} >= {agent_a.id, agent_b.id}

    filtered = await client.get(
        "/api/v1/agents/metrics/series", params={"ids": [agent_a.id]}, headers=viewer_headers
    )
    assert filtered.status_code == 200
    assert [entry["agent_id"] for entry in filtered.json()] == [agent_a.id]

    # `_user` is unused by the handler; the role check is FastAPI's, and it is
    # covered over HTTP by the auth test below.
    assert get_agents_metrics_series(db_session, None, ids=[]) == []


@pytest.mark.asyncio
async def test_series_never_selects_the_raw_jsonb_column(
    client, db_session, factories, viewer_headers
):
    """`raw` is the largest column in `agent_host_samples`.

    The sparkline needs four averaged numbers per bucket; pulling every host
    payload into the process to compute them is exactly the regression
    `test_agent_telemetry_history.py` already pins for the detail chart, and a
    fleet-wide read makes it N times worse.
    """
    agent = factories.agent(status="active")
    base = utcnow() - _SERIES_WINDOW + timedelta(minutes=5)
    _seed_samples(
        db_session,
        agent,
        ((base + timedelta(seconds=2 * i), {"cpu_pct": float(i % 40)}) for i in range(600)),
    )

    with _capture_sql() as statements:
        resp = await client.get("/api/v1/agents/metrics/series", headers=viewer_headers)

    assert resp.status_code == 200
    lowered = [statement.lower() for statement in statements]
    assert not any("agent_host_samples.raw" in s for s in lowered), lowered
    points = next(entry["points"] for entry in resp.json() if entry["agent_id"] == agent.id)
    assert len(points) <= _SERIES_MAX_POINTS


# ── Shared rules (design §1.3) ───────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/agents/presence", "/api/v1/agents/metrics/series"])
async def test_fleet_metric_routes_require_viewer_role(
    client, db_session, factories, viewer_headers, monkeypatch, path
):
    """Both routes sit behind `require_role("viewer")`, matching
    `/agents/{id}/telemetry` — host telemetry is not public.

    This doubles as the routing guard for `/metrics/series`: it is declared
    above `@router.get("/{agent_id}")`, and if it ever slides below it FastAPI
    parses `metrics` as an agent id and the anonymous request comes back 404 or
    422 instead of the expected 401/403.
    """
    _offline_redis(monkeypatch)
    agent = factories.agent(status="active")
    _seed_samples(db_session, agent, [(utcnow() - timedelta(minutes=1), {"cpu_pct": 3.0})])

    # `viewer_headers` logs in through the shared `client`, and httpx keeps the
    # session cookie that login set in the client's jar — so a request that
    # merely omits the Authorization header is still authenticated and would
    # come back 200 whatever the route declares. Existing agent auth tests
    # (`test_presence_requires_viewer_auth`) dodge this by never requesting a
    # login fixture; this one needs both halves, so it drops the jar instead.
    # The bearer token below is header-borne and unaffected.
    client.cookies.clear()

    anonymous = await client.get(path)
    assert anonymous.status_code in (401, 403)

    as_viewer = await client.get(path, headers=viewer_headers)
    assert as_viewer.status_code == 200
