import argparse
import asyncio
import logging

from app.workers import run_with_graceful_shutdown

logger = logging.getLogger(__name__)


_TYPE_MAP = {
    "0": "discovery",
    "1": "webhook",
    "2": "notification",
    "3": "telemetry",
}


async def _run_discovery():
    from app.workers import discovery as discovery_worker

    await run_with_graceful_shutdown(discovery_worker.run_worker)


async def _run_webhook():
    from app.workers import webhook_worker

    await run_with_graceful_shutdown(webhook_worker.run_worker)


async def _run_notification():
    from app.workers import notification_worker

    await run_with_graceful_shutdown(notification_worker.run_worker)


async def _run_telemetry():
    from app.workers import telemetry_collector

    await run_with_graceful_shutdown(telemetry_collector.run_worker)


async def _dispatch(kind: str) -> None:
    if kind == "discovery":
        await _run_discovery()
    elif kind == "webhook":
        await _run_webhook()
    elif kind == "notification":
        await _run_notification()
    elif kind == "telemetry":
        await _run_telemetry()
    else:
        raise SystemExit(f"Unknown worker type: {kind!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified Circuit Breaker worker entrypoint")
    parser.add_argument(
        "--type",
        required=True,
        help="Worker type: discovery, webhook, notification, telemetry, or numeric (0=discovery,1=webhook,2=notification,3=telemetry)",
    )
    args = parser.parse_args()

    worker_type = args.type
    if worker_type in _TYPE_MAP:
        worker_type = _TYPE_MAP[worker_type]

    logging.basicConfig(level=logging.INFO)
    logger.info("Starting worker type %s", worker_type)

    asyncio.run(_dispatch(worker_type))


if __name__ == "__main__":
    main()
