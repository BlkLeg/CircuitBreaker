"""The DISCOVERY JetStream consumer — which deliberately runs no scan (B44).

Nothing in this tree publishes to `discovery.jobs`. Outside this module's own
tests the subject is named in this file and in no other, in any language: the
`add_stream` in `_stream_config`, the `subscribe` in `_setup_jetstream`, and the
log lines that report them. That has been true since the module was first
committed, so no publisher was "lost in a refactor" — there never was one, and
`test_discovery_worker_job_consumer.py` fails if one appears without a result
path.

The consumer body is what settles which way to resolve that. It used to run
masscan, then nmap, and then throw both results away: no `ScanResult` row, no
`ScanJob` transition, no broadcast, nothing a scan is for. It was never the other
half of a discovery pipeline. Scheduled and operator-triggered discovery both go
through `services/discovery_service.execute_scan_job`, which either scans from
the server (`run_scan_job`) or dispatches to an agent
(`agent_discovery.dispatch_discovery_job`); neither touches this queue.

What the handler *was*, then, is an unauthenticated subprocess launcher: anyone
able to publish to the NATS server got `masscan <whatever they put in
target_cidr>` executed from a process that is deliberately given ambient
CAP_NET_RAW (`docker/supervisord.mono.conf`), in exchange for no product
function at all. `target_cidr` was never validated — only `nmap_args` was. That
execution path is gone; a message that somehow arrives is logged at ERROR and
consumed, because an un-acked message on a work-queue stream is redelivered
forever.

Retiring the worker outright — the supervisord program, the `--type=discovery`
entry in `workers/main.py`, the `topology.py` row, the native-release module
list — is the rest of B44 and touches files outside this one. Until that
happens `run_worker` must keep running and keep touching the heartbeat file, or
supervisord's `startsecs=5` turns the exit into a crash loop. The stream
declaration also stays: a deployment that already has a DISCOVERY stream should
keep the B15 limits on it rather than have them quietly stop being applied.
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from nats.js.api import RetentionPolicy

from app.core.nats_client import nats_client
from app.workers.stream_limits import update_stream_limits

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-discovery.healthy")


def _touch_healthy() -> None:
    """Update heartbeat file so the container healthcheck can verify liveness."""
    try:
        _HEALTHY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HEALTHY_FILE.write_text(str(time.time()))
    except OSError:
        pass


async def process_job(msg: Any, semaphore: asyncio.Semaphore) -> None:
    """Consume a `discovery.jobs` message without acting on it.

    Nothing publishes to this subject (see the module docstring), so reaching
    here means either a stray message left on the stream by an older build or a
    publisher this worker has no result path for. Neither is a reason to run
    masscan and nmap against a target nobody validated, so the message is logged
    at ERROR — loudly, because "a discovery job arrived and was dropped" is
    exactly the thing that must not be silent if this queue is ever revived —
    and then acked.

    Acked rather than naked or left alone: DISCOVERY is a `WORK_QUEUE` stream, so
    an un-acked message is redelivered until `max_age` expires it, and a
    redelivery loop of a message nobody can process is a log flood, not a
    retry. The payload is deliberately not parsed; its size is all that is
    reported, so an oversized or malformed body cannot steer anything here.

    `semaphore` is still taken and the signature is unchanged: `_setup_jetstream`
    passes it, and the day this queue gets a real publisher and a real result
    path, the concurrency ceiling it carries is the part that should not have to
    be reinvented.
    """
    async with semaphore:
        logger.error(
            "Discarding a message on discovery.jobs (%d bytes): this worker has no "
            "publisher and no result path for that subject. Discovery runs through "
            "discovery_service.execute_scan_job, not this queue.",
            len(getattr(msg, "data", b"") or b""),
        )
        try:
            await msg.ack()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to ack a discarded discovery.jobs message: %s", exc)


def _stream_config() -> dict[str, Any]:
    """The DISCOVERY stream config this build wants.

    The stream used to be declared with just a name and a subject, i.e. LimitsPolicy with
    no max_msgs, no max_bytes and no max_age — every job kept forever, acked or not. See
    `workers/telemetry_ingest_worker._stream_config` for the long form of why that is a
    disk-exhaustion path; the shape below is the same one.
    """
    return {
        "name": "DISCOVERY",
        "subjects": ["discovery.jobs"],
        # `process_job` acks everything it is handed, so a work queue is right here:
        # a consumed message has no reason to stay on disk. The queue group is what
        # keeps this legal — nats-py turns `queue` into the durable consumer name
        # (see `subscribe` below), so every replica shares one consumer rather than
        # each adding another with the same subject filter, which a work queue would
        # reject.
        "retention": RetentionPolicy.WORK_QUEUE,
        # Belt and braces for a subject with no publisher: anything that does land
        # here expires within the hour whether or not a consumer is running.
        "max_age": int(os.getenv("CB_DISCOVERY_STREAM_MAX_AGE_S", "3600")),
        "max_bytes": int(os.getenv("CB_DISCOVERY_STREAM_MAX_BYTES", str(64 * 1024 * 1024))),
    }


async def _update_stream_limits(js: Any, cfg: dict[str, Any]) -> None:
    """Retro-fit `cfg`'s limits onto a DISCOVERY stream that already exists.

    Delegates to `workers.stream_limits.update_stream_limits`. This used to be a
    byte-identical copy of the TELEMETRY worker's version, and when R12 was fixed
    there this copy was left behind — so a clustered NATS kept silently demoting
    the R3 DISCOVERY stream to R1 while the TELEMETRY one was safe, and the
    report said the regression was closed. Two copies of this is the defect; the
    shared module carries the reasoning.
    """
    await update_stream_limits(js, cfg)


async def _setup_jetstream(semaphore: asyncio.Semaphore) -> bool:
    """Create stream and subscribe via JetStream. Returns True on success."""
    try:
        js = nats_client._nc.jetstream()
        cfg = _stream_config()
        try:
            await js.add_stream(**cfg)
        except Exception as e:
            msg = str(e).lower()
            if "already in use" in msg or "already exists" in msg:
                await _update_stream_limits(js, cfg)
            else:
                logger.warning("DISCOVERY stream ensure failed: %s", e)

        def cb(msg: Any) -> None:
            asyncio.create_task(process_job(msg, semaphore))

        await js.subscribe("discovery.jobs", queue="discovery_workers", cb=cb)
        logger.info("Discovery worker subscribed to discovery.jobs")
        return True
    except Exception as exc:
        logger.error("JetStream setup failed: %s", exc)
        return False


async def run_worker(shutdown_event: asyncio.Event | None = None) -> None:
    """Keep the DISCOVERY subscription and the heartbeat alive.

    This loop does no discovery — see the module docstring for why the consumer
    it maintains has nothing to consume. It is kept running rather than removed
    because the removal spans the supervisord program, `workers/main.py`,
    `core/topology.py` and the native-release module list, and a `run_worker`
    that returns immediately would be a crash loop under `startsecs=5` rather
    than a retirement.
    """
    # Retry connecting to NATS with backoff — exiting would cause a Docker restart loop.
    backoff = 2
    while not nats_client.is_connected:
        await nats_client.connect()
        if not nats_client.is_connected:
            logger.error("Failed to connect to NATS, retrying in %ds...", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    from app.db.session import SessionLocal
    from app.services.settings_service import get_or_create_settings

    with SessionLocal() as _db:
        _settings = get_or_create_settings(_db)
        _max_concurrent = max(1, getattr(_settings, "max_concurrent_scans", 2) or 2)

    semaphore = asyncio.Semaphore(_max_concurrent)
    logger.info(
        "Discovery worker: max_concurrent_scans=%d (carried, not used — see module docs)",
        _max_concurrent,
    )
    await _setup_jetstream(semaphore)
    logger.info("Discovery worker started")
    _touch_healthy()

    # Watchdog: re-subscribe via JetStream after NATS reconnects
    was_connected: bool = True
    while not (shutdown_event and shutdown_event.is_set()):
        try:
            if shutdown_event:
                await asyncio.wait_for(shutdown_event.wait(), timeout=10.0)
            else:
                await asyncio.sleep(10)
        except TimeoutError:
            pass

        _touch_healthy()
        now_connected: bool = nats_client.is_connected
        if was_connected and not now_connected:
            logger.warning("Discovery worker: NATS disconnected — waiting for auto-reconnect")
        elif not was_connected and now_connected:
            logger.info(
                "Discovery worker: NATS reconnected — re-initialising JetStream subscription"
            )
            await _setup_jetstream(semaphore)
        was_connected = now_connected


if __name__ == "__main__":
    from app.workers import run_with_graceful_shutdown

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_with_graceful_shutdown(run_worker))
