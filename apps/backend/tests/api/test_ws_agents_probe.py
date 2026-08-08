"""Remote probe over the real `/link` socket (Slice 3 §4).

Both directions of the probe protocol, end to end through the genuine Noise
transport rather than a service-level call: an assignment published by some
*other* worker process reaching the socket-holding one, and a result posted by
the agent closing its run and moving monitor state.

Patterned on `test_ws_agents_link.py` — same `agent_redis_default` opt-in, same
`_FakeTTLRedis` standing in for the one Redis instance two workers would share,
and the same `SessionLocal()`-committed fixtures, because `link_stream` opens
its own session and can never see `db_session`'s SAVEPOINT.

`conftest.py::_reap_agents_committed_outside_the_test` reaps the `agents` table
and nothing else, and `monitor_items.probe_agent_id` is RESTRICT — so a monitor
left behind here would make that reaper fail for every later test in the
session. Every test that commits monitor rows deletes them itself.
"""

import asyncio
import concurrent.futures
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta

import pytest

from app.core.agent_crypto import get_server_static_keypair
from tests.helpers.agent_noise_client import TestNoiseInitiator

pytestmark = pytest.mark.usefixtures("agent_redis_default")


class _FakeTTLRedis:
    """The pub/sub half of test_ws_agents_link.py's double.

    Only what this file's two tests touch: presence/connection SETEX-GET with
    real monotonic TTL expiry, the compare-and-delete script `/link`'s teardown
    runs, and a channel registry so `publish_agent_control_frame` and
    `link_stream`'s own subscribe meet in one process.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str]] = {}
        self._channels: dict[str, list[asyncio.Queue]] = {}

    async def setex(self, key: str, ttl: float, value: str) -> bool:
        self._store[key] = (time.monotonic() + ttl, value)
        return True

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            del self._store[key]
            return None
        return value

    async def exists(self, key: str) -> int:
        return 1 if await self.get(key) is not None else 0

    async def delete(self, *keys: str) -> int:
        return sum(1 for key in keys if self._store.pop(key, None) is not None)

    async def incr(self, key: str) -> int:
        entry = self._store.get(key)
        if entry is not None and time.monotonic() >= entry[0]:
            entry = None
        current = (int(entry[1]) if entry is not None else 0) + 1
        self._store[key] = (entry[0] if entry is not None else float("inf"), str(current))
        return current

    async def expire(self, key: str, ttl: float, nx: bool = False) -> bool:
        entry = self._store.get(key)
        if entry is None:
            return False
        if nx and entry[0] != float("inf"):
            return False
        self._store[key] = (time.monotonic() + ttl, entry[1])
        return True

    def register_script(self, script: str) -> "_FakeCompareAndDeleteScript":
        return _FakeCompareAndDeleteScript(self)

    async def publish(self, channel: str, message: str) -> int:
        subs = self._channels.get(channel, [])
        for queue in subs:
            queue.put_nowait(message)
        return len(subs)

    def pubsub(self) -> "_FakePubSubSession":
        return _FakePubSubSession(self)


class _FakePubSubSession:
    def __init__(self, redis: _FakeTTLRedis) -> None:
        self._redis = redis
        self._queue: asyncio.Queue = asyncio.Queue()
        self._subscribed: list[str] = []

    async def subscribe(self, channel: str) -> None:
        self._subscribed.append(channel)
        self._redis._channels.setdefault(channel, []).append(self._queue)

    async def get_message(
        self,
        ignore_subscribe_messages: bool = True,
        timeout: float = 1.0,  # noqa: ASYNC109
    ):
        try:
            data = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None
        return {"type": "message", "data": data}

    async def unsubscribe(self) -> None:
        for channel in self._subscribed:
            subs = self._redis._channels.get(channel, [])
            if self._queue in subs:
                subs.remove(self._queue)
        self._subscribed = []

    async def aclose(self) -> None:
        pass


class _FakeCompareAndDeleteScript:
    def __init__(self, redis: _FakeTTLRedis) -> None:
        self._redis = redis

    async def __call__(self, keys: list[str], args: list[str]) -> int:
        if await self._redis.get(keys[0]) != args[0]:
            return 0
        await self._redis.delete(keys[0])
        return 1


def _active_agent_with_key(db_session, *, remote_probe: bool = True):
    """A committed, active agent holding the `remote_probe` grant.

    Committed through a real `SessionLocal()` rather than `db_session`, because
    `link_stream` opens its own connection and would never see the test's
    uncommitted SAVEPOINT — the same reason the twin helper in
    test_ws_agents_link.py exists.
    """
    from cryptography.hazmat.primitives.asymmetric import x25519

    from app.db.models import Agent, AgentCapabilityGrant
    from app.db.session import SessionLocal

    agent_priv = secrets.token_bytes(32)
    pub = x25519.X25519PrivateKey.from_private_bytes(agent_priv).public_key().public_bytes_raw()

    with SessionLocal() as setup_db:
        agent = Agent(
            device_pk=pub.hex(),
            fingerprint=hashlib.sha256(pub).hexdigest()[:32],
            status="active",
            hostname="probe-test-box",
        )
        setup_db.add(agent)
        setup_db.flush()
        setup_db.add(
            AgentCapabilityGrant(agent_id=agent.id, capability="remote_probe", enabled=remote_probe)
        )
        setup_db.commit()
        agent_id = agent.id

    return db_session.get(Agent, agent_id), agent_priv


def _committed_monitor_and_run(agent_id: int, *, deadline_in: float = 30.0):
    """A monitor assigned to *agent_id* plus one dispatched run, committed.

    Returns `(monitor_id, run_id)`. The caller must call `_cleanup` — these rows
    outlive `db_session`'s rollback and `monitor_items.probe_agent_id` is
    RESTRICT, so leaving one behind breaks the conftest agent reaper.
    """
    from app.core.time import utcnow
    from app.db.models import MonitorItem, MonitorProbeRun
    from app.db.session import SessionLocal

    now = utcnow()
    with SessionLocal() as setup_db:
        monitor = MonitorItem(
            name=f"probe-{secrets.token_hex(4)}",
            host="10.0.0.9",
            check_type="icmp",
            params={},
            interval_secs=60,
            max_retries=0,
            last_status="up",
            next_due_at=now + timedelta(seconds=60),
            probe_agent_id=agent_id,
        )
        setup_db.add(monitor)
        setup_db.flush()
        run = MonitorProbeRun(
            monitor_id=monitor.id,
            agent_id=agent_id,
            run_id=secrets.token_hex(16),
            status="dispatched",
            scheduled_at=now,
            dispatched_at=now,
            deadline_at=now + timedelta(seconds=deadline_in),
        )
        setup_db.add(run)
        setup_db.commit()
        return monitor.id, run.run_id


def _cleanup(monitor_id: int) -> None:
    from sqlalchemy import delete

    from app.db.models import MonitorEvent, MonitorItem, MonitorProbeRun, TelemetryTimeseries
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        db.execute(delete(MonitorProbeRun).where(MonitorProbeRun.monitor_id == monitor_id))
        db.execute(delete(MonitorEvent).where(MonitorEvent.item_id == monitor_id))
        db.execute(delete(TelemetryTimeseries).where(TelemetryTimeseries.item_id == monitor_id))
        db.execute(delete(MonitorItem).where(MonitorItem.id == monitor_id))
        db.commit()


def _send_hello(initiator, ws) -> None:
    frame = {
        "v": 1,
        "type": "hello",
        "seq": 0,
        "ts": datetime.now(UTC).isoformat(),
        "payload": {},
    }
    ws.send_bytes(initiator.encrypt(json.dumps(frame).encode()))


def _connect_linked(ws, agent_priv, server_pub):
    initiator = TestNoiseInitiator(agent_priv, server_pub)
    ws.send_bytes(initiator.write_message())
    initiator.read_message(ws.receive_bytes())
    _send_hello(initiator, ws)
    ack = json.loads(initiator.decrypt(ws.receive_bytes()))
    assert ack["type"] == "hello.ack", ack
    assert ack["payload"]["accepted"] is True
    assert json.loads(initiator.decrypt(ws.receive_bytes()))["type"] == "capabilities.set"
    return initiator


def _receive_bytes_with_timeout(ws, timeout: float = 2.0) -> bytes:
    """`ws.receive_bytes()` blocks forever; run it on a worker thread so a real
    delivery bug fails the test instead of hanging the suite."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(ws.receive_bytes)
    try:
        return future.result(timeout=timeout)
    finally:
        pool.shutdown(wait=False)


def _wait_for_run(run_id: str, *, status: str, timeout: float = 5.0):
    """Poll a fresh connection until `link_stream`'s own session has committed."""
    from sqlalchemy import select

    from app.db.models import MonitorProbeRun
    from app.db.session import SessionLocal

    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            last = db.execute(
                select(MonitorProbeRun).where(MonitorProbeRun.run_id == run_id)
            ).scalar_one_or_none()
            if last is not None and last.status == status:
                db.expunge(last)
                return last
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} never reached {status!r} (last: {last and last.status})")


def test_link_delivers_probe_assign_published_by_another_worker(db_session, ws_client, monkeypatch):
    """§2's dispatch hop, end to end. `workers/monitor_probe_dispatch.py` runs
    in its own process and can only reach the agent through
    `agent_registry.publish_agent_control_frame`; calling it directly here
    stands in for that, with `_FakeTTLRedis` playing the one Redis instance the
    two processes would share. `probe.assign` needs no special case in
    `api/ws_agents.py` — the control path is generic over `type` — and this is
    what proves it."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    scheduled_at = datetime.now(UTC)
    deadline_at = scheduled_at + timedelta(seconds=20)

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        # Let link_stream's background control-frame listener subscribe before
        # publishing — plain pub/sub is fire-and-forget.
        time.sleep(0.1)

        published = ws_client.portal.call(
            agent_registry.publish_agent_control_frame,
            agent.id,
            {
                "type": "probe.assign",
                "payload": {
                    "run_id": "a" * 32,
                    "monitor_id": 4242,
                    "check_type": "icmp",
                    "host": "10.0.0.9",
                    "config": {"packet_count": 5},
                    "scheduled_at": scheduled_at.isoformat(),
                    "deadline_at": deadline_at.isoformat(),
                },
            },
        )
        assert published is True

        frame = json.loads(initiator.decrypt(_receive_bytes_with_timeout(ws, timeout=2.0)))

    assert frame["type"] == "probe.assign"
    assert frame["payload"]["run_id"] == "a" * 32
    assert frame["payload"]["config"] == {"packet_count": 5}
    # Go's `time.Time` decoder requires RFC3339: `json.dumps(default=str)` on a
    # raw datetime renders a space separator it rejects outright.
    assert "T" in frame["payload"]["scheduled_at"]
    assert "T" in frame["payload"]["deadline_at"]


def test_link_accepts_a_probe_result_and_completes_the_run(db_session, ws_client, monkeypatch):
    """The return leg, over the genuine encrypted transport: a `probe.result`
    the agent posts is authenticated against its own run, feeds the shared
    result service, and closes the run — with the samples and the transition
    landing in the same commit `link_stream` made."""
    from unittest.mock import AsyncMock

    from app.db.models import MonitorEvent, MonitorItem, TelemetryTimeseries
    from app.db.session import SessionLocal

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))
    # result_service binds `get_redis` at import, so the patch above does not
    # reach its live-status push; point it at the same fake explicitly.
    monkeypatch.setattr(
        "app.services.monitoring.result_service.get_redis", AsyncMock(return_value=fake_redis)
    )

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    monitor_id, run_id = _committed_monitor_and_run(agent.id)

    try:
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            initiator = _connect_linked(ws, agent_priv, server_pub)
            finished_at = datetime.now(UTC)
            payload = {
                "v": 1,
                "type": "probe.result",
                "seq": 1,
                "ts": finished_at.isoformat(),
                "payload": {
                    "run_id": run_id,
                    "monitor_id": monitor_id,
                    "outcome": "completed",
                    "up": False,
                    "started_at": (finished_at - timedelta(seconds=1)).isoformat(),
                    "finished_at": finished_at.isoformat(),
                    "samples": [
                        {"metric": "avail", "value": 0},
                        {"metric": "packet_loss_pct", "value": 100},
                    ],
                    "msg": "100% packet loss (5 probes)",
                },
            }
            ws.send_bytes(initiator.encrypt(json.dumps(payload).encode()))

            run = _wait_for_run(run_id, status="completed")

        assert run.outcome == "completed"
        assert run.msg == "100% packet loss (5 probes)"
        assert run.completed_at is not None

        with SessionLocal() as db:
            item = db.get(MonitorItem, monitor_id)
            assert item.last_status == "down"
            assert item.probe_execution_status == "ready"
            assert item.probe_last_result_at is not None
            assert {
                row.metric
                for row in db.query(TelemetryTimeseries).filter_by(item_id=monitor_id).all()
            } == {"avail", "packet_loss_pct"}
            assert db.query(MonitorEvent).filter_by(item_id=monitor_id).count() == 1
    finally:
        _cleanup(monitor_id)


def _committed_assigned_monitors(agent_id: int, count: int, *, interval_secs: int = 60):
    """`count` enabled monitors assigned to *agent_id*, all due far in the future.

    Committed outside `db_session` for the same reason everything else here is:
    `link_stream` opens its own session and the reconnect UPDATE runs inside it.
    """
    from app.core.time import utcnow
    from app.db.models import MonitorItem
    from app.db.session import SessionLocal

    far_future = utcnow() + timedelta(hours=1)
    ids: list[int] = []
    with SessionLocal() as setup_db:
        for _ in range(count):
            monitor = MonitorItem(
                name=f"probe-{secrets.token_hex(4)}",
                host="10.0.0.9",
                check_type="icmp",
                params={},
                interval_secs=interval_secs,
                max_retries=0,
                last_status="up",
                next_due_at=far_future,
                probe_agent_id=agent_id,
            )
            setup_db.add(monitor)
            setup_db.flush()
            ids.append(monitor.id)
        setup_db.commit()
    return ids


def test_reconnect_makes_assigned_monitors_due_with_jitter_not_all_at_once(
    db_session, ws_client, monkeypatch
):
    """D-16. An agent with hundreds of assignments reconnecting at exactly
    `now()` gets a whole per-vantage batch claimed on the very next tick and
    dispatched into a bounded queue, turning a healthy reconnect into a burst of
    capacity-exhausted execution errors. `next_due_at` therefore lands inside
    `[now, now + least(interval_secs, 30))`, which is the same jitter idiom
    `services/monitoring/scheduler.py` already uses."""
    from unittest.mock import AsyncMock

    from app.db.models import MonitorItem
    from app.db.session import SessionLocal

    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=_FakeTTLRedis()))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    monitor_ids = _committed_assigned_monitors(agent.id, 12)
    disabled_id = _committed_assigned_monitors(agent.id, 1)[0]
    with SessionLocal() as db:
        db.get(MonitorItem, disabled_id).enabled = False
        db.commit()

    try:
        before = datetime.now(UTC)
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            _connect_linked(ws, agent_priv, server_pub)

        # The UPDATE's own `now()` is somewhere in [before, after], so the
        # ceiling has to be measured from the later end or a slow handshake
        # makes this flaky rather than wrong.
        after = datetime.now(UTC)

        with SessionLocal() as db:
            due = {
                m.id: m.next_due_at
                for m in db.query(MonitorItem).filter(MonitorItem.id.in_(monitor_ids)).all()
            }
            # A paused monitor is not woken by its vantage coming back.
            assert db.get(MonitorItem, disabled_id).next_due_at > before + timedelta(minutes=30)

        assert len(due) == len(monitor_ids)
        ceiling = after + timedelta(seconds=30)
        for monitor_id, next_due_at in due.items():
            assert before <= next_due_at < ceiling, (monitor_id, next_due_at)
        # The point of the jitter: not one stampede at `now()`.
        assert len(set(due.values())) > 1
    finally:
        for monitor_id in [*monitor_ids, disabled_id]:
            _cleanup(monitor_id)
