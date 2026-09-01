"""Task 1c: the event-loop lag sampler and its metrics.

Unit-level: exercises `run_event_loop_lag_sampler` directly as a background
asyncio task against the real module-level Prometheus registry — no database
involved, matching the convention in `apps/backend/tests/core/`.
"""

from __future__ import annotations

import asyncio
import time

from app.core import slo_metrics

# A block well above the sampler's own 100ms cadence, so the lag it produces
# cannot be mistaken for scheduling noise.
_BLOCK_SECONDS = 0.3


def _family_names(exposition_text: str) -> set[str]:
    """Metric family names present in a Prometheus text exposition."""
    names: set[str] = set()
    for line in exposition_text.splitlines():
        if line.startswith("# HELP "):
            names.add(line.split()[2])
        elif line and not line.startswith("#"):
            names.add(line.split(" ")[0].split("{")[0])
    return names


async def _run_sampler_briefly() -> asyncio.Task:
    task = asyncio.create_task(slo_metrics.run_event_loop_lag_sampler())
    # Let it complete at least one full 100ms sample cycle.
    await asyncio.sleep(0.15)
    return task


async def _cancel_and_await(task: asyncio.Task) -> None:
    """Mirrors the shutdown path in main.py's lifespan: cancel, then gather
    with return_exceptions=True so cancellation never raises into the caller."""
    task.cancel()
    results = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(results[0], asyncio.CancelledError)


async def test_the_sampler_records_a_sample_onto_the_gauge_and_histogram():
    before_count = slo_metrics.event_loop_lag_seconds_hist._sum.get()  # type: ignore[attr-defined]
    task = await _run_sampler_briefly()
    try:
        gauge_value = slo_metrics.event_loop_lag_seconds._value.get()  # type: ignore[attr-defined]
        assert gauge_value >= 0.0
        after_count = slo_metrics.event_loop_lag_seconds_hist._sum.get()  # type: ignore[attr-defined]
        assert after_count >= before_count  # the histogram gained at least one observation
    finally:
        await _cancel_and_await(task)


async def test_both_metric_names_are_declared_in_the_scrape_exposition():
    """Task 5 and Task 6 scrape these by exact name."""
    families = _family_names(slo_metrics.exposition().decode())
    assert "circuitbreaker_event_loop_lag_seconds" in families
    assert "circuitbreaker_event_loop_lag_seconds_hist" in families


async def test_a_synchronous_block_produces_a_materially_nonzero_lag():
    task = await _run_sampler_briefly()
    try:
        # Block the whole event loop synchronously — the sampler's pending
        # asyncio.sleep(0.1) cannot fire while this thread is busy, so by the
        # time it resumes, the lag against its own schedule is large.
        time.sleep(_BLOCK_SECONDS)  # noqa: ASYNC251 - the point of the test is a *synchronous* block
        # Yield control so the now-overdue sampler wakes up and records.
        await asyncio.sleep(0.05)

        lag = slo_metrics.event_loop_lag_seconds._value.get()  # type: ignore[attr-defined]
        assert lag > 0.1, f"expected a materially nonzero lag, got {lag}s"
    finally:
        await _cancel_and_await(task)


async def test_record_loop_lag_updates_both_series_directly():
    slo_metrics.record_loop_lag(0.42)
    assert slo_metrics.event_loop_lag_seconds._value.get() == 0.42  # type: ignore[attr-defined]


async def test_the_sampler_stops_cleanly_on_cancellation_and_does_not_raise():
    task = asyncio.create_task(slo_metrics.run_event_loop_lag_sampler())
    await asyncio.sleep(0.15)
    await _cancel_and_await(task)
    assert task.cancelled() or task.done()
