"""REL-07 — what the listeners and streams actually do when something fails.

Every test here fails against the pre-REL-07 handlers. The bugs those handlers
hid, in the order the tests appear:

* a single malformed pub/sub payload broke the forward loop, silently ending
  telemetry and monitor delivery for a connected client;
* a lost Redis subscription left the WebSocket open, pinging, and permanently
  empty instead of closing so the client could reconnect;
* an unparseable NATS frame was forwarded to the browser as an empty but
  well-formed event;
* one unserializable audit row wedged the log stream forever, because the
  cursor never advanced past it;
* the SSDP socket was leaked on every listener stop, along with its multicast
  membership;
* a NATS publish failure in the discovery listener was a bare `pass`.
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import stream_faults


@pytest.fixture(autouse=True)
def _clean_counters():
    stream_faults.reset_stream_faults()
    yield
    stream_faults.reset_stream_faults()


class _FakePubSub:
    """Yields a scripted list of pub/sub messages, then idles like real redis-py."""

    def __init__(self, messages: list[object], *, subscribe_error: Exception | None = None):
        self._messages = list(messages)
        self._subscribe_error = subscribe_error
        self.subscribed: list[str] = []
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        if self._subscribe_error is not None:
            raise self._subscribe_error
        self.subscribed.extend(channels)

    async def get_message(
        self,
        ignore_subscribe_messages: bool = True,
        timeout: float = 1.0,  # noqa: ASYNC109 - mirrors redis-py's own signature
    ):
        if self._messages:
            return self._messages.pop(0)
        await asyncio.sleep(timeout)
        return None

    async def unsubscribe(self, *channels: str) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


class _FakeRedis:
    def __init__(self, pubsub: _FakePubSub):
        self._pubsub = pubsub

    def pubsub(self) -> _FakePubSub:
        return self._pubsub


class _FakeSocket:
    """Records what a WebSocket handler sent and how it was closed."""

    def __init__(self):
        self.sent: list[str] = []
        self.close_code: int | None = None
        self.client_state = None
        self.application_state = None

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code


def _resolved(value):
    async def _get():
        return value

    return _get


def _message(payload: str) -> dict:
    return {"type": "message", "data": payload}


async def _run_briefly(coro, seconds: float = 0.3) -> None:
    """Drive a never-ending listener for long enough to observe it, then stop it."""
    task = asyncio.create_task(coro)
    await asyncio.sleep(seconds)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# ── Malformed payloads must not end the stream ───────────────────────────────


@pytest.mark.parametrize("module_name", ["ws_telemetry", "ws_monitors"])
async def test_one_malformed_payload_does_not_kill_the_forward_loop(monkeypatch, module_name):
    """The decode and the send used to share one handler that broke the loop
    for both, so any publisher shipping one bad frame silently ended delivery
    for every client connected at that moment."""
    import importlib

    module = importlib.import_module(f"app.api.{module_name}")

    pubsub = _FakePubSub([_message("{not json"), _message(json.dumps({"monitor_id": 7, "v": 1}))])
    monkeypatch.setattr(module, "get_redis", _resolved(_FakeRedis(pubsub)))

    ws = _FakeSocket()
    from starlette.websockets import WebSocketState

    ws.application_state = WebSocketState.CONNECTED
    stop = asyncio.Event()
    await _run_briefly(module._redis_listener(ws, {"chan"}, stop))

    assert len(ws.sent) == 1, "the good message after the malformed one was never forwarded"
    assert json.loads(ws.sent[0])["v"] == 1
    counts = stream_faults.stream_fault_counts()
    assert counts.get(f"{module_name}.decode/decode") == 1
    assert not any(key.endswith(".forward/peer_gone") for key in counts)


# ── A lost subscription must close the socket, not go quiet ──────────────────


async def test_discovery_stream_closes_when_its_subscription_dies(monkeypatch):
    import app.core.redis as core_redis
    from app.api import ws_discovery

    pubsub = _FakePubSub([], subscribe_error=ConnectionRefusedError("redis gone"))
    monkeypatch.setattr(core_redis, "get_redis", _resolved(_FakeRedis(pubsub)))

    ws = _FakeSocket()
    from starlette.websockets import WebSocketState

    ws.application_state = WebSocketState.CONNECTED
    await ws_discovery._redis_discovery_listener(ws, asyncio.Event())

    assert ws.close_code == 1011, "the socket was left open with no delivery path"
    assert stream_faults.stream_fault_counts()["ws_discovery.subscribe/transport"] == 1


async def test_agent_presence_stream_closes_when_its_subscription_dies(monkeypatch):
    import app.core.redis as core_redis
    from app.api import ws_agents

    pubsub = _FakePubSub([], subscribe_error=ConnectionRefusedError("redis gone"))
    monkeypatch.setattr(core_redis, "get_redis", _resolved(_FakeRedis(pubsub)))

    ws = _FakeSocket()
    from starlette.websockets import WebSocketState

    ws.application_state = WebSocketState.CONNECTED
    await ws_agents._redis_agent_listener(ws, asyncio.Event())

    assert ws.close_code == 1011
    assert stream_faults.stream_fault_counts()["ws_agents.presence.subscribe/transport"] == 1


# ── An unparseable NATS frame must be dropped, not forwarded as {} ───────────


def test_unparseable_nats_event_is_dropped_not_forwarded_as_empty():
    from app.api.events import decode_nats_event

    assert decode_nats_event(SimpleNamespace(data=b"{not json", subject="alert")) is None
    assert decode_nats_event(SimpleNamespace(data=b"[1, 2, 3]", subject="alert")) is None
    assert decode_nats_event(SimpleNamespace(data=b'{"id": 4}', subject="alert")) == {"id": 4}
    assert stream_faults.stream_fault_counts()["sse_events.decode/decode"] == 2


# ── One bad row must not wedge the audit log stream ──────────────────────────


async def test_one_unrenderable_row_does_not_wedge_the_log_stream(monkeypatch):
    """The cursor used to stay behind the failing row, so every subsequent poll
    re-read it, failed again, and the stream never advanced."""
    from app.api import logs

    base = datetime.now(UTC)
    bad = SimpleNamespace(id=1, timestamp=base)
    good = SimpleNamespace(id=2, timestamp=base + timedelta(seconds=1))
    later = SimpleNamespace(id=3, timestamp=base + timedelta(seconds=2))
    fetches: list[object] = []

    def _fetch(last_dt):
        fetches.append(last_dt)
        if len(fetches) == 1:
            return ([bad, good], {})
        if len(fetches) == 2:
            return ([later], {})
        return ([], {})

    def _render(row, _cache):
        if row is bad:
            raise ValueError("row 1 is not serializable")
        return f"data: {row.id}\n\n"

    monkeypatch.setattr(logs, "_fetch_stream_batch", _fetch)
    monkeypatch.setattr(logs, "_stream_payload", _render)
    monkeypatch.setattr(logs, "_STREAM_POLL_SECONDS", 0.01)

    response = await logs.stream_logs(since=None)
    iterator = response.body_iterator
    # frames[0] is the connect keepalive; then "data: 2" (the healthy row of the
    # first batch) and "data: 3" (proof the second poll started past the bad row).
    frames = [await asyncio.wait_for(iterator.__anext__(), timeout=5) for _ in range(3)]
    await iterator.aclose()

    assert "data: 2\n\n" in frames, "the healthy row after the bad one was never sent"
    assert "data: 3\n\n" in frames
    assert fetches[1] == good.timestamp, "cursor did not advance past the unrenderable row"
    assert stream_faults.stream_fault_counts()["sse_logs.render/decode"] == 1


# ── The SSDP listener must not leak its socket ───────────────────────────────


async def test_ssdp_listener_closes_its_socket_on_every_exit(monkeypatch):
    from app.services.listener_service import ListenerService

    class _Sock:
        def __init__(self):
            self.closed = False

        def close(self) -> None:
            self.closed = True

    service = ListenerService()
    sock = _Sock()
    monkeypatch.setattr(service, "_open_ssdp_socket", lambda: sock)
    monkeypatch.setattr(service, "_send_msearch", lambda: None)

    async def _boom(_sock):
        raise OSError("interface went away")

    monkeypatch.setattr(service, "_ssdp_recv_loop", _boom)
    await service._run_ssdp()

    assert sock.closed, "the multicast socket and its group membership were leaked"
    assert service.ssdp_active is False
    assert stream_faults.stream_fault_counts()["discovery_listener.ssdp/transport"] == 1


async def test_ssdp_recv_loop_gives_up_on_a_permanently_broken_socket(monkeypatch):
    """A read error used to mean a 1s sleep and another try, forever, at DEBUG."""
    from app.services import listener_service as ls

    service = ls.ListenerService()
    service.is_running = True
    monkeypatch.setattr(ls, "_SSDP_RECV_ERROR_BACKOFF_S", 0.0)

    class _Loop:
        async def sock_recvfrom(self, _sock, _size):
            raise OSError("bad file descriptor")

    monkeypatch.setattr(ls.asyncio, "get_running_loop", lambda: _Loop())
    await asyncio.wait_for(service._ssdp_recv_loop(object()), timeout=5)

    counts = stream_faults.stream_fault_counts()
    assert counts["discovery_listener.ssdp_recv/transport"] == ls._SSDP_MAX_CONSECUTIVE_ERRORS


# ── A dropped discovery event must not vanish silently ───────────────────────


async def test_listener_event_nats_publish_failure_is_recorded(monkeypatch):
    from app.services import listener_service as ls

    class _Db:
        def query(self, *_a, **_kw):
            return self

        def filter(self, *_a, **_kw):
            return self

        def first(self):
            return None

        def add(self, _obj):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    async def _publish(*_a, **_kw):
        raise ConnectionRefusedError("nats down")

    monkeypatch.setattr(ls, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(ls.nats_client, "publish", _publish)

    service = ls.ListenerService()
    await service._record_event(
        source="ssdp",
        service_type="upnp:rootdevice",
        name="printer",
        ip_address="10.0.0.5",
        port=None,
        properties={},
    )

    assert stream_faults.stream_fault_counts()["discovery_listener.publish/transport"] == 1


# ── One unserializable monitor must not mute the rest of the batch ───────────


async def test_one_unserializable_entry_does_not_drop_the_rest_of_live_status(monkeypatch):
    """`json.dumps` and `redis.publish` shared a handler that `return`ed, so
    one bad entry silently cancelled the live status of every monitor behind it
    in the batch."""
    from app.services.monitoring import result_service

    published: list[str] = []

    class _Redis:
        async def publish(self, channel: str, payload: str) -> None:
            published.append(channel)

    monkeypatch.setattr(result_service, "get_redis", _resolved(_Redis()))

    await result_service._publish_live_status(
        [
            {"monitor_id": 1, "status": "up"},
            {"monitor_id": 2, "status": object()},  # not JSON-serializable
            {"monitor_id": 3, "status": "down"},
        ]
    )

    assert published == ["monitor:1", "monitor:3"]
    assert stream_faults.stream_fault_counts()["monitor_results.live_encode/decode"] == 1


async def test_live_status_publish_outage_stops_the_batch_but_is_recorded(monkeypatch):
    from app.services.monitoring import result_service

    class _Redis:
        async def publish(self, channel: str, payload: str) -> None:
            raise ConnectionRefusedError("redis gone")

    monkeypatch.setattr(result_service, "get_redis", _resolved(_Redis()))

    await result_service._publish_live_status(
        [{"monitor_id": 1, "status": "up"}, {"monitor_id": 2, "status": "up"}]
    )

    assert stream_faults.stream_fault_counts()["monitor_results.live_publish/transport"] == 1


# ── The discovery review badge must actually get its event ───────────────────


async def test_result_processed_event_is_emitted_from_a_threadpool_caller(monkeypatch):
    """`POST /discovery/results/{id}/merge` is a synchronous `def` route, so
    FastAPI runs it on a worker thread — where `asyncio.get_event_loop()` raises
    `RuntimeError: There is no current event loop in thread ...`. The old code
    called exactly that inside a broad handler that logged at DEBUG, so no
    accept or reject ever emitted its `result_processed` frame and the review
    badge's `pending_count` drifted with no way to recover."""
    from app.services import discovery_merge, discovery_scheduler

    emitted: list[tuple[int, str]] = []

    async def _fake_emit(_db, result_id: int, status: str) -> None:
        emitted.append((result_id, status))

    monkeypatch.setattr(discovery_merge, "_emit_result_processed_event", _fake_emit)
    monkeypatch.setattr(discovery_scheduler, "_main_loop", asyncio.get_running_loop())

    await asyncio.to_thread(discovery_merge.schedule_result_processed_event, 4242, "accept")
    for _ in range(50):
        if emitted:
            break
        await asyncio.sleep(0.02)

    assert emitted == [(4242, "accept")], "the review badge event never reached the loop"


async def test_result_processed_event_is_not_abandoned_when_no_loop_exists(monkeypatch, caplog):
    """With nothing to schedule on, the coroutine must be closed rather than
    left for the garbage collector to report as never awaited (REL-08)."""
    import warnings

    from app.services import discovery_merge, discovery_scheduler

    monkeypatch.setattr(discovery_scheduler, "_main_loop", None)

    def _call_from_a_loopless_thread() -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            discovery_merge.schedule_result_processed_event(7, "reject")
            gc.collect()

    with caplog.at_level(logging.WARNING, logger="app.services.discovery_merge"):
        await asyncio.to_thread(_call_from_a_loopless_thread)

    assert any("result_processed" in r.getMessage() for r in caplog.records)
