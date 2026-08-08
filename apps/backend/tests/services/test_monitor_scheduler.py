from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, text

from app.core.subjects import MONITOR_POLL_ITEM, MONITOR_PROBE_REMOTE
from app.db.models import MonitorItem, MonitorProbeRun
from app.services.monitoring.scheduler import (
    _PROBE_BUDGET_MAX_S,
    _PROBE_DEADLINE_HEADROOM_S,
    _PROBE_DEADLINE_MIN_S,
    claim_due_items,
    enqueue_due,
    probe_deadline_seconds,
)


def _mk(
    db,
    *,
    due_offset_s,
    enabled=True,
    interval=60,
    probe_agent_id=None,
    check_type="icmp",
    params=None,
):
    item = MonitorItem(
        target_type="ip",
        target_id=None,
        host="10.0.0.9",
        check_type=check_type,
        params=params if params is not None else {},
        interval_secs=interval,
        enabled=enabled,
        next_due_at=datetime.now(UTC) + timedelta(seconds=due_offset_s),
        probe_agent_id=probe_agent_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _seed(db, count, *, probe_agent_id=None, due_offset_s=-5, interval=60):
    """Bulk-insert `count` due monitors on one vantage (core insert: 400 rows
    through the ORM unit of work would blow the 30 s suite timeout)."""
    now = datetime.now(UTC)
    db.execute(
        insert(MonitorItem),
        [
            {
                "name": f"v{probe_agent_id}-{i}",
                "target_type": "ip",
                "target_id": None,
                "host": "10.0.0.9",
                "check_type": "icmp",
                "params": {},
                "interval_secs": interval,
                "enabled": True,
                "next_due_at": now + timedelta(seconds=due_offset_s, milliseconds=-i),
                "probe_agent_id": probe_agent_id,
            }
            for i in range(count)
        ],
    )
    db.commit()


def _collecting_publish(published, result=True):
    async def publish(subject, payload):
        published.append((subject, payload))
        return result

    return publish


def _sql_now(db):
    return db.execute(text("SELECT now()")).scalar_one()


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


# ── Fair-share claiming (D-2) ────────────────────────────────────────────────


def test_claim_returns_probe_agent_id(db_session, factories):
    """Silent-failure guard: without probe_agent_id in RETURNING every monitor
    looks like a server monitor and nothing else in this task is observable."""
    agent = factories.agent(status="active")
    db_session.flush()
    server_item = _mk(db_session, due_offset_s=-5)
    agent_item = _mk(db_session, due_offset_s=-5, probe_agent_id=agent.id)

    claimed = {c["item_id"]: c["probe_agent_id"] for c in claim_due_items(db_session, batch=100)}
    assert claimed == {server_item.id: None, agent_item.id: agent.id}


def test_per_vantage_cap_limits_one_agent_to_fifty_per_tick(db_session, factories):
    agent = factories.agent(status="active")
    db_session.flush()
    _seed(db_session, 60, probe_agent_id=agent.id)

    claimed = claim_due_items(db_session, batch=200)
    assert len(claimed) == 50
    assert {c["probe_agent_id"] for c in claimed} == {agent.id}


def test_one_busy_vantage_does_not_starve_another(db_session, factories):
    """The fairness property D-2 exists to provide. Agent A's backlog is both
    larger and older, so a plain `ORDER BY next_due_at LIMIT 200` claim would
    return nothing at all for agent B."""
    agent_a = factories.agent(status="active")
    agent_b = factories.agent(status="active")
    db_session.flush()
    _seed(db_session, 400, probe_agent_id=agent_a.id, due_offset_s=-600)
    _seed(db_session, 10, probe_agent_id=agent_b.id, due_offset_s=-5)

    claimed = claim_due_items(db_session, batch=200)
    per_vantage = Counter(c["probe_agent_id"] for c in claimed)
    assert per_vantage[agent_b.id] == 10
    assert per_vantage[agent_a.id] == 50


def test_global_batch_limit_is_still_two_hundred(db_session, factories):
    agents = [factories.agent(status="active") for _ in range(5)]
    db_session.flush()
    for agent in agents:
        _seed(db_session, 50, probe_agent_id=agent.id)

    claimed = claim_due_items(db_session, batch=200)
    assert len(claimed) == 200


# ── Routing and run creation ─────────────────────────────────────────────────


async def test_server_monitors_publish_to_mon_poll_item_and_agent_monitors_to_mon_probe_remote(
    db_session, factories
):
    agent = factories.agent(status="active")
    db_session.flush()
    server_item = _mk(db_session, due_offset_s=-5)
    agent_item = _mk(db_session, due_offset_s=-5, probe_agent_id=agent.id)

    published: list[tuple[str, dict]] = []
    assert await enqueue_due(db_session, _collecting_publish(published), batch=200) == 2

    poll = [p for s, p in published if s == MONITOR_POLL_ITEM]
    probe = [p for s, p in published if s == MONITOR_PROBE_REMOTE]
    assert [p["item_id"] for p in poll] == [server_item.id]
    assert len(probe) == 1

    run = db_session.query(MonitorProbeRun).filter_by(monitor_id=agent_item.id).one()
    assert probe[0]["run_id"] == run.run_id


async def test_agent_route_creates_a_queued_run_and_publishes_only_the_run_id(
    db_session, factories
):
    agent = factories.agent(status="active")
    db_session.flush()
    item = _mk(db_session, due_offset_s=-5, probe_agent_id=agent.id)

    published: list[tuple[str, dict]] = []
    assert await enqueue_due(db_session, _collecting_publish(published), batch=200) == 1

    subject, payload = published[0]
    assert subject == MONITOR_PROBE_REMOTE
    # §2: NATS carries the run id and nothing else — no host, no config, no
    # credentials. The dispatcher loads all of that from the database.
    assert list(payload) == ["run_id"]

    run = db_session.query(MonitorProbeRun).filter_by(monitor_id=item.id).one()
    assert run.run_id == payload["run_id"]
    assert len(run.run_id) == 32
    assert run.agent_id == agent.id
    assert run.status == "queued"
    assert run.deadline_at > run.scheduled_at

    db_session.expire_all()
    refreshed = db_session.get(MonitorItem, item.id)
    assert refreshed.probe_execution_status == "queued"
    assert refreshed.probe_execution_reason is None


async def test_second_claim_while_a_run_is_active_skips_the_interval_without_a_second_run(
    db_session, factories
):
    """D-6: a monitor that becomes due with a run still in flight skips the
    interval — no second run, no pulled-back next_due_at."""
    agent = factories.agent(status="active")
    db_session.flush()
    item = _mk(db_session, due_offset_s=-5, probe_agent_id=agent.id)

    published: list[tuple[str, dict]] = []
    assert await enqueue_due(db_session, _collecting_publish(published), batch=200) == 1

    db_session.execute(
        text("UPDATE monitor_items SET next_due_at = now() - interval '1 second' WHERE id = :i"),
        {"i": item.id},
    )
    db_session.commit()
    published.clear()

    assert await enqueue_due(db_session, _collecting_publish(published), batch=200) == 0
    assert published == []
    assert db_session.query(MonitorProbeRun).filter_by(monitor_id=item.id).count() == 1

    db_session.expire_all()
    refreshed = db_session.get(MonitorItem, item.id)
    assert refreshed.probe_execution_status == "running"
    assert refreshed.probe_execution_reason == "previous_run_in_flight"
    # Skipped, not retried soon: the claim's advance stands.
    assert refreshed.next_due_at > _sql_now(db_session) + timedelta(seconds=30)


async def test_publish_failure_pulls_next_due_at_back_and_records_dispatch_failed(
    db_session, factories
):
    """§8: nats_client.js_publish never raises — it returns False and logs. The
    compensating UPDATE is the only thing that keeps the monitor from silently
    waiting a full interval."""
    agent = factories.agent(status="active")
    db_session.flush()
    item = _mk(db_session, due_offset_s=-5, interval=600, probe_agent_id=agent.id)

    published: list[tuple[str, dict]] = []
    assert await enqueue_due(db_session, _collecting_publish(published, result=False)) == 0

    db_session.expire_all()
    refreshed = db_session.get(MonitorItem, item.id)
    assert refreshed.probe_execution_status == "unavailable"
    assert refreshed.probe_execution_reason == "dispatch_failed"
    assert refreshed.next_due_at <= _sql_now(db_session) + timedelta(seconds=5)

    run = db_session.query(MonitorProbeRun).filter_by(monitor_id=item.id).one()
    assert run.status == "execution_error"
    assert run.error_code == "dispatch_failed"
    assert run.completed_at is not None

    # The failed run must not hold the partial unique index, or the retry the
    # pull-back just scheduled would be skipped as "previous_run_in_flight".
    # (`now()` is frozen at the outer transaction's start under the SAVEPOINT
    # fixture, so the jittered pull-back is never *reached* here; make it due.)
    db_session.execute(
        text("UPDATE monitor_items SET next_due_at = now() - interval '1 second' WHERE id = :i"),
        {"i": item.id},
    )
    db_session.commit()
    published.clear()
    assert await enqueue_due(db_session, _collecting_publish(published)) == 1
    assert [s for s, _ in published] == [MONITOR_PROBE_REMOTE]


async def test_claim_still_never_wedges_an_item_after_a_publish_crash(db_session, factories):
    """Preserves tests/integration/test_monitor_engine_e2e.py::
    test_restart_self_heals_no_wedged_items for the remote vantage: the claim
    commits before anything is published, so a crash leaves the item merely
    scheduled ahead rather than stuck."""
    agent = factories.agent(status="active")
    db_session.flush()
    item = _mk(db_session, due_offset_s=-5, probe_agent_id=agent.id)

    async def exploding_publish(subject, payload):
        raise RuntimeError("nats went away mid-tick")

    with pytest.raises(RuntimeError):
        await enqueue_due(db_session, exploding_publish, batch=200)

    assert claim_due_items(db_session, batch=200) == []
    db_session.expire_all()
    refreshed = db_session.get(MonitorItem, item.id)
    assert refreshed.next_due_at > _sql_now(db_session)


# ── Probe deadline derived from the monitor's own budget ─────────────────────
# A run whose deadline is shorter than what the check actually spends expires,
# the agent answers `execution_error`, and an execution error never moves
# monitor state — so the monitor keeps reporting its last status forever while
# the server-executed twin reports DOWN. The deadline therefore has to come from
# the monitor's own configuration, using the same defaults the collectors apply
# (the parity contract's numbers), not from one fixed constant.


@pytest.mark.parametrize(
    ("check_type", "params", "spends_s"),
    [
        # Parity contract: ICMP defaults packet_count=5, timeout=1.5.
        ("icmp", {}, 5 * 1.5),
        # The reported failure: 20 packets x the default 1.5 s = 30 s of work.
        ("icmp", {"packet_count": 20}, 20 * 1.5),
        ("icmp", {"packet_count": 10, "timeout": 4.0}, 40.0),
        # TCP tries each port in order, one timeout each — and then each
        # resolved address per port, so a dual-stack name costs twice that.
        ("tcp", {}, 1.0),
        ("tcp", {"ports": [22, 80, 443, 8080], "timeout": 5.0}, 2 * 4 * 5.0),
        # HTTP spends the request timeout, then the separate TLS capture.
        ("http", {}, 2 * 10.0),
        ("http", {"timeout": 30.0}, 60.0),
        # DNS bounds the whole resolution by one timeout.
        ("dns", {}, 5.0),
        ("dns", {"timeout": 20.0}, 20.0),
    ],
)
def test_probe_deadline_covers_what_the_check_actually_spends(check_type, params, spends_s):
    assert probe_deadline_seconds(check_type, params) > spends_s


def test_probe_deadline_keeps_a_floor_for_cheap_checks():
    assert probe_deadline_seconds("tcp", {}) == _PROBE_DEADLINE_MIN_S
    assert probe_deadline_seconds("icmp", None) == _PROBE_DEADLINE_MIN_S


def test_probe_deadline_is_bounded_and_survives_junk_config():
    ceiling = _PROBE_BUDGET_MAX_S + _PROBE_DEADLINE_HEADROOM_S
    assert probe_deadline_seconds("tcp", {"ports": list(range(1, 4000)), "timeout": 30}) == ceiling
    # params is free-form JSONB; a junk value must fall back to the collector
    # default rather than take down the whole scheduler tick.
    assert probe_deadline_seconds("icmp", {"packet_count": "lots"}) == _PROBE_DEADLINE_MIN_S
    assert probe_deadline_seconds("nonsense", {}) == _PROBE_DEADLINE_MIN_S


async def test_run_deadline_is_derived_from_the_monitors_configured_budget(db_session, factories):
    """The concrete failure: 20 packets at the default 1.5 s timeout needs 30 s
    to observe 100% loss. A fixed 20 s deadline expires the run mid-check."""
    agent = factories.agent(status="active")
    db_session.flush()
    item = _mk(
        db_session,
        due_offset_s=-5,
        probe_agent_id=agent.id,
        check_type="icmp",
        params={"packet_count": 20},
    )

    published: list[tuple[str, dict]] = []
    assert await enqueue_due(db_session, _collecting_publish(published), batch=200) == 1

    run = db_session.query(MonitorProbeRun).filter_by(monitor_id=item.id).one()
    assert (run.deadline_at - run.scheduled_at).total_seconds() > 20 * 1.5


async def test_default_http_run_deadline_covers_request_plus_tls_capture(db_session, factories):
    """Sparse config is the normal case (`model_dump(exclude_unset=True)`), so
    the collector-side defaults have to be applied here too: an empty HTTP
    config still spends timeout=10 on the request and another 10 on the
    separate TLS connection."""
    agent = factories.agent(status="active")
    db_session.flush()
    item = _mk(
        db_session,
        due_offset_s=-5,
        probe_agent_id=agent.id,
        check_type="http",
        params={},
    )

    published: list[tuple[str, dict]] = []
    assert await enqueue_due(db_session, _collecting_publish(published), batch=200) == 1

    run = db_session.query(MonitorProbeRun).filter_by(monitor_id=item.id).one()
    assert (run.deadline_at - run.scheduled_at).total_seconds() > 2 * 10.0
