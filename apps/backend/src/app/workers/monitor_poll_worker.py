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

from nats.js.api import ConsumerConfig

from app.core.nats_client import nats_client
from app.db.session import get_session_context
from app.services.monitoring.collectors import COLLECTORS, CheckResult, Sample
from app.services.monitoring.result_service import (
    OUTCOME_COMPLETED,
    SOURCE_SERVER,
    MonitorResult,
    process_results,
)
from app.services.monitoring.writer import SampleRow
from app.workers.dead_letter import handle_failed_delivery

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-monitor-poll.healthy")
_MAX_PARALLEL = int(os.getenv("CB_MONITOR_POLL_PARALLEL", "50"))
_FETCH_BATCH = int(os.getenv("CB_MONITOR_POLL_FETCH", "50"))
_JS_STREAM = "MONITOR_POLL"
_JS_DURABLE = "monitor_pollers"
#: Delivery budget before a message is parked (route F14). Five attempts across
#: the ack-wait window is long enough to ride out a transient database or NATS
#: blip, and short enough that a genuinely poisoned message stops blocking its
#: batch within minutes rather than never.
_MAX_DELIVER = 5
_sema = asyncio.Semaphore(_MAX_PARALLEL)

# What one collector run yields, before it is turned into a MonitorResult:
# the sample row, the target verdict, the message, the execution outcome, and
# the collector's free-form details. The last two are carried rather than
# dropped so the shape matches what a remote vantage reports; on this path
# `details` has nowhere to land (D-8) and the outcome is always `completed`,
# because a server-side collector crash is a down datum, not an execution error.
PollOutcome = tuple[SampleRow, bool, str, str, dict | None]


def _touch_healthy() -> None:
    try:
        _HEALTHY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HEALTHY_FILE.write_text(str(time.time()))
    except OSError:
        pass


async def poll_one(item: dict) -> PollOutcome:
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
        msg = f"unknown check type {item['check_type']!r}"
        return row, False, msg, OUTCOME_COMPLETED, None
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
    return row, result.up, result.msg, OUTCOME_COMPLETED, result.details


async def process_batch(items: list[dict], db_factory: Callable[[], Any]) -> int:
    """Poll a claimed batch, then hand it to the one shared result path (§6).

    Everything after the collectors — the Proxmox override, samples, the state
    machine, events, alerts and the live push — lives in
    `services/monitoring/result_service.py`, which the remote `probe.result`
    ingest path calls with the identical record shape. This function is
    deliberately thin: a second copy of that logic here is exactly the drift §6
    exists to prevent.
    """
    outcomes = await asyncio.gather(*(poll_one(i) for i in items))
    results = [
        MonitorResult(
            item_id=row[0],
            target_type=row[1],
            target_id=row[2],
            check_type=item.get("check_type"),
            samples=row[3],
            up=up,
            msg=msg,
            checked_at=row[4],
            outcome=outcome,
            details=details,
            source=SOURCE_SERVER,
        )
        for item, (row, up, msg, outcome, details) in zip(items, outcomes, strict=True)
    ]
    return await process_results(results, db_factory)


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
    psub = await js.pull_subscribe(
        "mon.poll.item",
        durable=_JS_DURABLE,
        stream=_JS_STREAM,
        config=ConsumerConfig(max_deliver=_MAX_DELIVER),
    )
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

        # Messages stay paired with what they decoded to. The previous version
        # built a bare `items` list that silently skipped unparseable messages,
        # so indices no longer lined up with `msgs` and the failure path below
        # could not tell which message caused what.
        parsed: list[tuple[Any, dict]] = []
        for m in msgs:
            try:
                parsed.append((m, json.loads(m.data.decode())))
            except json.JSONDecodeError as exc:
                # Parked, not dropped. "bad message, dropping" acked it, which
                # deleted the payload and left no record — despite
                # db/models_failed_message.py naming a message that failed to
                # parse as exactly the kind that belongs in failed_messages.
                # max_deliver=1 because a parse failure is deterministic:
                # redelivering the same bytes cannot succeed.
                logger.warning("monitor-poll: unparseable message, parking")
                await handle_failed_delivery(
                    m,
                    stream=_JS_STREAM,
                    consumer=_JS_DURABLE,
                    error=f"JSONDecodeError: {exc}",
                    max_deliver=1,
                    session_factory=get_session_context,
                )

        if parsed:
            try:
                await process_batch([item for _, item in parsed], SessionLocal)
            except Exception as exc:  # noqa: BLE001
                logger.error("monitor-poll batch failed, isolating: %s", exc, exc_info=True)
                # Failure handling was per-batch despite the comment claiming
                # otherwise: only the *delivery budget* was checked per message.
                # One poison item in a 50-message fetch naked all 50 together,
                # marched all 50 to max_deliver, then parked and terminated
                # them — 49 healthy monitor checks deleted from a work queue and
                # filed as failures under someone else's exception.
                #
                # Re-running one at a time isolates the real offender. A message
                # that already succeeded inside the failed batch may be polled
                # twice; that was already true of every redelivery, since a nak
                # re-polls the whole batch, and a duplicate availability sample
                # is a far smaller harm than discarding 49 checks.
                await _process_individually(parsed)
                _touch_healthy()
                continue

        for m, _ in parsed:
            await _safe_ack(m)
        _touch_healthy()

    logger.info("monitor-poll worker stopped")


async def _process_individually(parsed: list[tuple[Any, dict]]) -> None:
    """Re-run a failed batch one message at a time, so only the poison one pays.

    Called after a batch raises. Each message is acked on success and handed to
    the dead-letter path on its own failure, with its own error attached rather
    than the batch exception that happened to surface first.
    """
    from app.db.session import SessionLocal

    for m, item in parsed:
        try:
            await process_batch([item], SessionLocal)
        except Exception as exc:  # noqa: BLE001 - attributed to this message, not the batch
            logger.error("monitor-poll: message failed in isolation: %s", exc, exc_info=True)
            await handle_failed_delivery(
                m,
                stream=_JS_STREAM,
                consumer=_JS_DURABLE,
                error=f"{type(exc).__name__}: {exc}",
                max_deliver=_MAX_DELIVER,
                session_factory=get_session_context,
            )
        else:
            await _safe_ack(m)


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
