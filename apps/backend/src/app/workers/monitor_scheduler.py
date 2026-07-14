"""Monitor scheduler worker: the single active clock for the polling engine.

Guarded by a Postgres advisory lock so exactly one instance enqueues, even with
multiple replicas. Each tick atomically claims due items (advancing their
next_due_at) and publishes one poll message per item. All scheduling state is in
the DB, so a restart resumes cleanly with no wedged state.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.core.job_lock import _lock_id_for, advisory_unlock, try_advisory_lock
from app.core.nats_client import nats_client
from app.services.monitoring.scheduler import enqueue_due

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-monitor-scheduler.healthy")
_TICK_S = float(os.getenv("CB_MONITOR_SCHED_TICK_S", "1.0"))
_BATCH = int(os.getenv("CB_MONITOR_SCHED_BATCH", "200"))
_LOCK_NAME = "monitor_scheduler"


def _touch_healthy() -> None:
    try:
        _HEALTHY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HEALTHY_FILE.write_text(str(time.time()))
    except OSError:
        pass


async def tick(
    db_factory: Callable[[], Any],
    publish: Callable[[str, dict], Awaitable[bool]],
) -> int:
    db = db_factory()
    try:
        return await enqueue_due(db, publish, batch=_BATCH)
    finally:
        db.close()


async def run_worker(shutdown_event: asyncio.Event | None = None) -> None:
    from app.db.session import SessionLocal

    backoff = 2
    while not nats_client.is_connected:
        await nats_client.connect()
        if not nats_client.is_connected:
            logger.warning("monitor-scheduler: waiting for NATS (%ds)", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
    await nats_client.ensure_monitor_poll_stream()

    lock_id = _lock_id_for(_LOCK_NAME)
    lock_db = SessionLocal()
    have_lock = try_advisory_lock(lock_db, lock_id)
    if not have_lock:
        logger.info("monitor-scheduler: another instance holds the lock; standing by")

    logger.info("monitor-scheduler started (active=%s, tick=%ss)", have_lock, _TICK_S)
    _touch_healthy()
    try:
        while not (shutdown_event and shutdown_event.is_set()):
            if not have_lock:
                have_lock = try_advisory_lock(lock_db, lock_id)
            if have_lock:
                try:
                    await tick(SessionLocal, nats_client.js_publish)
                except Exception as exc:  # noqa: BLE001
                    logger.error("monitor-scheduler tick failed: %s", exc, exc_info=True)
            _touch_healthy()
            try:
                if shutdown_event:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=_TICK_S)
                else:
                    await asyncio.sleep(_TICK_S)
            except TimeoutError:
                pass
    finally:
        if have_lock:
            advisory_unlock(lock_db, lock_id)
        lock_db.close()
    logger.info("monitor-scheduler worker stopped")


if __name__ == "__main__":
    from app.workers import run_with_graceful_shutdown

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_with_graceful_shutdown(run_worker))
