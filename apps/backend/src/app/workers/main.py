import argparse
import asyncio
import logging

from app.core.log_redaction import install_global_log_redaction
from app.workers import run_with_graceful_shutdown

logger = logging.getLogger(__name__)


_TYPE_MAP = {
    "0": "discovery",
    "1": "webhook",
    "2": "notification",
    "3": "telemetry",
    "4": "monitor_scheduler",
    "5": "monitor_poll",
    "6": "monitor_poll",
}


async def _run_discovery() -> None:
    from app.workers import discovery as discovery_worker

    await run_with_graceful_shutdown(discovery_worker.run_worker)


async def _run_webhook() -> None:
    from app.workers import webhook_worker

    await run_with_graceful_shutdown(webhook_worker.run_worker)


async def _run_notification() -> None:
    from app.workers import notification_worker

    await run_with_graceful_shutdown(notification_worker.run_worker)


async def _run_telemetry() -> None:
    from app.workers import telemetry_collector

    await run_with_graceful_shutdown(telemetry_collector.run_worker)


async def _run_monitor_scheduler() -> None:
    from app.workers import monitor_scheduler

    await run_with_graceful_shutdown(monitor_scheduler.run_worker)


async def _run_monitor_poll() -> None:
    from app.workers import monitor_poll_worker

    await run_with_graceful_shutdown(monitor_poll_worker.run_worker)


async def _dispatch(kind: str) -> None:
    if kind == "discovery":
        await _run_discovery()
    elif kind == "webhook":
        await _run_webhook()
    elif kind == "notification":
        await _run_notification()
    elif kind == "telemetry":
        await _run_telemetry()
    elif kind == "monitor_scheduler":
        await _run_monitor_scheduler()
    elif kind == "monitor_poll":
        await _run_monitor_poll()
    else:
        raise SystemExit(f"Unknown worker type: {kind!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified Circuit Breaker worker entrypoint")
    parser.add_argument(
        "--type",
        required=True,
        help=(
            "Worker type: discovery, webhook, notification, telemetry,"
            " monitor_scheduler, monitor_poll, or numeric"
            " (0=discovery,1=webhook,2=notification,3=telemetry,"
            "4=monitor_scheduler,5=monitor_poll,6=monitor_poll)"
        ),
    )
    args = parser.parse_args()

    worker_type = args.type
    if worker_type in _TYPE_MAP:
        worker_type = _TYPE_MAP[worker_type]

    logging.basicConfig(level=logging.INFO)
    install_global_log_redaction()
    logger.info("Starting worker type %s", worker_type)

    asyncio.run(_dispatch(worker_type))


if __name__ == "__main__":
    main()
