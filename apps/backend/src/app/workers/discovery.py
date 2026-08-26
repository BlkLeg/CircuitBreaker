import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from nats.js.api import RetentionPolicy

from app.core.nats_client import nats_client
from app.core.nmap_args import validate_nmap_arguments

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-discovery.healthy")


def _touch_healthy() -> None:
    """Update heartbeat file so the container healthcheck can verify liveness."""
    try:
        _HEALTHY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HEALTHY_FILE.write_text(str(time.time()))
    except OSError:
        pass


async def _run_masscan(cidr: str) -> list[str]:
    cmd = ["masscan", cidr, "-p", "1-65535", "--rate=1000", "-oJ", "-"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0 and b"No such file" in stderr:
        logger.warning("masscan not found, returning cidr")
        return [cidr]

    try:
        if not stdout.strip():
            return []
        results = json.loads(stdout.decode())
        ips = {r["ip"] for r in results}
        return list(ips)
    except Exception:
        return [cidr]


async def _run_nmap(targets: list[str], args: str) -> dict:
    import nmap

    nm = nmap.PortScanner()
    target_str = " ".join(targets)

    def _scan() -> Any:
        return nm.scan(hosts=target_str, arguments=args)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _scan)


_JOB_TIMEOUT_S = 600  # 10 minutes max per discovery job


async def _process_job_inner(msg: Any) -> None:
    data = json.loads(msg.data.decode())
    cidr = data.get("target_cidr")
    raw_nmap = data.get("nmap_args", "-T4 -F")
    try:
        nmap_args = validate_nmap_arguments(raw_nmap)
    except ValueError as e:
        logger.warning("Invalid nmap_args in job, using default: %s", e)
        nmap_args = "-T4 -F"
    logger.info("Processing discovery job for %s", cidr)

    ips = await _run_masscan(cidr)
    logger.info("Masscan found %d potential targets", len(ips))

    if ips:
        await _run_nmap(ips, nmap_args)
        logger.info("Nmap finished for %s", cidr)

    await msg.ack()


async def process_job(msg: Any, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        try:
            await asyncio.wait_for(_process_job_inner(msg), timeout=_JOB_TIMEOUT_S)
        except TimeoutError:
            logger.error(
                "Discovery job timed out after %ds, releasing semaphore slot", _JOB_TIMEOUT_S
            )
            try:
                await msg.nak()
            except Exception:
                pass
        except Exception as e:
            logger.error("Error processing discovery job: %s", e)
            try:
                await msg.nak()
            except Exception:
                pass


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
        # `process_job` acks a finished scan and naks a failed one, so a work queue is
        # right here too: a job that has been run has no reason to stay on disk. The
        # queue group is what keeps this legal — nats-py turns `queue` into the durable
        # consumer name (see `subscribe` below), so every replica shares one consumer
        # rather than each adding another with the same subject filter, which a work
        # queue would reject.
        "retention": RetentionPolicy.WORK_QUEUE,
        # A discovery job whose scan window has long passed is not worth running: a
        # single job is capped at _JOB_TIMEOUT_S, so an hour is many jobs' worth of slack.
        "max_age": int(os.getenv("CB_DISCOVERY_STREAM_MAX_AGE_S", "3600")),
        "max_bytes": int(os.getenv("CB_DISCOVERY_STREAM_MAX_BYTES", str(64 * 1024 * 1024))),
    }


async def _update_stream_limits(js: Any, cfg: dict[str, Any]) -> None:
    """Retro-fit `cfg`'s limits onto a DISCOVERY stream that already exists.

    `add_stream` reports a config mismatch as "stream name already in use", which this
    worker used to log as "Stream may already exist" and move on — so an upgraded
    deployment would have kept its limitless stream forever. Retention is taken from the
    server's stored config rather than from `cfg` because JetStream rejects an update
    that changes it, and rejects the whole request along with it. Same reasoning, at
    length, in `workers/telemetry_ingest_worker._update_stream_limits`.
    """
    name = cfg["name"]
    try:
        info = await js.stream_info(name)
        await js.update_stream(**{**cfg, "retention": info.config.retention})
        logger.info("NATS %s stream limits updated", name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("NATS %s stream limits update failed: %s", name, exc)


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
    logger.info("Discovery worker: max_concurrent_scans=%d", _max_concurrent)
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
