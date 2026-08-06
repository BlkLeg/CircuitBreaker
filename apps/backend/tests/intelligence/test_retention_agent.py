"""Retention coverage for the agent host-sample branch.

The agent branch aggregates `agent_host_samples` into `agent_host_sample_hourly`
entirely in SQL (fleet-wide, grouped by agent_id) and must report every row it
touches back to the caller.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, insert, select

from app.db.models import AgentHostSample, AgentHostSampleHourly
from app.services.intelligence.retention import run_retention_executor


def _hour_floor(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _seed_agent_samples(db, agent, *, start, count, step, hardware_id=None, **overrides):
    """Bulk-seed `count` agent_host_samples via a single Core executemany.

    Deliberately not `factories.agent_host_sample` — the dense cases here seed
    thousands of rows and the per-row ORM flush would blow the 30 s per-test
    timeout for reasons unrelated to the code under test.
    """
    rows = []
    ts = start
    for i in range(count):
        row = {
            "agent_id": agent.id,
            "hardware_id": hardware_id,
            "sample_id": f"{agent.id:08x}{i:024x}",
            "collected_at": ts,
            "status": "healthy",
            "cpu_pct": 30.0,
            "mem_pct": 40.0,
            "root_disk_pct": 50.0,
            "net_rx_bps": 1000.0,
            "net_tx_bps": 2000.0,
            "max_temp_c": 45.0,
            "load_1": 0.5,
            "uptime_s": 3600,
            "raw": {},
            "projected_at": None,
        }
        row.update(overrides)
        rows.append(row)
        ts += step
    db.execute(insert(AgentHostSample), rows)
    db.flush()
    return len(rows)


class _SQLCapture:
    """Collects every statement executed on the shared engine."""

    def __init__(self):
        self.statements: list[str] = []

    def __enter__(self):
        from app.db.session import engine

        self._engine = engine

        def _listener(conn, cursor, statement, parameters, context, executemany):
            self.statements.append(statement)

        self._listener = _listener
        event.listen(engine, "after_cursor_execute", _listener)
        return self

    def __exit__(self, *exc):
        event.remove(self._engine, "after_cursor_execute", self._listener)
        return False

    @property
    def joined(self) -> str:
        return "\n".join(self.statements)


def test_retention_result_counts_agent_rows(db_session, factories):
    """48 h of 1-minute samples 10-12 days old collapse to 48 hourly buckets."""
    agent = factories.agent(status="approved")
    start = _hour_floor(datetime.now(tz=UTC) - timedelta(days=12))
    seeded = _seed_agent_samples(
        db_session, agent, start=start, count=48 * 60, step=timedelta(minutes=1)
    )
    assert seeded == 2880

    result = run_retention_executor(db_session, hot_days=7, warm_days=30)

    assert result["agent_downsampled"] == 48
    assert result["agent_deleted"] == 2880
    assert result["agent_hourly_deleted"] == 0
    # Grand totals fold the agent branch in alongside the hardware branch.
    assert result["downsampled"] == result["hardware_downsampled"] + 48
    assert result["deleted"] == result["hardware_deleted"] + 2880
    assert result["downsampled"] >= 48
    assert result["deleted"] >= 2880

    db_session.expire_all()
    buckets = (
        db_session.execute(
            select(AgentHostSampleHourly).where(AgentHostSampleHourly.agent_id == agent.id)
        )
        .scalars()
        .all()
    )
    assert len(buckets) == 48
    assert all(b.sample_count == 60 for b in buckets)
    assert (
        db_session.execute(select(AgentHostSample).where(AgentHostSample.agent_id == agent.id))
        .scalars()
        .all()
        == []
    )


def test_agent_hourly_summary_includes_uptime_s(db_session, factories):
    """The hourly summary carries all eight fields the history endpoint emits."""
    agent = factories.agent(status="approved")
    bucket = _hour_floor(datetime.now(tz=UTC) - timedelta(days=9))
    factories.agent_host_sample(
        agent,
        collected_at=bucket + timedelta(minutes=1),
        cpu_pct=10.0,
        mem_pct=20.0,
        root_disk_pct=30.0,
        net_rx_bps=100.0,
        net_tx_bps=200.0,
        max_temp_c=40.0,
        load_1=1.0,
        uptime_s=100,
    )
    factories.agent_host_sample(
        agent,
        collected_at=bucket + timedelta(minutes=2),
        cpu_pct=20.0,
        mem_pct=40.0,
        root_disk_pct=60.0,
        net_rx_bps=300.0,
        net_tx_bps=400.0,
        max_temp_c=50.0,
        load_1=3.0,
        uptime_s=200,
    )

    run_retention_executor(db_session, hot_days=7, warm_days=30)

    db_session.expire_all()
    row = db_session.execute(
        select(AgentHostSampleHourly).where(AgentHostSampleHourly.agent_id == agent.id)
    ).scalar_one()
    assert row.sample_count == 2
    assert set(row.summary) == {
        "cpu_pct",
        "mem_pct",
        "root_disk_pct",
        "net_rx_bps",
        "net_tx_bps",
        "max_temp_c",
        "load_1",
        "uptime_s",
    }
    assert row.summary["uptime_s"] == pytest.approx(150.0)
    assert row.summary["cpu_pct"] == pytest.approx(15.0)
    assert row.summary["load_1"] == pytest.approx(2.0)


@pytest.mark.timeout(120)
def test_agent_downsample_runs_in_sql(db_session, factories):
    """The aggregate is one INSERT ... SELECT ... GROUP BY; `raw` is never read."""
    agent = factories.agent(status="approved")
    start = _hour_floor(datetime.now(tz=UTC) - timedelta(days=12))
    _seed_agent_samples(db_session, agent, start=start, count=10_000, step=timedelta(seconds=10))

    with _SQLCapture() as cap:
        run_retention_executor(db_session, hot_days=7, warm_days=30)

    upserts = [
        s
        for s in cap.statements
        if "INSERT INTO agent_host_sample_hourly" in s and "GROUP BY" in s and "SELECT" in s
    ]
    assert len(upserts) == 1, cap.joined
    assert "ON CONFLICT" in upserts[0]

    # No statement may materialize the JSONB payload column.
    assert "agent_host_samples.raw" not in cap.joined, cap.joined


def test_agent_retention_is_idempotent(db_session, factories):
    """Two consecutive runs converge; the second downsamples nothing."""
    agent = factories.agent(status="approved")
    start = _hour_floor(datetime.now(tz=UTC) - timedelta(days=12))
    _seed_agent_samples(db_session, agent, start=start, count=120, step=timedelta(minutes=1))

    first = run_retention_executor(db_session, hot_days=7, warm_days=30)
    db_session.expire_all()
    snapshot = sorted(
        (r.bucket_at, r.sample_count, tuple(sorted(r.summary.items())))
        for r in db_session.execute(select(AgentHostSampleHourly)).scalars().all()
    )

    second = run_retention_executor(db_session, hot_days=7, warm_days=30)
    db_session.expire_all()
    after = sorted(
        (r.bucket_at, r.sample_count, tuple(sorted(r.summary.items())))
        for r in db_session.execute(select(AgentHostSampleHourly)).scalars().all()
    )

    assert first["agent_downsampled"] == 2
    assert second["agent_downsampled"] == 0
    assert second["agent_deleted"] == 0
    assert after == snapshot


def test_agent_retention_uses_no_timescale_functions(db_session, factories):
    """Bucketing must stay portable — no time_bucket(), no date_bin()."""
    agent = factories.agent(status="approved")
    start = _hour_floor(datetime.now(tz=UTC) - timedelta(days=12))
    _seed_agent_samples(db_session, agent, start=start, count=10, step=timedelta(minutes=1))

    with _SQLCapture() as cap:
        run_retention_executor(db_session, hot_days=7, warm_days=30)

    lowered = cap.joined.lower()
    assert "time_bucket" not in lowered, cap.joined
    assert "date_bin" not in lowered, cap.joined
    assert "to_timestamp" in lowered, cap.joined


def test_agent_samples_older_than_warm_cutoff_are_deleted_not_aggregated(db_session, factories):
    """Cold rows are purged without aggregation — by design, they are already cold."""
    agent = factories.agent(status="approved")
    factories.agent_host_sample(
        agent, collected_at=datetime.now(tz=UTC) - timedelta(days=40), uptime_s=10
    )

    result = run_retention_executor(db_session, hot_days=7, warm_days=30)

    assert result["agent_downsampled"] == 0
    assert result["agent_deleted"] == 1
    db_session.expire_all()
    assert db_session.execute(select(AgentHostSampleHourly)).scalars().all() == []


def test_agent_hourly_rows_older_than_warm_cutoff_are_purged(db_session, factories):
    """Expired hourly buckets are counted, not silently dropped."""
    agent = factories.agent(status="approved")
    factories.agent_host_sample_hourly(
        agent,
        bucket_at=_hour_floor(datetime.now(tz=UTC) - timedelta(days=45)),
        sample_count=60,
        summary={"cpu_pct": 1.0},
    )

    result = run_retention_executor(db_session, hot_days=7, warm_days=30)

    assert result["agent_hourly_deleted"] == 1
    assert result["deleted"] >= 1
    db_session.expire_all()
    assert db_session.execute(select(AgentHostSampleHourly)).scalars().all() == []


def test_agent_rows_are_visible_before_the_caller_commits(db_session, factories):
    """run_retention_executor does not commit; the caller (analytics_worker) does."""
    agent = factories.agent(status="approved")
    start = _hour_floor(datetime.now(tz=UTC) - timedelta(days=12))
    _seed_agent_samples(db_session, agent, start=start, count=60, step=timedelta(minutes=1))

    run_retention_executor(db_session, hot_days=7, warm_days=30)

    db_session.expire_all()
    rows = db_session.execute(select(AgentHostSampleHourly)).scalars().all()
    assert len(rows) == 1
    assert rows[0].sample_count == 60


def test_stale_hourly_bucket_is_recomputed_not_skipped(db_session, factories):
    """The upsert must be DO UPDATE, not DO NOTHING.

    `test_agent_retention_is_idempotent` cannot pin this: the first run deletes
    the raw rows it aggregated, so the second run's SELECT is empty and never
    reaches the conflict target at all. Seeding a *stale* hourly row alongside
    raw samples that still exist is the only way to drive the conflict branch,
    and it is the branch that matters — a bucket re-aggregated after late-
    arriving samples must overwrite, not silently keep the old numbers.
    """
    agent = factories.agent(status="approved")
    bucket = _hour_floor(datetime.now(tz=UTC) - timedelta(days=12))
    _seed_agent_samples(
        db_session, agent, start=bucket, count=4, step=timedelta(minutes=10), cpu_pct=80.0
    )
    factories.agent_host_sample_hourly(
        agent,
        bucket_at=bucket,
        sample_count=1,
        summary={"cpu_pct": 1.0},
    )

    result = run_retention_executor(db_session, hot_days=7, warm_days=30)
    db_session.expire_all()

    rows = (
        db_session.execute(
            select(AgentHostSampleHourly).where(AgentHostSampleHourly.bucket_at == bucket)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "the conflict target must update in place, not insert a duplicate"
    assert rows[0].sample_count == 4, "stale sample_count survived — upsert is DO NOTHING"
    assert rows[0].summary["cpu_pct"] == 80.0, "stale summary survived — upsert is DO NOTHING"
    assert result["agent_downsampled"] == 1
