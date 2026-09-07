"""The background tasks the API process owns, and how they are stopped.

Everything here is optional to the request path: the mDNS/SSDP listener, the
OPNsense poller, the in-process worker loops (only when the topology says this
process runs them), the daily update check and the event-loop lag sampler.

Started together and stopped together, because the stopping is the part with a
contract. Two of the loops hold a PostgreSQL advisory lease and release it in a
`finally`; cancelling them before they observe their stop event means that
`finally` runs inside a cancelled task, where the release itself raises. See
:func:`drain_background_tasks`.
"""

import asyncio
import logging
import os
from dataclasses import dataclass

from app.core import topology
from app.db import models
from app.db.session import get_session_context
from app.startup.scheduler import run_discovery_enrichment_backfill

_logger = logging.getLogger(__name__)

#: How long the cooperative loops get to exit on their own before being
#: cancelled. Well inside the unit's TimeoutStopSec=30 and the scheduler's own
#: 10s budget; the loops park on `wait_for(stop_event.wait(), ...)` and wake
#: immediately, so it is only ever paid by a worker genuinely mid-batch.
_WORKER_DRAIN_TIMEOUT_S = 5.0


@dataclass
class BackgroundTasks:
    """Handles for everything :func:`start_background_tasks` created.

    `draining` is the subset of `tasks` that takes a stop event and cleans up in
    a `finally` — currently the telemetry-ingest and integration loops, both of
    which release an advisory lease there. Tracked separately because shutdown
    has to let them observe the stop event before anything cancels them.
    """

    tasks: list[asyncio.Task]
    draining: list[asyncio.Task]
    ingest_stop: asyncio.Event
    integration_stop: asyncio.Event


async def start_background_tasks(topology_mode: topology.TopologyMode) -> BackgroundTasks:
    """Start every background loop this process owns and return their handles."""
    # ── Phase 4: Always-On Listener (mDNS + SSDP) ─────────────────────────
    from app.services.listener_service import listener_service

    with get_session_context() as listener_db:
        listener_settings = listener_db.query(models.AppSettings).first()
        if listener_settings and getattr(listener_settings, "listener_enabled", False):
            asyncio.create_task(listener_service.start(listener_settings))
            _logger.info("Always-on listener started.")

    # ── OPNsense background monitor ───────────────────────────────────────────
    with get_session_context() as _opn_db:
        _opn_settings = _opn_db.query(models.AppSettings).first()
        if _opn_settings and getattr(_opn_settings, "opnsense_enabled", False):
            from app.services.opnsense_monitor import start_monitor as _start_opnsense_monitor

            _opn_cfg = {
                "opnsense_host": getattr(_opn_settings, "opnsense_host", ""),
                "opnsense_api_key_enc": getattr(_opn_settings, "opnsense_api_key_enc", None),
                "opnsense_api_secret_enc": getattr(_opn_settings, "opnsense_api_secret_enc", None),
                "opnsense_verify_ssl": getattr(_opn_settings, "opnsense_verify_ssl", False),
            }
            await _start_opnsense_monitor(_opn_cfg)

    # ── Notification and discovery workers (skip when running with dedicated worker
    # containers, e.g. Docker Compose) ───────────────────────────────────────────
    _run_inprocess_workers = topology.api_runs_inprocess_workers(topology_mode)
    _worker_tasks: list = []
    # The subset of _worker_tasks that takes a stop event and cleans up in a
    # `finally` -- currently the telemetry-ingest and integration loops, both of
    # which release a PostgreSQL advisory lease there. They are tracked
    # separately because shutdown has to let them observe the stop event before
    # anything cancels them; see the drain block below for what happens when it
    # does not.
    _draining_tasks: list = []
    _ingest_stop_event = asyncio.Event()
    _integration_stop_event = asyncio.Event()
    if _run_inprocess_workers:
        from app.workers import discovery as discovery_worker
        from app.workers import notification_worker
        from app.workers.telemetry_ingest_worker import run_ingest_loop as _run_ingest_loop

        _worker_tasks.append(asyncio.create_task(notification_worker.run_worker()))
        _worker_tasks.append(asyncio.create_task(discovery_worker.run_worker()))
        _ingest_task = asyncio.create_task(_run_ingest_loop(_ingest_stop_event))
        _worker_tasks.append(_ingest_task)
        _draining_tasks.append(_ingest_task)
        from app.workers.integration_worker import run_integration_worker as _run_integration_worker

        _integration_task = asyncio.create_task(_run_integration_worker(_integration_stop_event))
        _worker_tasks.append(_integration_task)
        _draining_tasks.append(_integration_task)
        _logger.info(
            "Notification, discovery, telemetry ingest, and integration workers started in-process."
        )
    else:
        _logger.info(
            "[topology] mode=%s — %s run as dedicated worker processes, not in the API.",
            topology_mode.value,
            ", ".join(topology.INPROCESS_WORKER_FUNCTIONS),
        )

    # ── Phase 9: Update check (non-blocking, daily) ─────────────────────
    # Appended to _worker_tasks so shutdown cancels it. Deliberately outside
    # the inprocess worker conditional: knowing the build is stale is not
    # a worker concern.
    try:
        from app.core.update_check import run_update_check_loop

        _worker_tasks.append(asyncio.create_task(run_update_check_loop()))
    except Exception:
        pass  # Never let update check affect startup

    # ── Phase 10: Discovery readiness logging ──────────────────────────
    # Make degraded discovery (missing nmap, no raw sockets, no ARP, etc.)
    # visible at boot instead of only being discovered at scan time.
    try:
        from app.services.discovery_readiness import log_discovery_readiness_at_startup

        log_discovery_readiness_at_startup()
    except Exception:
        _logger.warning("Discovery readiness logging failed at startup", exc_info=True)

    # ── Phase 11: reconcile the discovery review queue ─────────────────────
    # Reclassify stale new observations, enrich known devices, and consolidate
    # pending duplicates from older builds. The paginated pass is idempotent;
    # unknown devices remain reviewable. Threaded because it owns a synchronous
    # session; a failed backfill is reported without preventing startup.
    try:
        await asyncio.to_thread(run_discovery_enrichment_backfill)
    except Exception:
        _logger.warning("Discovery enrichment backfill failed at startup", exc_info=True)

    # ── Task 1c: event-loop lag sampler (observability phase 2) ────────────
    # A 100ms sleep loop is free, so this runs by default. Appended to
    # _worker_tasks so the cancel-and-gather shutdown below stops it the same
    # way it stops the update-check loop — return_exceptions=True there means
    # a cancelled or failed sampler never raises into this lifespan.
    if os.environ.get("CB_LOOP_LAG_SAMPLER", "true").strip().lower() not in {"false", "0", "no"}:
        from app.core.slo_metrics import run_event_loop_lag_sampler

        _worker_tasks.append(asyncio.create_task(run_event_loop_lag_sampler()))
    else:
        _logger.info("[lifecycle] event loop lag sampler disabled via CB_LOOP_LAG_SAMPLER=false")

    return BackgroundTasks(
        tasks=_worker_tasks,
        draining=_draining_tasks,
        ingest_stop=_ingest_stop_event,
        integration_stop=_integration_stop_event,
    )


async def stop_listener() -> None:
    """Stop the always-on mDNS/SSDP listener.

    First thing the shutdown does: it holds sockets, and it is the only
    background task that accepts unauthenticated LAN traffic.
    """
    from app.services.listener_service import listener_service

    await listener_service.stop()


def stop_opnsense_monitor() -> None:
    """Cancel the OPNsense poller, if one was started."""
    from app.services.opnsense_monitor import cancel_monitor

    cancel_monitor()


async def drain_background_tasks(background: BackgroundTasks) -> None:
    """Signal the cooperative loops, wait, then cancel whatever is left."""
    # Setting the stop event and cancelling in the same block is what this used
    # to do, and it meant the cooperative loops never saw the event: `cancel()`
    # lands before the loop is scheduled again, so the task raises CancelledError
    # at whatever `await` it is parked on. Their `finally` blocks then run in a
    # cancelled task, where the very next `await` -- `lease.release_async()`,
    # which is `asyncio.to_thread(...)` -- raises immediately instead of
    # releasing.
    #
    # The advisory lease therefore stayed held on a session nothing closed. On a
    # rolling restart the replacement process stands by waiting for a lease the
    # departing one never handed over, and the function it guards silently stops
    # happening -- exactly the failure
    # tests/test_srv_drain.py::test_a_restarted_process_can_take_the_lease_the_old_one_held
    # exists to catch, which it did not because it probed only the
    # `scheduled_job` namespace and not `worker_lease`. It surfaced instead as an
    # intermittent failure of tests/test_worker_lease.py two files later in the
    # same CI shard.
    #
    # So: signal, give the cooperative loops a bounded window to exit on their
    # own, and only then cancel. Five seconds sits well inside the unit's
    # TimeoutStopSec=30 and the scheduler's own 10s budget above; the loops park
    # on `wait_for(stop_event.wait(), ...)` and wake immediately, so the window
    # is only ever paid by a worker genuinely mid-batch.
    background.ingest_stop.set()
    background.integration_stop.set()

    if background.draining:
        _, _still_running = await asyncio.wait(background.draining, timeout=_WORKER_DRAIN_TIMEOUT_S)
        if _still_running:
            # Named rather than counted: which loop refused to drain is the first
            # thing anyone debugging a stuck shutdown needs, and it is also how a
            # lease that is still held after this point gets attributed.
            _logger.warning(
                "Worker task(s) did not drain within %ss and will be cancelled — "
                "any lease they hold is released only when this process exits: %s",
                _WORKER_DRAIN_TIMEOUT_S,
                ", ".join(sorted(_t.get_name() for _t in _still_running)),
            )

    for _wt in background.tasks:
        _wt.cancel()
    if background.tasks:
        await asyncio.gather(*background.tasks, return_exceptions=True)
        _logger.info("In-process workers stopped.")
