import asyncio
import json
import logging
import time
from pathlib import Path

from app.core.nats_client import nats_client

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/tmp/worker.healthy")  # noqa: S108


def _touch_healthy() -> None:
    """Update heartbeat file so the container healthcheck can verify liveness."""
    try:
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

    def _scan():
        return nm.scan(hosts=target_str, arguments=args)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _scan)


_JOB_TIMEOUT_S = 600  # 10 minutes max per discovery job


async def _process_job_inner(msg) -> None:
    data = json.loads(msg.data.decode())
    cidr = data.get("target_cidr")
    nmap_args = data.get("nmap_args", "-T4 -F")
    logger.info("Processing discovery job for %s", cidr)

    ips = await _run_masscan(cidr)
    logger.info("Masscan found %d potential targets", len(ips))

    if ips:
        await _run_nmap(ips, nmap_args)
        logger.info("Nmap finished for %s", cidr)

    await msg.ack()


async def process_job(msg, semaphore: asyncio.Semaphore):
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


async def _setup_jetstream(semaphore: asyncio.Semaphore) -> bool:
    """Create stream and subscribe via JetStream. Returns True on success."""
    try:
        js = nats_client._nc.jetstream()
        try:
            await js.add_stream(name="DISCOVERY", subjects=["discovery.jobs"])
        except Exception as e:
            logger.warning("Stream may already exist: %s", e)

        def cb(msg):
            asyncio.create_task(process_job(msg, semaphore))

        await js.subscribe("discovery.jobs", queue="discovery_workers", cb=cb)
        logger.info("Discovery worker subscribed to discovery.jobs")
        return True
    except Exception as exc:
        logger.error("JetStream setup failed: %s", exc)
        return False


async def run_worker():
    # Retry connecting to NATS with backoff — exiting would cause a Docker restart loop.
    backoff = 2
    while not nats_client.is_connected:
        await nats_client.connect()
        if nats_client.is_connected:
            break
        logger.error("Failed to connect to NATS, retrying in %ds…", backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)

    semaphore = asyncio.Semaphore(2)
    await _setup_jetstream(semaphore)
    logger.info("Discovery worker started")
    _touch_healthy()

    # Watchdog: re-subscribe via JetStream after NATS reconnects
    was_connected = True
    while True:
        await asyncio.sleep(10)
        _touch_healthy()
        now_connected = nats_client.is_connected
        if was_connected and not now_connected:
            logger.warning("Discovery worker: NATS disconnected — waiting for auto-reconnect")
        elif not was_connected and now_connected:
            logger.info(
                "Discovery worker: NATS reconnected — re-initialising JetStream subscription"
            )
            await _setup_jetstream(semaphore)
        was_connected = now_connected


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
