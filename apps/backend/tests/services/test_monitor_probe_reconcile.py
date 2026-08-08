"""Reconciliation: expiry, staleness, and probe-run retention (Slice 3 §8, D-4, D-5).

The scheduler's own tick owns all of it (D-5). Without it the §1 partial unique
index turns one silent agent into a permanent wedge for that monitor — the
mirror image of the property
`tests/integration/test_monitor_engine_e2e.py::test_restart_self_heals_no_wedged_items`
already protects for the server path.
"""

import inspect
from datetime import timedelta

import pytest

from app.core.time import utcnow
from app.db.models import MonitorEvent, MonitorItem, MonitorProbeRun
from app.services.monitoring import probe_reconcile, result_service
from app.services.monitoring.collectors import Sample
from app.workers import monitor_scheduler


class _FakeRedis:
    """Only what `agent_registry.bulk_presence` reaches for."""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self._store.get(k) for k in keys]

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def publish(self, channel: str, payload: str) -> int:
        return 0


@pytest.fixture
def presence(monkeypatch):
    """Agent presence, controlled by the test rather than by a live Redis."""
    store: dict[str, str] = {}

    async def _get_redis():
        return _FakeRedis(store)

    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)
    monkeypatch.setattr(result_service, "get_redis", _get_redis)

    def mark(agent) -> None:
        store[f"agent:presence:{agent.id}"] = "{}"

    return mark


def _healthy_agent(factories, *, collector: str = "probe.icmp"):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    factories.agent_capability_readiness(agent, collector=collector, state="ready")
    return agent


def _assigned_monitor(factories, agent, **kwargs):
    defaults = {
        "probe_agent_id": agent.id,
        "check_type": "icmp",
        "interval_secs": 60,
        "last_status": "up",
        "next_due_at": utcnow() + timedelta(seconds=60),
    }
    defaults.update(kwargs)
    return factories.monitor_item(**defaults)


async def test_overdue_run_is_expired_and_monitor_marked_unavailable(
    db_session, factories, presence
):
    agent = _healthy_agent(factories)
    item = _assigned_monitor(factories, agent, probe_execution_status="running")
    now = utcnow()
    run = factories.monitor_probe_run(
        item,
        agent,
        status="dispatched",
        scheduled_at=now - timedelta(seconds=120),
        deadline_at=now - timedelta(seconds=100),
    )
    db_session.flush()

    summary = await probe_reconcile.reconcile(db_session)

    db_session.expire_all()
    assert summary.expired == 1
    stored = db_session.get(MonitorProbeRun, run.id)
    assert stored.status == "expired"
    assert stored.error_code == probe_reconcile.REASON_RESULT_TIMEOUT
    assert stored.completed_at is not None

    monitor = db_session.get(MonitorItem, item.id)
    assert monitor.probe_execution_status == "unavailable"
    assert monitor.probe_execution_reason == probe_reconcile.REASON_RESULT_TIMEOUT
    # §2/D-12: an unavailable vantage is not a down target.
    assert monitor.last_status == "up"
    assert monitor.consecutive_failures == 0
    assert monitor.last_polled_at is None


async def test_expired_run_releases_the_partial_unique_index_so_the_monitor_dispatches_again(
    db_session, factories, presence
):
    """The anti-wedge property: a silent agent must not own the monitor forever."""
    agent = _healthy_agent(factories)
    item = _assigned_monitor(factories, agent)
    now = utcnow()
    factories.monitor_probe_run(
        item,
        agent,
        status="dispatched",
        scheduled_at=now - timedelta(seconds=120),
        deadline_at=now - timedelta(seconds=100),
    )
    db_session.flush()

    await probe_reconcile.reconcile(db_session)

    factories.monitor_probe_run(
        item,
        agent,
        status="queued",
        scheduled_at=utcnow(),
        deadline_at=utcnow() + timedelta(seconds=20),
    )
    db_session.flush()  # no IntegrityError: the index is free again

    assert (
        db_session.query(MonitorProbeRun)
        .filter(
            MonitorProbeRun.monitor_id == item.id,
            MonitorProbeRun.status.in_(("queued", "dispatched")),
        )
        .count()
        == 1
    )


async def test_reconciliation_runs_under_the_existing_scheduler_advisory_lock(
    db_session, monkeypatch
):
    """D-5: no new worker and no second lock — it is the first thing `tick` does."""
    calls: list[str] = []

    async def fake_reconcile(db, **kwargs):
        calls.append("reconcile")
        return probe_reconcile.ReconcileSummary()

    async def fake_enqueue(db, publish, **kwargs):
        calls.append("enqueue")
        return 0

    monkeypatch.setattr(probe_reconcile, "reconcile", fake_reconcile)
    monkeypatch.setattr(monitor_scheduler, "enqueue_due", fake_enqueue)

    async def publish(subject, payload):
        return True

    await monitor_scheduler.tick(lambda: db_session, publish)

    assert calls == ["reconcile", "enqueue"]
    # The scheduler's advisory lock is the only one on this path; a second lock
    # would let reconciliation run in a replica that is not the active clock.
    assert monitor_scheduler._LOCK_NAME == "monitor_scheduler"
    assert "try_advisory_lock" not in inspect.getsource(probe_reconcile)


async def test_ready_agent_with_no_recent_result_is_marked_stale(db_session, factories, presence):
    """D-4: healthy-looking vantage, no accepted result within 2 x interval_secs."""
    agent = _healthy_agent(factories)
    presence(agent)
    item = _assigned_monitor(
        factories,
        agent,
        interval_secs=60,
        probe_execution_status="running",
        probe_last_result_at=utcnow() - timedelta(seconds=300),
    )
    db_session.flush()

    summary = await probe_reconcile.reconcile(db_session)

    db_session.expire_all()
    assert summary.stale == 1
    monitor = db_session.get(MonitorItem, item.id)
    assert monitor.probe_execution_status == "stale"
    assert monitor.probe_execution_reason == probe_reconcile.REASON_NO_RECENT_RESULT
    assert monitor.last_status == "up"

    events = db_session.query(MonitorEvent).filter(MonitorEvent.item_id == item.id).all()
    assert [e.event_type for e in events] == [result_service.EVENT_EXECUTION]
    # The target's own state is carried through, never rewritten (§7).
    assert events[0].status_to == "up"


async def test_stale_clears_on_the_next_completed_result(db_session, factories, presence):
    agent = _healthy_agent(factories)
    presence(agent)
    item = _assigned_monitor(
        factories,
        agent,
        interval_secs=60,
        probe_execution_status="running",
        probe_last_result_at=utcnow() - timedelta(seconds=300),
    )
    db_session.flush()
    await probe_reconcile.reconcile(db_session)
    db_session.expire_all()
    assert db_session.get(MonitorItem, item.id).probe_execution_status == "stale"

    run = factories.monitor_probe_run(
        item,
        agent,
        status="dispatched",
        scheduled_at=utcnow(),
        deadline_at=utcnow() + timedelta(seconds=20),
    )
    db_session.flush()
    result_service.persist_results(
        db_session,
        [
            result_service.MonitorResult(
                item_id=item.id,
                target_type=item.target_type,
                target_id=item.target_id,
                check_type=item.check_type,
                samples=[Sample("avail", 1.0)],
                up=True,
                msg="1.2ms avg, 0.0% loss",
                checked_at=utcnow(),
                source=result_service.SOURCE_AGENT,
                agent_id=agent.id,
                run_id=run.run_id,
            )
        ],
    )

    db_session.expire_all()
    monitor = db_session.get(MonitorItem, item.id)
    assert monitor.probe_execution_status == "ready"
    assert monitor.probe_execution_reason is None
    assert monitor.probe_last_result_at is not None


def test_runs_older_than_seven_days_are_purged(db_session, factories):
    """§1: seven days. Long-term availability lives in telemetry_timeseries."""
    agent = factories.agent(status="active")
    item = factories.monitor_item(probe_agent_id=agent.id)
    now = utcnow()
    old = factories.monitor_probe_run(
        item,
        agent,
        status="completed",
        scheduled_at=now - timedelta(days=8),
        created_at=now - timedelta(days=8),
    )
    recent = factories.monitor_probe_run(
        item,
        agent,
        status="completed",
        scheduled_at=now - timedelta(days=1),
        created_at=now - timedelta(days=1),
    )
    db_session.flush()
    old_id, recent_id = old.id, recent.id

    deleted = probe_reconcile.purge_probe_runs(db_session)

    assert deleted == 1
    assert db_session.get(MonitorProbeRun, old_id) is None
    assert db_session.get(MonitorProbeRun, recent_id) is not None
