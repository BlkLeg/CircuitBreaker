"""Slice 3 §2's dispatch half: `mon.probe.remote` -> `probe.assign`.

The scheduler puts nothing but a `run_id` on NATS; everything the agent needs —
host, complete validated config, any HTTP credentials — is loaded here,
immediately before encrypted delivery over the live /link socket (D-10).
"""

import json
from datetime import timedelta

import pytest

from app.core.time import utcnow
from app.db.models import MonitorItem, MonitorProbeRun
from app.schemas.agent_frame import TYPE_PROBE_ASSIGN, ProbeAssignPayload
from app.workers import monitor_probe_dispatch as dispatch


class _FakeRedis:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def get(self, key: str) -> str | None:
        return self._store.get(key)


@pytest.fixture
def presence(monkeypatch):
    store: dict[str, str] = {}

    async def _get_redis():
        return _FakeRedis(store)

    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)

    def mark(agent, worker: str = "worker-1") -> None:
        store[f"agent:presence:{agent.id}"] = "{}"
        store[f"agent:connection:{agent.id}"] = worker

    return mark


@pytest.fixture
def published(monkeypatch):
    """Capture what the dispatcher hands the generic control-frame path."""
    frames: list[tuple[int, dict]] = []

    async def _publish(agent_id: int, frame: dict) -> bool:
        frames.append((agent_id, frame))
        return True

    monkeypatch.setattr("app.services.agent_registry.publish_agent_control_frame", _publish)
    return frames


def _ready_agent(factories, *, collector: str = "probe.tcp"):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    factories.agent_network(agent)  # 10.0.0.5/24 -> derived scope 10.0.0.0/24
    factories.agent_capability_readiness(agent, collector=collector, state="ready")
    return agent


def _queued_run(db_session, factories, agent, monitor):
    now = utcnow()
    run = factories.monitor_probe_run(
        monitor,
        agent,
        status="queued",
        scheduled_at=now,
        deadline_at=now + timedelta(seconds=20),
    )
    monitor.probe_execution_status = "queued"
    db_session.flush()
    return run


async def test_dispatch_loads_full_config_and_publishes_probe_assign(
    db_session, factories, presence, published
):
    agent = _ready_agent(factories)
    presence(agent)
    monitor = factories.monitor_item(
        host="10.0.0.9",
        check_type="tcp",
        params={"ports": [8443], "timeout": 2.5},
        probe_agent_id=agent.id,
    )
    run = _queued_run(db_session, factories, agent, monitor)

    assert await dispatch.dispatch_run(db_session, run.run_id) is True

    assert len(published) == 1
    agent_id, frame = published[0]
    assert agent_id == agent.id
    assert frame["type"] == TYPE_PROBE_ASSIGN
    payload = frame["payload"]
    assert payload["run_id"] == run.run_id
    assert payload["monitor_id"] == monitor.id
    assert payload["check_type"] == "tcp"
    assert payload["host"] == "10.0.0.9"
    # The complete stored config travels, not a summary of it.
    assert payload["config"] == {"ports": [8443], "timeout": 2.5}
    # And it is exactly the shape both languages agreed on.
    ProbeAssignPayload.model_validate(payload)

    db_session.expire_all()
    stored = db_session.get(MonitorProbeRun, run.id)
    assert stored.status == "dispatched"
    assert stored.dispatched_at is not None
    assert stored.attempt_count == 1
    item = db_session.get(MonitorItem, monitor.id)
    assert item.probe_execution_status == "running"
    assert item.probe_execution_reason is None
    assert item.probe_last_dispatched_at is not None


async def test_dispatch_assign_timestamps_are_rfc3339_with_a_T_separator(
    db_session, factories, presence, published
):
    """`publish_agent_control_frame` dumps with `json.dumps(..., default=str)`,
    which renders a raw `datetime` with a space separator that Go's `time.Time`
    rejects outright. The frame therefore has to carry strings already."""
    agent = _ready_agent(factories)
    presence(agent)
    monitor = factories.monitor_item(host="10.0.0.9", check_type="tcp", probe_agent_id=agent.id)
    run = _queued_run(db_session, factories, agent, monitor)

    await dispatch.dispatch_run(db_session, run.run_id)

    payload = published[0][1]["payload"]
    for field in ("scheduled_at", "deadline_at"):
        value = payload[field]
        assert isinstance(value, str), f"{field} is a raw {type(value).__name__}"
        assert "T" in value and " " not in value, f"{field} = {value!r}"

    # The whole frame must already be JSON-native: `default=str` firing at all
    # means something datetime-shaped slipped through.
    def _no_coercion(obj):
        raise AssertionError(f"non-JSON value in probe.assign: {obj!r}")

    json.dumps(published[0][1], default=_no_coercion)


async def test_dispatch_refuses_target_outside_effective_scope(
    db_session, factories, presence, published
):
    """The agent enforces scope again before connecting; this is the backend
    half of that pair, and it must refuse without ever reaching the socket."""
    agent = _ready_agent(factories)
    presence(agent)
    monitor = factories.monitor_item(host="192.168.50.5", check_type="tcp", probe_agent_id=agent.id)
    run = _queued_run(db_session, factories, agent, monitor)

    assert await dispatch.dispatch_run(db_session, run.run_id) is False

    assert published == []
    db_session.expire_all()
    stored = db_session.get(MonitorProbeRun, run.id)
    assert stored.status == "execution_error"
    assert stored.error_code == "out_of_scope"
    # `outcome` is what the agent reported, and it never saw this assignment.
    assert stored.outcome is None
    assert stored.completed_at is not None
    item = db_session.get(MonitorItem, monitor.id)
    assert item.probe_execution_status == "unavailable"
    assert item.probe_execution_reason == "out_of_scope"


async def test_undelivered_control_frame_marks_the_run_dispatch_failed(
    db_session, factories, presence, monkeypatch
):
    """`publish_agent_control_frame` returns False only when Redis itself is
    unavailable — a True with zero subscribers is "not guaranteed", not
    "delivered" — so False is the one signal that nothing can have arrived."""
    agent = _ready_agent(factories)
    presence(agent)
    monitor = factories.monitor_item(host="10.0.0.9", check_type="tcp", probe_agent_id=agent.id)
    run = _queued_run(db_session, factories, agent, monitor)

    async def _undeliverable(agent_id: int, frame: dict) -> bool:
        return False

    monkeypatch.setattr("app.services.agent_registry.publish_agent_control_frame", _undeliverable)

    assert await dispatch.dispatch_run(db_session, run.run_id) is False

    db_session.expire_all()
    stored = db_session.get(MonitorProbeRun, run.id)
    assert stored.status == "execution_error"
    assert stored.error_code == "dispatch_failed"
    assert stored.completed_at is not None
    item = db_session.get(MonitorItem, monitor.id)
    assert item.probe_execution_status == "unavailable"
    assert item.probe_execution_reason == "dispatch_failed"


async def test_offline_agent_marks_the_run_unavailable_without_publishing(
    db_session, factories, published
):
    agent = _ready_agent(factories)  # never marked present
    monitor = factories.monitor_item(host="10.0.0.9", check_type="tcp", probe_agent_id=agent.id)
    run = _queued_run(db_session, factories, agent, monitor)

    assert await dispatch.dispatch_run(db_session, run.run_id) is False

    assert published == []
    db_session.expire_all()
    stored = db_session.get(MonitorProbeRun, run.id)
    assert stored.status == "execution_error"
    assert stored.error_code == "agent_offline"
    item = db_session.get(MonitorItem, monitor.id)
    assert item.probe_execution_status == "unavailable"
    assert item.probe_execution_reason == "agent_offline"


async def test_a_run_that_is_no_longer_queued_is_a_no_op(
    db_session, factories, presence, published
):
    """Cancellation and expiry both close the run before the dispatcher gets to
    it; redelivering the NATS message must not resurrect it."""
    agent = _ready_agent(factories)
    presence(agent)
    monitor = factories.monitor_item(host="10.0.0.9", check_type="tcp", probe_agent_id=agent.id)
    run = _queued_run(db_session, factories, agent, monitor)
    run.status = "cancelled"
    db_session.flush()

    assert await dispatch.dispatch_run(db_session, run.run_id) is False

    assert published == []
    db_session.expire_all()
    assert db_session.get(MonitorProbeRun, run.id).status == "cancelled"


async def test_an_unknown_run_id_is_a_no_op(db_session, published):
    assert await dispatch.dispatch_run(db_session, "0" * 32) is False
    assert published == []


async def test_a_run_without_a_deadline_is_closed_rather_than_published(
    db_session, factories, presence, published
):
    """`probe.assign` requires `deadline_at` on both sides of the wire and the
    reconciliation pass expires runs *by* it, so publishing a null would produce
    a frame the agent rejects and a run nothing ever expires — a permanent wedge
    behind the partial unique index."""
    agent = _ready_agent(factories)
    presence(agent)
    monitor = factories.monitor_item(host="10.0.0.9", check_type="tcp", probe_agent_id=agent.id)
    run = _queued_run(db_session, factories, agent, monitor)
    run.deadline_at = None
    db_session.flush()

    assert await dispatch.dispatch_run(db_session, run.run_id) is False

    assert published == []
    db_session.expire_all()
    stored = db_session.get(MonitorProbeRun, run.id)
    assert stored.status == "execution_error"
    assert stored.error_code == "invalid_run"
