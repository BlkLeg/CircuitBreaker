"""
General-purpose Server-Sent Events (SSE) endpoint.

GET /api/v1/events/stream

Delivers a merged real-time stream of notifications, alerts, and discovery
progress events.  When NATS is available the stream is NATS-backed (zero
polling latency); when NATS is unavailable it falls back to DB polling every
2 seconds so the frontend always gets a working SSE connection.

Event format (text/event-stream):
  event: <event_type>
  data: <json_payload>

  (blank line)

Supported event types:
  notification   — general informational events
  alert          — severity-bearing alert events
  discovery      — discovery scan progress / completion events
  keepalive      — empty comment (": keepalive") every 15 s

Auth: optional — authenticated via get_optional_user.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from app.core import subjects
from app.core.nats_client import nats_client
from app.core.security import get_optional_user
from app.db.models import Log
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()

_KEEPALIVE_INTERVAL = 15  # seconds between SSE keepalive comments
# Log SSE NATS queue drops at most once per interval to avoid log spam under load
_QUEUE_FULL_LOG_INTERVAL_S = 30.0


# ── NATS-backed SSE ──────────────────────────────────────────────────────────


def _nats_event_generator(queue: asyncio.Queue[Any]) -> AsyncIterator[str]:
    """Async generator that reads from an asyncio.Queue populated by NATS callbacks."""

    async def _gen() -> AsyncGenerator[str, None]:
        yield ": keepalive\n\n"
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_INTERVAL)
                yield item
            except TimeoutError:
                yield ": keepalive\n\n"
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("SSE NATS generator error: %s", exc)
                yield ": error\n\n"

    return _gen()


# ── DB-poll fallback SSE ─────────────────────────────────────────────────────


def _db_poll_generator() -> AsyncIterator[str]:
    """Poll the logs / notifications tables every 2 s as a fallback stream.

    All SQLAlchemy calls run in a thread via run_in_executor so the asyncio
    event loop is never blocked by synchronous DB I/O.
    """

    async def _gen() -> AsyncGenerator[str, None]:
        yield ": keepalive\n\n"
        last_log_id: int | None = 0
        loop = asyncio.get_running_loop()

        # Seed last_log_id to avoid replaying old history on connect
        def _seed() -> int | None:
            from sqlalchemy import func, select

            with SessionLocal() as db:
                return db.execute(select(func.max(Log.id))).scalar_one_or_none()

        try:
            max_id = await loop.run_in_executor(None, _seed)
            last_log_id = max_id if max_id is not None else 0
        except Exception:
            logger.warning("SSE DB poll: initial seed failed; retrying once", exc_info=True)
            try:
                max_id = await loop.run_in_executor(None, _seed)
                last_log_id = max_id if max_id is not None else 0
            except Exception:
                logger.exception(
                    "SSE DB poll: seed failed after retry; polling disabled until DB recovers"
                )
                last_log_id = None

        while True:
            await asyncio.sleep(2)
            if last_log_id is None:
                try:
                    max_id = await loop.run_in_executor(None, _seed)
                    last_log_id = max_id if max_id is not None else 0
                    logger.info("SSE DB poll: re-seeded after earlier connection failure")
                except Exception:
                    yield ": error\n\n"
                    continue
            try:

                def _poll(_last: int | None = last_log_id) -> Any:
                    from sqlalchemy import select

                    with SessionLocal() as db:
                        if _last is None:
                            return []
                        return (
                            db.execute(
                                select(Log).where(Log.id > _last).order_by(Log.id.asc()).limit(20)
                            )
                            .scalars()
                            .all()
                        )

                rows = await loop.run_in_executor(None, _poll)
                for row in rows:
                    payload = {
                        "id": row.id,
                        "action": row.action,
                        "category": row.category,
                        "entity_type": row.entity_type,
                        "entity_id": row.entity_id,
                        "entity_name": row.entity_name,
                        "actor": row.actor,
                        "details": row.details,
                        "created_at_utc": row.created_at_utc,
                        "severity": row.severity or row.level,
                    }
                    event_type = (
                        "alert"
                        if row.severity in ("warning", "error", "critical")
                        else "notification"
                    )
                    yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
                    last_log_id = max(last_log_id, row.id)
            except Exception as exc:
                logger.debug("SSE DB poll error: %s", exc)
                yield ": error\n\n"

    return _gen()


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.get("/stream")
async def events_stream(_user: Any = Depends(get_optional_user)) -> StreamingResponse:
    """Stream real-time notification and alert events via SSE.

    Automatically selects NATS-backed delivery when available, falling back
    to DB polling when NATS is not connected.
    """
    if nats_client.is_connected:
        queue: asyncio.Queue = asyncio.Queue(maxsize=512)
        _last_queue_full_log = 0.0

        async def _nats_cb(msg: Any) -> None:
            nonlocal _last_queue_full_log
            try:
                data = json.loads(msg.data.decode())
            except Exception:
                logger.debug(
                    "SSE NATS: malformed message on %s",
                    getattr(msg, "subject", "?"),
                    exc_info=True,
                )
                data = {}
            subj = msg.subject
            if subj in (subjects.ALERT_EVENT,):
                event_type = "alert"
            elif subj in (
                subjects.DISCOVERY_SCAN_STARTED,
                subjects.DISCOVERY_SCAN_PROGRESS,
                subjects.DISCOVERY_SCAN_COMPLETED,
                subjects.DISCOVERY_SCAN_FAILED,
                subjects.DISCOVERY_DEVICE_FOUND,
            ):
                event_type = "discovery"
            else:
                event_type = "notification"
            item = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                # Drop under backpressure (slow consumer). Throttle warnings.
                now = time.monotonic()
                if now - _last_queue_full_log >= _QUEUE_FULL_LOG_INTERVAL_S:
                    _last_queue_full_log = now
                    logger.warning(
                        "SSE NATS: event queue full (maxsize=%s); "
                        "dropping events until consumer catches up",
                        queue.maxsize,
                    )

        subscriptions = []
        for subj in (
            subjects.NOTIFICATION_EVENT,
            subjects.ALERT_EVENT,
            subjects.DISCOVERY_SCAN_STARTED,
            subjects.DISCOVERY_SCAN_PROGRESS,
            subjects.DISCOVERY_SCAN_COMPLETED,
            subjects.DISCOVERY_SCAN_FAILED,
            subjects.DISCOVERY_DEVICE_FOUND,
        ):
            sub = await nats_client.subscribe(subj, _nats_cb)
            if sub:
                subscriptions.append(sub)

        async def _cleanup_generator() -> AsyncGenerator[str, None]:
            try:
                async for chunk in _nats_event_generator(queue):
                    yield chunk
            finally:
                for sub in subscriptions:
                    try:
                        await sub.unsubscribe()
                    except Exception:
                        pass

        return StreamingResponse(
            _cleanup_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # NATS not available — fall back to DB polling
    logger.debug("SSE /events/stream: NATS unavailable, using DB-poll fallback")
    return StreamingResponse(
        _db_poll_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/status")
async def events_status() -> dict:
    """Return realtime transport status for frontend capability detection."""
    return {
        "nats_connected": nats_client.is_connected,
        "transport": "nats" if nats_client.is_connected else "db_poll",
    }
