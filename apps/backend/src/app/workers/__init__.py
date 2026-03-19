import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

from app.core.nats_client import nats_client

logger = logging.getLogger(__name__)


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
