"""REL-07 — the classification/throttle/metric primitive itself.

`app.services.stream_faults` is what replaced the broad `except Exception: pass`
handlers in the listeners and streams. Three properties matter and are pinned
here: a fault is put in a stable class, a storm of identical faults produces a
bounded number of log lines *without* losing the count, and every occurrence —
logged or suppressed — increments a counter.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app.services import stream_faults


@pytest.fixture(autouse=True)
def _clean_counters():
    stream_faults.reset_stream_faults()
    yield
    stream_faults.reset_stream_faults()


class _FakeWebSocketDisconnect(Exception):
    """Starlette's WebSocketDisconnect is matched by name, not by import."""


_FakeWebSocketDisconnect.__name__ = "WebSocketDisconnect"


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ConnectionResetError("reset"), stream_faults.FAULT_PEER_GONE),
        (BrokenPipeError("pipe"), stream_faults.FAULT_PEER_GONE),
        (TimeoutError("slow"), stream_faults.FAULT_TIMEOUT),
        (ConnectionRefusedError("no redis"), stream_faults.FAULT_TRANSPORT),
        (json.JSONDecodeError("bad", "{", 0), stream_faults.FAULT_DECODE),
        (KeyError("ts"), stream_faults.FAULT_DECODE),
        (RuntimeError("boom"), stream_faults.FAULT_UNEXPECTED),
    ],
)
def test_classify_fault_puts_each_failure_in_its_own_class(exc, expected):
    assert stream_faults.classify_fault(exc) == expected


def test_attribute_error_is_unexpected_not_decode():
    """`None.something` on a frame is our bug, not a malformed peer message —
    it has to reach an operator as an unexpected fault with a traceback."""
    assert stream_faults.classify_fault(AttributeError("x")) == stream_faults.FAULT_UNEXPECTED


def test_record_stream_fault_counts_every_occurrence(caplog):
    for _ in range(50):
        stream_faults.record_stream_fault("unit.listener", ConnectionRefusedError("down"))

    counts = stream_faults.stream_fault_counts()
    assert counts["unit.listener/transport"] == 50


def test_record_stream_fault_throttles_the_log_but_not_the_count(caplog):
    """A dependency outage drives an identical fault thousands of times. The
    log must stay readable; the counter must stay exact."""
    logger = logging.getLogger("test_rel07_throttle")
    with caplog.at_level(logging.DEBUG, logger="test_rel07_throttle"):
        for _ in range(500):
            stream_faults.record_stream_fault(
                "unit.storm", ConnectionRefusedError("down"), logger=logger
            )

    emitted = [r for r in caplog.records if r.name == "test_rel07_throttle"]
    assert 0 < len(emitted) <= 5, f"log storm: {len(emitted)} lines for 500 faults"
    assert stream_faults.stream_fault_counts()["unit.storm/transport"] == 500


def test_suppressed_faults_are_reported_on_the_next_line(caplog, monkeypatch):
    """Nothing is dropped quietly: the first line after a throttled burst says
    how many occurrences it stands for."""
    logger = logging.getLogger("test_rel07_suppressed")
    clock = {"now": 1000.0}
    monkeypatch.setattr(stream_faults.time, "monotonic", lambda: clock["now"])

    with caplog.at_level(logging.DEBUG, logger="test_rel07_suppressed"):
        for _ in range(20):
            stream_faults.record_stream_fault(
                "unit.suppressed", ConnectionRefusedError("down"), logger=logger
            )
        # Far enough ahead that the bucket has refilled.
        clock["now"] += stream_faults._LOG_INTERVAL_S * 2
        stream_faults.record_stream_fault(
            "unit.suppressed", ConnectionRefusedError("down"), logger=logger
        )

    messages = [r.getMessage() for r in caplog.records if r.name == "test_rel07_suppressed"]
    assert any("suppressed=" in m for m in messages), messages
    assert stream_faults.stream_fault_counts()["unit.suppressed/transport"] == 21


def test_context_is_sanitised_into_the_log_line(caplog):
    """Listener context is attacker-influenced (peer names, channel payloads):
    it must not be able to forge a second log record."""
    logger = logging.getLogger("test_rel07_context")
    with caplog.at_level(logging.DEBUG, logger="test_rel07_context"):
        stream_faults.record_stream_fault(
            "unit.context",
            ConnectionRefusedError("down"),
            logger=logger,
            context={"name": "evil\nINFO forged log line"},
        )
    message = caplog.records[-1].getMessage()
    assert "\n" not in message
    assert "forged log line" in message


def test_unexpected_faults_are_logged_at_error_with_a_traceback(caplog):
    logger = logging.getLogger("test_rel07_unexpected")
    with caplog.at_level(logging.DEBUG, logger="test_rel07_unexpected"):
        stream_faults.record_stream_fault("unit.bug", RuntimeError("boom"), logger=logger)
    record = caplog.records[-1]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


def test_peer_disconnects_stay_at_debug(caplog):
    """A client hanging up is routine; it must not page anyone."""
    logger = logging.getLogger("test_rel07_peer")
    with caplog.at_level(logging.DEBUG, logger="test_rel07_peer"):
        stream_faults.record_stream_fault("unit.peer", ConnectionResetError(), logger=logger)
    assert caplog.records[-1].levelno == logging.DEBUG


async def test_close_stream_socket_swallows_a_failing_close_and_counts_it():
    class _Broken:
        client_state = None

        async def close(self, code: int) -> None:
            raise RuntimeError("already closed")

    await stream_faults.close_stream_socket(_Broken(), component="unit.sock", code=1011)
    assert stream_faults.stream_fault_counts()["unit.sock.close/peer_gone"] == 1


async def test_close_stream_socket_closes_a_live_socket():
    closed: list[int] = []

    class _Live:
        client_state = None

        async def close(self, code: int) -> None:
            closed.append(code)

    await stream_faults.close_stream_socket(_Live(), component="unit.sock", code=1011)
    assert closed == [1011]
    assert stream_faults.stream_fault_counts() == {}


async def test_concurrent_recorders_do_not_lose_counts():
    """The throttle and the counter are shared mutable state reached from every
    listener task at once."""

    async def _burst() -> None:
        for _ in range(100):
            stream_faults.record_stream_fault("unit.race", ConnectionRefusedError("down"))
            await asyncio.sleep(0)

    await asyncio.gather(*(_burst() for _ in range(8)))
    assert stream_faults.stream_fault_counts()["unit.race/transport"] == 800


def test_the_fault_counter_reaches_the_metrics_endpoint():
    """A counter nothing exposes is not a metric. These land on the
    process-lifetime registry `/api/v1/metrics` already appends."""
    from app.core import slo_metrics

    stream_faults.record_stream_fault("unit.exposed", ConnectionRefusedError("down"))
    exposition = slo_metrics.exposition().decode()

    assert "circuitbreaker_stream_faults_total" in exposition
    assert 'component="unit.exposed"' in exposition
    assert 'fault="transport"' in exposition
