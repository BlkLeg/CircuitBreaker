"""`monitor_service._publish_soon` — the fire-and-forget seam the discovery
bootstrap and every cancellation publisher share.

The contract these tests pin is the one a bare `loop.create_task` does not
give: the scheduled coroutine actually runs to completion even though the
caller keeps no reference to it, the reference is released once it finishes,
and an exception it raises is logged rather than lost.
"""

from __future__ import annotations

import asyncio
import gc
import logging

import pytest

from app.services import monitor_service


def test_returns_false_and_schedules_nothing_without_a_running_loop(caplog):
    created: list[str] = []

    async def _never() -> None:  # pragma: no cover - must not be constructed
        created.append("ran")

    def factory():
        created.append("constructed")
        return _never()

    with caplog.at_level(logging.WARNING, logger=monitor_service.logger.name):
        assert monitor_service._publish_soon("nothing", factory) is False

    assert created == []
    assert "No running async loop to publish nothing." in caplog.text


@pytest.mark.asyncio
async def test_the_task_is_held_until_it_finishes_and_then_released():
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def _work() -> None:
        started.set()
        await release.wait()
        finished.set()

    assert monitor_service._publish_soon("held", _work) is True
    await asyncio.wait_for(started.wait(), timeout=1)

    # The caller holds nothing. A full collection here is what would reap a
    # task the loop only references weakly; the module's set must keep it.
    gc.collect()
    held = [t for t in monitor_service._BACKGROUND_TASKS if t.get_name() == "publish_soon:held"]
    assert len(held) == 1, monitor_service._BACKGROUND_TASKS

    release.set()
    await asyncio.wait_for(finished.wait(), timeout=1)
    await asyncio.sleep(0)  # let the done-callback run
    assert held[0] not in monitor_service._BACKGROUND_TASKS


@pytest.mark.asyncio
async def test_an_escaped_exception_is_logged_with_its_traceback(caplog):
    async def _boom() -> None:
        raise RuntimeError("bootstrap exploded")

    with caplog.at_level(logging.ERROR, logger=monitor_service.logger.name):
        assert monitor_service._publish_soon("discovery bootstrap", _boom) is True
        for _ in range(5):
            await asyncio.sleep(0)

    records = [
        r for r in caplog.records if r.getMessage() == "Deferred discovery bootstrap failed."
    ]
    assert len(records) == 1, caplog.text
    assert records[0].exc_info is not None
    assert "bootstrap exploded" in caplog.text
    assert not [t for t in monitor_service._BACKGROUND_TASKS if not t.done()]
