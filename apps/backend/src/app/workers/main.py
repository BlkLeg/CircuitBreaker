import argparse
import asyncio
import logging

from app.core.log_redaction import install_global_log_redaction
from app.workers import run_with_graceful_shutdown

logger = logging.getLogger(__name__)


_TYPE_MAP = {
    "0": "discovery",
    "2": "notification",
    "3": "telemetry",
    "4": "monitor_scheduler",
    "5": "monitor_poll",
    "6": "monitor_poll",
    "7": "monitor_probe_dispatch",
    "8": "integration",
}


async def _run_discovery() -> None:
    from app.workers import discovery as discovery_worker

    await run_with_graceful_shutdown(discovery_worker.run_worker)


async def _run_notification() -> None:
    from app.workers import notification_worker

    await run_with_graceful_shutdown(notification_worker.run_worker)


async def _run_telemetry() -> None:
    from app.workers import telemetry_collector

    await run_with_graceful_shutdown(telemetry_collector.run_worker)


async def _run_integration() -> None:
    from app.workers import integration_worker

    await run_with_graceful_shutdown(integration_worker.run_integration_worker)


async def _run_monitor_scheduler() -> None:
    from app.workers import monitor_scheduler

    await run_with_graceful_shutdown(monitor_scheduler.run_worker)


async def _run_monitor_poll() -> None:
    from app.workers import monitor_poll_worker

    await run_with_graceful_shutdown(monitor_poll_worker.run_worker)


async def _run_monitor_probe_dispatch() -> None:
    from app.workers import monitor_probe_dispatch

    await run_with_graceful_shutdown(monitor_probe_dispatch.run_worker)


async def _dispatch(kind: str) -> None:
    if kind == "discovery":
        await _run_discovery()

    elif kind == "notification":
        await _run_notification()
    elif kind == "telemetry":
        await _run_telemetry()
    elif kind == "integration":
        await _run_integration()
    elif kind == "monitor_scheduler":
        await _run_monitor_scheduler()
    elif kind == "monitor_poll":
        await _run_monitor_poll()
    elif kind == "monitor_probe_dispatch":
        await _run_monitor_probe_dispatch()
    else:
        raise SystemExit(f"Unknown worker type: {kind!r}")


def _log_topology(worker_type: str) -> None:
    """State the ownership this process is claiming (SRV-02).

    A dedicated worker running beside an API process that still owns the same
    function in-process is the mixed-mode configuration that duplicates work.
    It is logged rather than refused: the queue-backed workers are safe to run
    alongside (JetStream delivers each message once), and the timer-shaped ones
    hold a `SingleActiveLease`, so the second instance stands by instead of
    repeating the work. What must never happen is that it is invisible.
    """
    from app.core.topology import TopologyConfigError, resolve_mode

    try:
        mode = resolve_mode()
    except TopologyConfigError as exc:
        logger.error("[topology] %s", exc)
        return
    logger.info("[topology] mode=%s worker_type=%s", mode.value, worker_type)
    if mode.value == "mono":
        logger.warning(
            "[topology] this is a dedicated %s worker, but CB_TOPOLOGY_MODE=mono says the "
            "API process owns the background workers too. Set CB_TOPOLOGY_MODE=api on the "
            "API process so exactly one owner is declared.",
            worker_type,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified Circuit Breaker worker entrypoint")
    parser.add_argument(
        "--type",
        required=True,
        help=(
            "Worker type: discovery, notification, telemetry, integration,"
            " monitor_scheduler, monitor_poll, monitor_probe_dispatch, or numeric"
            " (0=discovery,2=notification,3=telemetry,"
            "4=monitor_scheduler,5=monitor_poll,6=monitor_poll,"
            "7=monitor_probe_dispatch,8=integration)"
        ),
    )
    args = parser.parse_args()

    worker_type = args.type
    if worker_type in _TYPE_MAP:
        worker_type = _TYPE_MAP[worker_type]

    logging.basicConfig(level=logging.INFO)
    install_global_log_redaction()
    _log_topology(worker_type)
    logger.info("Starting worker type %s", worker_type)

    asyncio.run(_dispatch(worker_type))


if __name__ == "__main__":
    main()
