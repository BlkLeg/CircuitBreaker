"""The Proxmox poll jobs, testable for the first time.

These five were closures nested inside `main.py`'s lifespan (route F9). Nothing
could import them, so nothing could test them — the only way to reach the
timeout guard below was to boot the app and wait. That is why the guard is what
these tests are mostly about: it is the behaviour most likely to be wrong and
was the least observable.

Each job wraps its work in `asyncio.timeout` and swallows `TimeoutError` with a
warning, deliberately. A poll that overruns must skip its cycle rather than
stack up behind the next one — APScheduler is configured `max_instances=1`, so a
hung poll would otherwise block every later run of the same job silently.
"""

from __future__ import annotations

import asyncio

import pytest

from app.jobs import proxmox as jobs


@pytest.mark.asyncio
async def test_a_timing_out_poll_is_swallowed_so_the_next_cycle_still_runs(
    monkeypatch, caplog
) -> None:
    """The guard that could not previously be reached from a test."""

    async def _hang(_db):
        await asyncio.sleep(3600)

    monkeypatch.setattr(jobs, "poll_node_telemetry", _hang)
    monkeypatch.setattr(jobs, "NODE_POLL_TIMEOUT_S", 0.01)

    # Must not raise: a raising job marks the APScheduler run as errored and
    # tells the operator a poll crashed when it merely ran long.
    await jobs.proxmox_node_poll()

    assert any("timed out" in record.message for record in caplog.records), (
        "a skipped cycle must say so — silently swallowing the timeout would "
        "make a permanently-hanging Proxmox host indistinguishable from a "
        "healthy idle one"
    )


@pytest.mark.asyncio
async def test_a_successful_poll_records_health_for_every_config(monkeypatch) -> None:
    recorded: list[dict] = []

    async def _poll(_db):
        return {7: None, 9: RuntimeError("unreachable")}

    monkeypatch.setattr(jobs, "poll_node_telemetry", _poll)
    monkeypatch.setattr(jobs, "record_poll_health", lambda outcomes: recorded.append(outcomes))

    await jobs.proxmox_node_poll()

    assert recorded == [{7: None, 9: recorded[0][9]}]
    assert isinstance(recorded[0][9], RuntimeError), (
        "the per-config exception must survive to the health writer, or a failing "
        "node shows as healthy"
    )


@pytest.mark.asyncio
async def test_full_sync_records_a_failure_per_config_and_keeps_going(monkeypatch) -> None:
    """One broken Proxmox host must not stop the others syncing.

    The loop catches per config precisely so a single unreachable cluster does
    not abort the sweep — the same shape as the batch-vs-message distinction in
    the JetStream workers.
    """
    healths: list[tuple[int, bool]] = []

    class _Cfg:
        def __init__(self, cid: int) -> None:
            self.id = cid
            self.auto_sync = True

    async def _import(_db, cfg, queue_for_review=False):
        if cfg.id == 2:
            raise RuntimeError("cluster unreachable")
        return {"ok": True, "errors": []}

    monkeypatch.setattr(jobs, "list_integrations", lambda _db: [_Cfg(1), _Cfg(2), _Cfg(3)])
    monkeypatch.setattr(jobs, "discover_and_import", _import)
    monkeypatch.setattr(
        jobs,
        "record_sync_health",
        lambda cid, result=None, exc=None: healths.append((cid, exc is None)),
    )

    await jobs.proxmox_full_sync()

    assert healths == [(1, True), (2, False), (3, True)], (
        "config 3 was never synced — one unreachable cluster aborted the sweep"
    )


@pytest.mark.asyncio
async def test_a_config_with_auto_sync_off_is_skipped(monkeypatch) -> None:
    seen: list[int] = []

    class _Cfg:
        def __init__(self, cid: int, auto: bool) -> None:
            self.id = cid
            self.auto_sync = auto

    async def _import(_db, cfg, queue_for_review=False):
        seen.append(cfg.id)
        return {"ok": True, "errors": []}

    monkeypatch.setattr(jobs, "list_integrations", lambda _db: [_Cfg(1, True), _Cfg(2, False)])
    monkeypatch.setattr(jobs, "discover_and_import", _import)
    monkeypatch.setattr(jobs, "record_sync_health", lambda *a, **k: None)

    await jobs.proxmox_full_sync()

    assert seen == [1], "auto_sync=False must not be synced"
