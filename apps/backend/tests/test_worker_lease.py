"""SRV-02/SRV-04: the timer-shaped workers run on one process, and hand off.

Not every worker loop is a queue consumer. The telemetry collector and the
integration sync are timers — "every N seconds, find what is due and do it" —
and a second instance of a timer does not share the work, it repeats it: every
monitored device polled twice, every integration synced twice against the
remote system it calls. The mono image runs the API with `uvicorn --workers 2`,
so a second instance is not hypothetical.

These tests run the real worker loops against the real PostgreSQL lease.
"""

from __future__ import annotations

import asyncio

import pytest

from app.workers import SingleActiveLease


@pytest.fixture
def lease_name(request):
    return f"test_{request.node.name}"


def test_only_one_holder_at_a_time(lease_name):
    first = SingleActiveLease(lease_name)
    second = SingleActiveLease(lease_name)
    try:
        assert first.try_acquire() is True
        assert second.try_acquire() is False
        assert first.try_acquire() is True, "re-acquiring an already-held lease must be a no-op"
    finally:
        first.release()
        second.release()


def test_the_lease_hands_off_to_the_standby(lease_name):
    """The rolling-restart case: the replacement is already running and idle,
    and picks the work up on its next tick rather than the work stopping."""
    departing = SingleActiveLease(lease_name)
    standby = SingleActiveLease(lease_name)
    try:
        assert departing.try_acquire() is True
        assert standby.try_acquire() is False

        departing.release()

        assert standby.try_acquire() is True
    finally:
        departing.release()
        standby.release()


def test_release_is_safe_before_anything_was_acquired(lease_name):
    SingleActiveLease(lease_name).release()


async def _run_briefly(coro_factory, stop_event: asyncio.Event) -> None:
    task = asyncio.create_task(coro_factory())
    await asyncio.sleep(0.4)
    stop_event.set()
    await asyncio.wait_for(task, timeout=30)


async def test_the_telemetry_collector_does_not_poll_without_the_lease(monkeypatch):
    """Two collectors would poll every monitored device twice — load on the
    devices being watched, and duplicate samples in the series they feed."""
    from app.workers import telemetry_collector

    collected: list[int] = []

    async def _record(**_kwargs):
        collected.append(1)

    monkeypatch.setattr(telemetry_collector, "collect_once", _record)
    monkeypatch.setattr(telemetry_collector, "_init_vault", lambda: None)

    holder = SingleActiveLease("telemetry_collector")
    assert holder.try_acquire()
    try:
        stop = asyncio.Event()
        await _run_briefly(lambda: telemetry_collector.run_worker(stop), stop)
        assert collected == [], "collected while another instance held the lease"
    finally:
        holder.release()

    # With the lease free, the same loop does its work.
    stop = asyncio.Event()
    await _run_briefly(lambda: telemetry_collector.run_worker(stop), stop)
    assert collected == [1]


async def test_the_integration_worker_does_not_sync_without_the_lease(monkeypatch):
    """Two integration workers would call the remote system twice per interval
    and write its result twice."""
    from app.workers import integration_worker

    synced: list[int] = []

    async def _record():
        synced.append(1)

    monkeypatch.setattr(integration_worker, "_sync_due_integrations", _record)

    holder = SingleActiveLease("integration_sync")
    assert holder.try_acquire()
    try:
        stop = asyncio.Event()
        await _run_briefly(lambda: integration_worker.run_integration_worker(stop), stop)
        assert synced == [], "synced while another instance held the lease"
    finally:
        holder.release()

    stop = asyncio.Event()
    await _run_briefly(lambda: integration_worker.run_integration_worker(stop), stop)
    assert synced == [1]


async def test_the_worker_releases_its_lease_on_shutdown(monkeypatch):
    """SRV-04: the drain must let go, or the replacement process stands by
    forever and the function silently stops running."""
    from app.workers import integration_worker

    async def _noop():
        return None

    monkeypatch.setattr(integration_worker, "_sync_due_integrations", _noop)

    stop = asyncio.Event()
    await _run_briefly(lambda: integration_worker.run_integration_worker(stop), stop)

    successor = SingleActiveLease("integration_sync")
    try:
        assert successor.try_acquire() is True, "the lease outlived the worker that held it"
    finally:
        successor.release()
