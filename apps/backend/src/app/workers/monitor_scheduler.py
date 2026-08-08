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
from app.services.monitoring import probe_reconcile
from app.services.monitoring.scheduler import enqueue_due

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-monitor-scheduler.healthy")
_TICK_S = float(os.getenv("CB_MONITOR_SCHED_TICK_S", "1.0"))
_BATCH = int(os.getenv("CB_MONITOR_SCHED_BATCH", "200"))
# D-2 fair sharing: no vantage (the server, or any one agent) may take more
# than _PER_VANTAGE of a tick, and the claim locks _OVERSAMPLE rows so the
# ranking has every vantage to rank before the global _BATCH cap applies.
_PER_VANTAGE = int(os.getenv("CB_MONITOR_SCHED_PER_VANTAGE", "50"))
_OVERSAMPLE = int(os.getenv("CB_MONITOR_SCHED_OVERSAMPLE", "1000"))
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
        # D-5: remote-probe reconciliation rides this tick rather than a worker
        # of its own — this is already the single active clock, under the
        # `monitor_scheduler` advisory lock, with a session open. It runs first
        # so an expired run has released the partial unique index before the
        # claim below can decide the monitor is due again.
        #
        # Guarded, because a reconciliation defect must never be able to stop
        # the scheduler: an item that is never claimed is a wedged item, which
        # is the one failure the whole engine is built to make impossible.
        try:
            await probe_reconcile.reconcile(db)
        except Exception as exc:  # noqa: BLE001
            logger.error("monitor-scheduler reconcile failed: %s", exc, exc_info=True)
            db.rollback()
        return await enqueue_due(
            db,
            publish,
            batch=_BATCH,
            per_vantage=_PER_VANTAGE,
            oversample=_OVERSAMPLE,
        )
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
    await nats_client.ensure_monitor_probe_stream()

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
