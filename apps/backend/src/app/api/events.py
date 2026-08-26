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

Auth: viewer or higher. Revoked/expired sessions are rejected before the
stream is opened.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from app.core import subjects
from app.core.nats_client import nats_client
from app.core.rbac import require_role
from app.core.security import _extract_token, _is_user_accessible, decode_token
from app.db.models import Log
from app.db.session import SessionLocal
from app.services.settings_service import get_or_create_settings
from app.services.stream_faults import FAULT_DECODE, record_stream_fault
from app.services.user_service import is_session_revoked

logger = logging.getLogger(__name__)

router = APIRouter()

# REL-07 fault-metric identity for the SSE stream.
_COMPONENT = "sse_events"

_KEEPALIVE_INTERVAL = 15  # seconds between SSE keepalive comments
# Log SSE NATS queue drops at most once per interval to avoid log spam under load
_QUEUE_FULL_LOG_INTERVAL_S = 30.0
# How often a live stream re-checks that its session is still valid. This is the
# upper bound on how long a revoked session keeps receiving alert data.
_REVALIDATE_INTERVAL_S = 15.0


def decode_nats_event(msg: Any) -> dict | None:
    """Parse one NATS message body, or return None if it is not usable.

    Returning None rather than `{}` is the point: the old code substituted an
    empty payload on a parse failure, which turned an unparseable frame into a
    well-formed event the frontend rendered as a real (empty) notification.
    Counted so a publisher shipping bad frames is visible (REL-07).
    """
    try:
        decoded = json.loads(msg.data.decode())
    except Exception as exc:
        record_stream_fault(
            f"{_COMPONENT}.decode",
            exc,
            logger=logger,
            context={"subject": getattr(msg, "subject", "?")},
            fault=FAULT_DECODE,
        )
        return None
    if not isinstance(decoded, dict):
        # A bare list/str/number is valid JSON but not an event; the `**data`
        # splat downstream would raise on it inside the NATS callback, where
        # nothing would ever see the traceback.
        record_stream_fault(
            f"{_COMPONENT}.decode",
            TypeError(f"event payload is {type(decoded).__name__}, not an object"),
            logger=logger,
            context={"subject": getattr(msg, "subject", "?")},
            fault=FAULT_DECODE,
        )
        return None
    return decoded


# ── Mid-stream revocation ────────────────────────────────────────────────────


def _session_still_valid(raw_token: str | None) -> bool:
    """Re-run the connect-time auth policy against current DB state.

    Authenticating only at connect meant a revoked or expired session kept
    receiving notification and alert events until the client disconnected —
    which, for an SSE stream a dashboard holds open, can be indefinitely.
    """
    with SessionLocal() as db:
        cfg = get_or_create_settings(db)
        if not cfg.auth_enabled:
            # Pre-bootstrap: there are no sessions to revoke yet.
            return True
        if not cfg.jwt_secret or not raw_token:
            return False
        if is_session_revoked(db, raw_token):
            return False
        uid = decode_token(raw_token, cfg.jwt_secret)
        if uid is None:
            return False
        return _is_user_accessible(db, uid)


async def _revoked_frame(raw_token: str | None, state: dict[str, float]) -> str | None:
    """Return a terminal SSE frame once the session stops being valid, else None.

    Rate-limited to one DB check per `_REVALIDATE_INTERVAL_S` so a 2 s poll loop
    does not turn into a 2 s auth query. Fails closed: if the check itself
    errors we end the stream rather than keep streaming unvalidated.
    """
    now = time.monotonic()
    if now < state["next_check"]:
        return None
    state["next_check"] = now + _REVALIDATE_INTERVAL_S
    loop = asyncio.get_running_loop()
    try:
        valid = await loop.run_in_executor(None, _session_still_valid, raw_token)
    except Exception:
        logger.warning("SSE revalidation failed; closing stream", exc_info=True)
        valid = False
    if valid:
        return None
    return "event: session_revoked\ndata: {}\n\n"


def _revalidation_state() -> dict[str, float]:
    return {"next_check": time.monotonic() + _REVALIDATE_INTERVAL_S}


# ── NATS-backed SSE ──────────────────────────────────────────────────────────


def _nats_event_generator(queue: asyncio.Queue[Any], raw_token: str | None) -> AsyncIterator[str]:
    """Async generator that reads from an asyncio.Queue populated by NATS callbacks."""

    async def _gen() -> AsyncGenerator[str, None]:
        yield ": keepalive\n\n"
        revalidation = _revalidation_state()
        while True:
            revoked = await _revoked_frame(raw_token, revalidation)
            if revoked is not None:
                yield revoked
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_INTERVAL)
                yield item
            except TimeoutError:
                yield ": keepalive\n\n"
            except asyncio.CancelledError:
                break
            except Exception as exc:
                # Reading the in-process queue has no recoverable failure mode:
                # anything that reaches here (a closed loop, a broken queue)
                # will reach here again on the next iteration, and the old code
                # yielded ": error" in a tight loop with no sleep — a spin that
                # pinned a core and filled the client's socket buffer. End the
                # stream explicitly instead; the browser's EventSource
                # reconnects (REL-07).
                record_stream_fault(f"{_COMPONENT}.nats_queue", exc, logger=logger)
                yield ": error\n\n"
                break

    return _gen()


# ── DB-poll fallback SSE ─────────────────────────────────────────────────────


def _db_poll_generator(raw_token: str | None) -> AsyncIterator[str]:
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

        revalidation = _revalidation_state()
        while True:
            await asyncio.sleep(2)
            revoked = await _revoked_frame(raw_token, revalidation)
            if revoked is not None:
                yield revoked
                break
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
                # The 2s sleep above already bounds the retry rate, so this
                # loop keeps polling — the database coming back is exactly the
                # recovery this fallback exists for. What it must not do is
                # hide the outage at DEBUG for hours: classified, throttled and
                # counted (REL-07).
                record_stream_fault(
                    f"{_COMPONENT}.db_poll",
                    exc,
                    logger=logger,
                    context={"last_log_id": last_log_id},
                )
                yield ": error\n\n"

    return _gen()


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.get("/stream")
async def events_stream(request: Request, _user: Any = require_role("viewer")) -> StreamingResponse:
    """Stream real-time notification and alert events via SSE.

    Automatically selects NATS-backed delivery when available, falling back
    to DB polling when NATS is not connected.
    """
    # Captured once here; the stream re-checks it against the DB as it runs so
    # revoking a session actually ends the stream it authorized.
    raw_token = _extract_token(request)
    if nats_client.is_connected:
        queue: asyncio.Queue = asyncio.Queue(maxsize=512)
        _last_queue_full_log = 0.0

        async def _nats_cb(msg: Any) -> None:
            nonlocal _last_queue_full_log
            data = decode_nats_event(msg)
            if data is None:
                return
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
                async for chunk in _nats_event_generator(queue, raw_token):
                    yield chunk
            finally:
                for sub in subscriptions:
                    try:
                        await sub.unsubscribe()
                    except Exception as exc:
                        # A failed unsubscribe leaks a NATS subscription for
                        # the life of the connection; counted so the leak is
                        # measurable instead of invisible.
                        record_stream_fault(f"{_COMPONENT}.unsubscribe", exc, logger=logger)

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
        _db_poll_generator(raw_token),
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
