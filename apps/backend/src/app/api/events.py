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

Auth: optional — if auth_enabled is False the stream is public.
"""

import asyncio
import json
import logging

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


# ── NATS-backed SSE ──────────────────────────────────────────────────────────


def _nats_event_generator(queue: asyncio.Queue):
    """Async generator that reads from an asyncio.Queue populated by NATS callbacks."""

    async def _gen():
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


def _db_poll_generator():
    """Poll the logs / notifications tables every 2 s as a fallback stream."""

    async def _gen():
        yield ": keepalive\n\n"
        last_log_id: int = 0

        # Seed last_log_id to avoid replaying old history on connect
        try:
            with SessionLocal() as db:
                from sqlalchemy import func, select

                max_id = db.execute(select(func.max(Log.id))).scalar_one_or_none()
                if max_id:
                    last_log_id = max_id
        except Exception:
            pass

        while True:
            await asyncio.sleep(2)
            try:
                with SessionLocal() as db:
                    from sqlalchemy import select

                    rows = (
                        db.execute(
                            select(Log).where(Log.id > last_log_id).order_by(Log.id.asc()).limit(20)
                        )
                        .scalars()
                        .all()
                    )
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
async def events_stream(_user=Depends(get_optional_user)):
    """Stream real-time notification and alert events via SSE.

    Automatically selects NATS-backed delivery when available, falling back
    to DB polling when NATS is not connected.
    """
    if nats_client.is_connected:
        queue: asyncio.Queue = asyncio.Queue(maxsize=512)

        async def _nats_cb(msg) -> None:
            try:
                data = json.loads(msg.data.decode())
            except Exception:
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
                pass  # Drop if backpressure — client too slow

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

        async def _cleanup_generator():
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
