"""Remote-probe dispatch worker: `mon.probe.remote` -> `probe.assign` (Slice 3 §2).

The scheduler puts nothing but a `run_id` on NATS. Everything the agent needs —
the host, the monitor's complete validated configuration, and any HTTP
credentials it carries — is loaded here, immediately before encrypted delivery
over the live /link socket (D-10), so no credential ever sits in a JetStream
message.

Its own durable on its own stream (D-3): a blocked agent must not be able to
delay server-executed checks, and JetStream forbids two work-queue consumers
with overlapping subject filters anyway.

Delivery goes through `agent_registry.publish_agent_control_frame` and nothing
else. Only `ws_agents.link_stream`'s own loop may write to an agent socket; this
worker generally is not even in the process that holds it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.nats_client import nats_client
from app.core.subjects import MONITOR_PROBE_REMOTE
from app.core.time import utcnow
from app.db.models import MonitorItem, MonitorProbeRun
from app.schemas.agent_frame import TYPE_PROBE_ASSIGN
from app.services import agent_registry
from app.services.monitoring import probe_eligibility

logger = logging.getLogger(__name__)

_HEALTHY_FILE = Path("/data/worker-monitor-probe-dispatch.healthy")
_FETCH_BATCH = int(os.getenv("CB_MONITOR_PROBE_FETCH", "50"))
_JS_STREAM = "MONITOR_PROBE"
_JS_DURABLE = "monitor_probe_dispatchers"

# §8 vocabulary: a control frame that could not be published is a dispatch
# failure, not a target failure and not an agent-side execution error.
_DISPATCH_FAILED = "dispatch_failed"
# A run whose lease has no end. Nothing but a caller bug produces one, and it is
# worth its own code: `probe.assign` requires `deadline_at` on both sides of the
# wire, and the reconciliation pass expires runs *by* that deadline — so a NULL
# would be published as `null`, rejected by the agent's decoder, and then never
# expired, wedging the monitor behind the partial unique index indefinitely.
_INVALID_RUN = "invalid_run"


def _touch_healthy() -> None:
    try:
        _HEALTHY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HEALTHY_FILE.write_text(str(time.time()))
    except OSError:
        pass


async def dispatch_run(db: Session, run_id: str) -> bool:
    """Turn one queued run into a delivered `probe.assign`.

    Returns whether an assignment was published. Every other outcome — the run
    already closed, the vantage ineligible, the frame undeliverable — closes the
    run and records the reason on the monitor instead, because a run left in
    `queued` holds the partial unique index and would wedge the monitor until
    the reconciliation pass expires it.

    Owns its commit: it is the top-level caller on this path.
    """
    run = db.execute(
        select(MonitorProbeRun).where(MonitorProbeRun.run_id == run_id)
    ).scalar_one_or_none()
    if run is None:
        logger.debug("probe dispatch: unknown run %s", run_id)
        return False
    if run.status != "queued":
        # Cancelled, expired, or already dispatched and redelivered. The backend
        # stays authoritative: nothing here may reopen a closed run.
        logger.debug("probe dispatch: run %s is %s, not queued", run_id, run.status)
        return False

    monitor = db.get(MonitorItem, run.monitor_id)
    if monitor is None:  # pragma: no cover - FK CASCADE removes the run with it
        return False

    decision = await probe_eligibility.evaluate_eligibility(
        db, monitor, agent_id=run.agent_id, ignore_run_id=run.run_id
    )
    if not decision.ok:
        reason = decision.reason or "ineligible"
        logger.info(
            "probe dispatch: run %s for monitor %s refused (%s: %s)",
            run_id,
            monitor.id,
            reason,
            decision.detail,
        )
        _close_unavailable(db, run, monitor, reason, detail=decision.detail)
        return False

    if run.deadline_at is None:
        logger.error("probe dispatch: run %s has no deadline_at", run_id)
        _close_unavailable(db, run, monitor, _INVALID_RUN)
        return False

    frame = {
        "type": TYPE_PROBE_ASSIGN,
        "payload": {
            "run_id": run.run_id,
            "monitor_id": monitor.id,
            "check_type": monitor.check_type,
            "host": monitor.host,
            # The complete stored configuration, credentials included (D-10).
            # The agent holds it in memory for the life of the run only.
            "config": dict(monitor.params or {}),
            # `.isoformat()`, never the raw datetime: publish_agent_control_frame
            # serializes with `json.dumps(default=str)`, which renders a datetime
            # as "2026-08-04 18:00:00+00:00" — a space separator that Go's
            # `time.Time` rejects outright. Same call site shape as
            # `agent_link._handle_key_rotate`.
            "scheduled_at": run.scheduled_at.isoformat(),
            "deadline_at": run.deadline_at.isoformat(),
        },
    }
    delivered = await agent_registry.publish_agent_control_frame(run.agent_id, frame)
    if not delivered:
        # False means Redis itself was unavailable, so nothing can have arrived.
        # A True with no subscriber is "not guaranteed", not "delivered" — that
        # case is the reconciliation pass's deadline, not this branch's.
        logger.warning("probe dispatch: run %s could not be published", run_id)
        _close_unavailable(db, run, monitor, _DISPATCH_FAILED)
        return False

    now = utcnow()
    run.status = "dispatched"
    run.dispatched_at = now
    run.attempt_count = (run.attempt_count or 0) + 1
    monitor.probe_execution_status = "running"
    monitor.probe_execution_reason = None
    monitor.probe_last_dispatched_at = now
    db.commit()
    return True


def _close_unavailable(
    db: Session,
    run: MonitorProbeRun,
    monitor: MonitorItem,
    reason: str,
    *,
    detail: str | None = None,
) -> None:
    """Retire the run and record why the vantage could not run the check.

    No `avail` sample and no retry-counter change: an unavailable vantage is not
    a down target (§2, D-12). `next_due_at` is left where the scheduler put it,
    so the monitor simply tries again on its normal interval.

    `outcome` stays NULL deliberately. It records what the *agent* reported, and
    on this path the agent never saw the assignment at all; `error_code` is the
    discriminator between an ineligible vantage and an undeliverable frame.
    """
    now = utcnow()
    run.status = "execution_error"
    run.error_code = reason
    run.completed_at = now
    if detail:
        run.msg = detail[:2000]
    monitor.probe_execution_status = "unavailable"
    monitor.probe_execution_reason = reason[:128]
    db.commit()


async def process_messages(run_ids: list[str], db_factory: Callable[[], Any]) -> int:
    dispatched = 0
    db = db_factory()
    try:
        for run_id in run_ids:
            try:
                if await dispatch_run(db, run_id):
                    dispatched += 1
            except Exception:
                db.rollback()
                raise
    finally:
        db.close()
    return dispatched


async def run_worker(shutdown_event: asyncio.Event | None = None) -> None:
    from app.db.session import SessionLocal

    backoff = 2
    while not nats_client.is_connected:
        await nats_client.connect()
        if not nats_client.is_connected:
            logger.warning("monitor-probe-dispatch: waiting for NATS (%ds)", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    await nats_client.ensure_monitor_probe_stream()
    js = nats_client._nc.jetstream()
    psub = await js.pull_subscribe(MONITOR_PROBE_REMOTE, durable=_JS_DURABLE, stream=_JS_STREAM)
    logger.info("monitor-probe-dispatch worker subscribed (durable=%s)", _JS_DURABLE)
    _touch_healthy()

    while not (shutdown_event and shutdown_event.is_set()):
        try:
            msgs = await psub.fetch(_FETCH_BATCH, timeout=1.0)
        except Exception as exc:  # noqa: BLE001
            if "Timeout" not in type(exc).__name__:
                logger.warning("monitor-probe-dispatch fetch error: %s", exc)
            _touch_healthy()
            continue

        run_ids: list[str] = []
        for m in msgs:
            try:
                payload = json.loads(m.data.decode())
            except json.JSONDecodeError:
                logger.warning("monitor-probe-dispatch: bad message, dropping")
                continue
            run_id = payload.get("run_id") if isinstance(payload, dict) else None
            if isinstance(run_id, str) and run_id:
                run_ids.append(run_id)
            else:
                logger.warning("monitor-probe-dispatch: message without a run_id, dropping")

        if run_ids:
            try:
                await process_messages(run_ids, SessionLocal)
            except Exception as exc:  # noqa: BLE001
                logger.error("monitor-probe-dispatch batch failed: %s", exc, exc_info=True)
                for m in msgs:
                    await _safe_nak(m)
                continue

        for m in msgs:
            await _safe_ack(m)
        _touch_healthy()

    logger.info("monitor-probe-dispatch worker stopped")


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
