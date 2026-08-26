import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

from app.core.nats_client import nats_client

logger = logging.getLogger(__name__)


class SingleActiveLease:
    """A PostgreSQL advisory lease that makes a worker loop single-active (SRV-02).

    Some worker loops are JetStream consumers on a durable name, and running a
    second one distributes work rather than repeating it. The rest are *timers*
    — "every N seconds, find what is due and do it" — and a second instance of
    one of those does every unit of work twice: two telemetry polls per device,
    two syncs per integration, two of whatever they write. Those loops take
    this lease, and an instance that does not hold it stands by and retries,
    exactly as `monitor_scheduler` (the pattern this generalises) does.

    Standing by rather than exiting is what makes a rolling restart safe: the
    replacement process is already running and idle when the departing one
    releases, so the function never stops happening.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._db = None
        self._lock_id = None
        self._held = False

    @property
    def name(self) -> str:
        return self._name

    def held(self) -> bool:
        return self._held

    def try_acquire(self) -> bool:
        """Take the lease if it is free. Never blocks; safe to call every tick."""
        if self._held:
            return True
        from app.core.job_lock import _lock_id_for, lock_session, try_advisory_lock

        if self._db is None:
            self._db = lock_session()
            self._lock_id = _lock_id_for("worker_lease", self._name)
        self._held = try_advisory_lock(self._db, self._lock_id)
        return self._held

    def release(self) -> None:
        """Hand the lease off and close the connection that held it."""
        from app.core.job_lock import advisory_unlock

        if self._db is None:
            return
        try:
            if self._held:
                advisory_unlock(self._db, self._lock_id)
        finally:
            self._held = False
            self._db.close()
            self._db = None

    async def try_acquire_async(self) -> bool:
        return await asyncio.to_thread(self.try_acquire)

    async def release_async(self) -> None:
        await asyncio.to_thread(self.release)


async def run_with_graceful_shutdown(
    worker_loop_coro: Callable[[asyncio.Event], Awaitable[None]],
) -> None:
    """
    Wraps a worker's main loop with standard SIGTERM/SIGINT handling.
    The worker_loop_coro should accept a shutdown_event argument and
    exit cleanly when the event is set.
    """
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def sigterm_handler() -> None:
        logger.info("SIGTERM received, shutting down gracefully...")
        shutdown_event.set()

    try:
        loop.add_signal_handler(signal.SIGTERM, sigterm_handler)
        loop.add_signal_handler(signal.SIGINT, sigterm_handler)
    except NotImplementedError:
        # Fails on Windows, but this is designed for Linux/Docker
        pass

    try:
        await worker_loop_coro(shutdown_event)
    finally:
        await shutdown()


async def shutdown() -> None:
    """Shared teardown logic for workers."""
    if nats_client.is_connected:
        await nats_client.disconnect()

    # Note: DB sessions in workers are typically localized to the job processing blocks.
    # We do not hold long-running global sessions that need explicit closing here.

    logger.info("Worker shutdown complete")
