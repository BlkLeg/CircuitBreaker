# apps/backend/tests/services/test_worker_stream_limits.py
"""B15: the TELEMETRY and DISCOVERY JetStream streams must be bounded.

Both worker streams were declared with nothing but a name and a subject list.  A
JetStream stream created that way is LimitsPolicy with `max_msgs`, `max_bytes` and
`max_age` all unset, which means "keep every message forever" — acking a telemetry
sample does not delete it.  `telemetry_collector` publishes one message per device per
poll cycle, so the NATS volume grew without bound until the disk filled and every
publisher on the box started failing at once.  `MONITOR_POLL` and `MONITOR_PROBE`
already get this right in `core/nats_client.py`; these tests pin the same treatment
onto the two worker-owned streams.

The retrofit half matters as much as the creation half: `add_stream` against a stream
that already exists with a different config fails with "stream name already in use",
which both workers swallowed, so an upgraded deployment would have kept its limitless
stream forever.  The fix has to reach back and update it — and must do so without
changing the retention policy, because JetStream rejects an update that does.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

from nats.js.api import RetentionPolicy


class _FakeJetStream:
    """Records stream declarations the way `test_monitor_probe_stream.py` does."""

    def __init__(self, add_error: str | None = None, existing_retention: Any = None) -> None:
        self.added: list[dict] = []
        self.updated: list[dict] = []
        self.subscribed: list[tuple[str, dict]] = []
        self._add_error = add_error
        self._existing_retention = existing_retention

    async def add_stream(self, **kwargs: Any) -> Any:
        self.added.append(kwargs)
        if self._add_error:
            raise Exception(self._add_error)
        return object()

    async def stream_info(self, name: str) -> Any:
        return SimpleNamespace(config=SimpleNamespace(retention=self._existing_retention))

    async def update_stream(self, **kwargs: Any) -> Any:
        self.updated.append(kwargs)
        return object()

    async def subscribe(self, subject: str, **kwargs: Any) -> Any:
        self.subscribed.append((subject, kwargs))
        return object()


def _fake_nats_client(js: _FakeJetStream) -> Any:
    return SimpleNamespace(is_connected=True, _nc=SimpleNamespace(jetstream=lambda: js))


# ── TELEMETRY ─────────────────────────────────────────────────────────────────


def _ensure_telemetry(monkeypatch: Any, js: _FakeJetStream) -> None:
    from app.workers import telemetry_ingest_worker

    monkeypatch.setattr(telemetry_ingest_worker, "nats_client", _fake_nats_client(js))
    asyncio.run(telemetry_ingest_worker._ensure_stream())


def test_the_telemetry_stream_is_created_as_a_bounded_work_queue(monkeypatch):
    js = _FakeJetStream()
    _ensure_telemetry(monkeypatch, js)

    assert len(js.added) == 1
    decl = js.added[0]
    assert decl["name"] == "TELEMETRY"
    assert decl["subjects"] == ["telemetry.ingest.>"]
    # The ingest loop acks every message it writes, so acked samples must be deleted
    # rather than retained — exactly what MONITOR_POLL does.
    assert decl["retention"] == RetentionPolicy.WORK_QUEUE
    # And a backlog accumulated while the ingest worker is down must still expire.
    assert decl["max_age"] == 3600
    assert decl["max_bytes"] == 256 * 1024 * 1024


def test_the_telemetry_stream_limits_are_env_tunable(monkeypatch):
    monkeypatch.setenv("CB_TELEMETRY_STREAM_MAX_AGE_S", "120")
    monkeypatch.setenv("CB_TELEMETRY_STREAM_MAX_BYTES", "4096")
    js = _FakeJetStream()
    _ensure_telemetry(monkeypatch, js)

    assert js.added[0]["max_age"] == 120
    assert js.added[0]["max_bytes"] == 4096


def test_an_already_deployed_limitless_telemetry_stream_is_bounded_in_place(monkeypatch):
    """The "already in use" branch must retro-fit limits, not shrug at debug level."""
    js = _FakeJetStream(
        add_error="nats: stream name already in use",
        existing_retention=RetentionPolicy.LIMITS,
    )
    _ensure_telemetry(monkeypatch, js)

    assert len(js.updated) == 1, "an existing TELEMETRY stream was left unbounded"
    upd = js.updated[0]
    assert upd["name"] == "TELEMETRY"
    assert upd["subjects"] == ["telemetry.ingest.>"]
    assert upd["max_age"] == 3600
    assert upd["max_bytes"] == 256 * 1024 * 1024
    # JetStream rejects a stream update that changes retention, and rejects the whole
    # request when it sees one — sending WorkQueuePolicy here would throw the limits
    # away with it, which is the one outcome this test exists to prevent.
    assert upd["retention"] == RetentionPolicy.LIMITS


def test_a_failing_telemetry_retrofit_is_logged_rather_than_raised(monkeypatch):
    js = _FakeJetStream(add_error="nats: stream name already in use")

    async def _boom(**kwargs: Any) -> Any:
        raise Exception("update rejected")

    js.update_stream = _boom  # type: ignore[method-assign]

    _ensure_telemetry(monkeypatch, js)  # must not raise


def test_ensuring_the_telemetry_stream_is_a_no_op_while_nats_is_down(monkeypatch):
    from app.workers import telemetry_ingest_worker

    js = _FakeJetStream()
    client = _fake_nats_client(js)
    client.is_connected = False
    monkeypatch.setattr(telemetry_ingest_worker, "nats_client", client)

    asyncio.run(telemetry_ingest_worker._ensure_stream())

    assert js.added == []


# ── DISCOVERY ─────────────────────────────────────────────────────────────────


def _setup_discovery(monkeypatch: Any, js: _FakeJetStream) -> bool:
    from app.workers import discovery

    monkeypatch.setattr(discovery, "nats_client", _fake_nats_client(js))
    return asyncio.run(discovery._setup_jetstream(asyncio.Semaphore(1)))


def test_the_discovery_stream_is_created_as_a_bounded_work_queue(monkeypatch):
    js = _FakeJetStream()
    assert _setup_discovery(monkeypatch, js) is True

    assert len(js.added) == 1
    decl = js.added[0]
    assert decl["name"] == "DISCOVERY"
    assert decl["subjects"] == ["discovery.jobs"]
    # `process_job` acks on success and naks on failure, so a work queue is right here
    # too: a finished scan job has no reason to stay on disk.
    assert decl["retention"] == RetentionPolicy.WORK_QUEUE
    assert decl["max_age"] == 3600
    assert decl["max_bytes"] == 64 * 1024 * 1024
    # The queue group is what makes the work queue legal: nats-py turns `queue` into the
    # durable name, so every replica shares one consumer rather than each adding its own.
    assert len(js.subscribed) == 1
    subject, kwargs = js.subscribed[0]
    assert subject == "discovery.jobs"
    assert kwargs["queue"] == "discovery_workers"


def test_an_already_deployed_limitless_discovery_stream_is_bounded_in_place(monkeypatch):
    js = _FakeJetStream(
        add_error="nats: stream name already in use",
        existing_retention=RetentionPolicy.LIMITS,
    )
    assert _setup_discovery(monkeypatch, js) is True

    assert len(js.updated) == 1, "an existing DISCOVERY stream was left unbounded"
    upd = js.updated[0]
    assert upd["name"] == "DISCOVERY"
    assert upd["max_age"] == 3600
    assert upd["retention"] == RetentionPolicy.LIMITS
