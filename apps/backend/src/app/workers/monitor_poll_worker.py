"""Monitor poll worker: JetStream consumer that runs collectors and writes samples.

Deliberately NOT an in-process asyncio task on the API loop (the discovery-scan
anti-pattern). Poll load lives here and scales by running more replicas.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.nats_client import nats_client
from app.core.redis import get_redis
from app.core.subjects import (
    MONITOR_ALERT_DOWN,
    MONITOR_ALERT_RECOVERED,
    monitor_alert_payload,
)
from app.services.monitoring.collectors import COLLECTORS, CheckResult, Sample
from app.services.monitoring.proxmox_override import apply_proxmox_overrides
from app.services.monitoring.state import AppliedTransition, apply_result
from app.services.monitoring.writer import SampleRow, write_samples

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-monitor-poll.healthy")
_MAX_PARALLEL = int(os.getenv("CB_MONITOR_POLL_PARALLEL", "50"))
_FETCH_BATCH = int(os.getenv("CB_MONITOR_POLL_FETCH", "50"))
_JS_STREAM = "MONITOR_POLL"
_JS_DURABLE = "monitor_pollers"
_sema = asyncio.Semaphore(_MAX_PARALLEL)


def _touch_healthy() -> None:
    try:
        _HEALTHY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HEALTHY_FILE.write_text(str(time.time()))
    except OSError:
        pass


async def poll_one(item: dict) -> tuple[SampleRow, bool, str]:
    """Run the check for one monitor in a worker thread. Never raises."""
    ts = datetime.now(UTC)
    collector = COLLECTORS.get(item["check_type"])
    if collector is None:
        row = (
            item["item_id"],
            item["target_type"],
            item["target_id"],
            [Sample("avail", 0.0, error_reason="unknown_check_type")],
            ts,
        )
        return row, False, f"unknown check type {item['check_type']!r}"
    try:
        async with _sema:
            result: CheckResult = await asyncio.to_thread(collector, item["host"], item["params"])
    except Exception as exc:  # noqa: BLE001 — a probe crash is a down datum
        logger.debug("Check crashed for monitor %s: %s", item["item_id"], exc)
        result = CheckResult(
            up=False,
            samples=[Sample("avail", 0.0, error_reason="collector_error")],
            msg=f"check crashed: {type(exc).__name__}",
        )
    row = (item["item_id"], item["target_type"], item["target_id"], result.samples, ts)
    return row, result.up, result.msg


async def process_batch(items: list[dict], db_factory: Callable[[], Any]) -> int:
    outcomes = await asyncio.gather(*(poll_one(i) for i in items))
    transitions: list[AppliedTransition] = []
    db = db_factory()
    try:
        outcomes = apply_proxmox_overrides(db, items, outcomes)
        written = write_samples(db, [row for row, _, _ in outcomes])
        for row, up, msg in outcomes:
            item_id, _, _, _, ts = row
            transition = apply_result(db, item_id, up=up, msg=msg, checked_at=ts)
            if transition:
                transitions.append(transition)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    await _publish_transitions(transitions)
    await _publish_live_status(outcomes)
    return written


async def _publish_transitions(transitions: list[AppliedTransition]) -> None:
    for t in transitions:
        if t.notify == "down":
            subject = MONITOR_ALERT_DOWN.format(item_id=t.item_id)
        elif t.notify == "recovered":
            subject = MONITOR_ALERT_RECOVERED.format(item_id=t.item_id)
        else:
            continue
        payload = monitor_alert_payload(
            t.item_id, t.name, t.status_to, t.msg, t.occurred_at.isoformat()
        )
        try:
            await nats_client.js_publish(subject, payload)
        except Exception as exc:  # noqa: BLE001 — alerting is best-effort here
            logger.warning("Failed to publish monitor alert %s: %s", subject, exc)


async def _publish_live_status(outcomes: list[tuple[SampleRow, bool, str]]) -> None:
    redis = await get_redis()
    if redis is None:
        return
    for row, up, msg in outcomes:
        item_id, _, _, _, ts = row
        payload = json.dumps(
            {
                "monitor_id": item_id,
                "status": "up" if up else "down",
                "msg": msg,
                "ts": ts.isoformat(),
            }
        )
        try:
            await redis.publish(f"monitor:{item_id}", payload)
        except Exception:  # noqa: BLE001 — live push degrades silently
            return


async def run_worker(shutdown_event: asyncio.Event | None = None) -> None:
    from app.db.session import SessionLocal

    backoff = 2
    while not nats_client.is_connected:
        await nats_client.connect()
        if not nats_client.is_connected:
            logger.warning("monitor-poll: waiting for NATS (%ds)", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    await nats_client.ensure_monitor_poll_stream()
    js = nats_client._nc.jetstream()
    psub = await js.pull_subscribe("mon.poll.item", durable=_JS_DURABLE, stream=_JS_STREAM)
    logger.info("monitor-poll worker subscribed (durable=%s)", _JS_DURABLE)
    _touch_healthy()

    while not (shutdown_event and shutdown_event.is_set()):
        try:
            msgs = await psub.fetch(_FETCH_BATCH, timeout=1.0)
        except Exception as exc:  # noqa: BLE001
            if "Timeout" not in type(exc).__name__:
                logger.warning("monitor-poll fetch error: %s", exc)
            _touch_healthy()
            continue

        items: list[dict] = []
        for m in msgs:
            try:
                items.append(json.loads(m.data.decode()))
            except json.JSONDecodeError:
                logger.warning("monitor-poll: bad message, dropping")

        if items:
            try:
                await process_batch(items, SessionLocal)
            except Exception as exc:  # noqa: BLE001
                logger.error("monitor-poll batch failed: %s", exc, exc_info=True)
                for m in msgs:
                    await _safe_nak(m)
                continue

        for m in msgs:
            await _safe_ack(m)
        _touch_healthy()

    logger.info("monitor-poll worker stopped")


async def _safe_ack(msg: Any) -> None:
    try:
        await msg.ack()
    except Exception:
        pass


async def _safe_nak(msg: Any) -> None:
    try:
        await msg.nak()
    except Exception:
        pass


if __name__ == "__main__":
    from app.workers import run_with_graceful_shutdown

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_with_graceful_shutdown(run_worker))
