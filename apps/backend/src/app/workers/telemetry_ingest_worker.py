"""Telemetry ingest worker — JetStream pull consumer for batch DB writes.

Consumes messages from the TELEMETRY JetStream stream (subject ``telemetry.ingest.>``),
produced by ``telemetry_collector`` after each device poll.

Advantages over per-poll synchronous DB writes:
- Decouples polling latency from DB write latency.
- Bulk-inserts up to BATCH_SIZE rows per commit → fewer round-trips to TimescaleDB.
- NATS durability: messages survive an ingest-worker restart; no telemetry is lost during
  rolling upgrades or transient DB hiccups.
- Graceful degradation: if NATS is unavailable, the collector falls back to direct writes
  so monitoring continues uninterrupted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from nats.js.api import RetentionPolicy

from app.core.nats_client import nats_client
from app.core.time import utcnow
from app.db.models import Hardware, HardwareLiveMetric
from app.db.session import get_session_context
from app.services.telemetry_cache import cache_telemetry, publish_telemetry
from app.services.telemetry_normalize import (
    _NON_LIVE_STATUSES,
    _normalise_payload,
    live_metric_fields,
)

_logger = logging.getLogger(__name__)

_STREAM_NAME = "TELEMETRY"
_SUBJECT_FILTER = "telemetry.ingest.>"
_CONSUMER_DURABLE = "telemetry_ingest"
_BATCH_SIZE = 50
_FETCH_TIMEOUT_S = 5.0
_CACHE_TTL_SECONDS = 60


# ── Stream bootstrap ──────────────────────────────────────────────────────────


def _stream_config() -> dict[str, Any]:
    """The TELEMETRY stream config this build wants.

    Read fresh on every call so the env knobs take effect on a worker restart rather
    than only on the process that first created the stream.

    The stream used to be declared with nothing but a name and a subject list, which is
    JetStream's LimitsPolicy with no max_msgs, no max_bytes and no max_age — i.e. keep
    every message forever, acked or not. `telemetry_collector` publishes one message per
    device per poll cycle (30s by default), so the NATS volume grew without bound until
    the disk filled, at which point every publisher on the box starts failing at once and
    the loss is nowhere near limited to telemetry.
    """
    return {
        "name": _STREAM_NAME,
        "subjects": [_SUBJECT_FILTER],
        # WorkQueuePolicy, matching MONITOR_POLL and MONITOR_PROBE in core/nats_client.py:
        # `run_ingest_loop` acks every message it has written, so an acked sample is
        # deleted instead of retained and the steady-state stream size is the backlog,
        # not the history. Legal here because the ingest worker is the stream's only
        # consumer — a work queue forbids two consumers with overlapping subject filters,
        # and every replica shares the one `telemetry_ingest` durable.
        "retention": RetentionPolicy.WORK_QUEUE,
        # Belt and braces for the window where the ingest worker is down and nothing is
        # acking: telemetry has no value once it is an hour stale, and 256 MiB is far
        # more backlog than the batch loop could ever usefully drain.
        "max_age": int(os.getenv("CB_TELEMETRY_STREAM_MAX_AGE_S", "3600")),
        "max_bytes": int(os.getenv("CB_TELEMETRY_STREAM_MAX_BYTES", str(256 * 1024 * 1024))),
    }


async def _update_stream_limits(js: Any, cfg: dict[str, Any]) -> None:
    """Retro-fit `cfg`'s limits onto a stream that already exists.

    `add_stream` against a stream whose stored config differs reports "stream name
    already in use" — the same string an identical stream never produces. Swallowing
    that at debug level, as this worker used to, means an upgraded deployment keeps the
    limitless stream it was created with forever and never sees a byte of this fix, so
    the mismatch branch has to reach back and update the stream in place.

    The retention policy is deliberately taken from the *server's* copy rather than from
    `cfg`. JetStream refuses a stream update that changes retention and rejects the whole
    request when it sees one, so sending WorkQueuePolicy at a stream created under
    LimitsPolicy would throw the max_age/max_bytes fix away along with it. Existing
    installs therefore stay LimitsPolicy and merely become bounded, which is the part
    that actually closes the disk-exhaustion path; only streams created from scratch get
    the work queue.
    """
    name = cfg["name"]
    try:
        info = await js.stream_info(name)
        await js.update_stream(**{**cfg, "retention": info.config.retention})
        _logger.info("NATS %s stream limits updated", name)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("NATS %s stream limits update failed: %s", name, exc)


async def _ensure_stream() -> None:
    """Create the TELEMETRY JetStream stream, or bound one an older build left limitless."""
    if not nats_client.is_connected or not nats_client._nc:
        return
    try:
        js = nats_client._nc.jetstream()
        cfg = _stream_config()
        try:
            await js.add_stream(**cfg)
            _logger.info("NATS %s stream created", _STREAM_NAME)
        except Exception as exc:
            msg = str(exc).lower()
            if "already in use" in msg or "already exists" in msg or "name already in use" in msg:
                await _update_stream_limits(js, cfg)
            else:
                _logger.warning("NATS %s stream ensure failed: %s", _STREAM_NAME, exc)
    except Exception as exc:
        _logger.warning("NATS stream setup failed: %s", exc)


# ── Batch processing ──────────────────────────────────────────────────────────


def _build_metric_row(
    hw_id: int,
    source: str,
    data: dict[str, Any],
    status: str,
    error_msg: str | None,
    ts: Any,
) -> dict[str, Any]:
    return {
        "hardware_id": hw_id,
        "collected_at": ts,
        **live_metric_fields(data),
        "status": status,
        "source": source,
        "raw": data,
        "error_msg": error_msg,
    }


async def _process_batch(msgs: list[Any]) -> None:
    """Parse, bulk-insert metrics, update Hardware rows, and refresh Redis cache."""
    rows: list[dict[str, Any]] = []
    latest: dict[int, dict[str, Any]] = {}  # hw_id → most-recent parsed entry in this batch

    for msg in msgs:
        try:
            env = json.loads(msg.data)
        except Exception:
            _logger.debug("Telemetry ingest: unparseable message dropped")
            continue
        try:
            hw_id = int(env["hardware_id"])
            payload: dict[str, Any] = env["payload"]
            source = str(env.get("source") or "unknown")
        except (KeyError, TypeError, ValueError) as exc:
            _logger.debug("Telemetry ingest: malformed envelope: %s", exc)
            continue

        data, status, error_msg = _normalise_payload(payload)
        ts = utcnow()

        rows.append(_build_metric_row(hw_id, source, data, status, error_msg, ts))

        if hw_id not in latest or ts > latest[hw_id]["ts"]:
            latest[hw_id] = {
                "ts": ts,
                "data": data,
                "status": status,
                "source": source,
                "error_msg": error_msg,
            }

    if not rows:
        return

    # ── Bulk DB write ─────────────────────────────────────────────────────────
    with get_session_context() as db:
        db.bulk_insert_mappings(HardwareLiveMetric, rows)

        for hw_id, rec in latest.items():
            hw = db.get(Hardware, hw_id)
            if hw is None:
                continue
            hw.telemetry_data = rec["data"]
            hw.telemetry_status = rec["status"]
            hw.telemetry_last_polled = rec["ts"]
            if rec["status"] not in _NON_LIVE_STATUSES:
                hw.last_seen = rec["ts"].isoformat()

        db.commit()

    # ── Redis cache + WebSocket publish ───────────────────────────────────────
    for hw_id, rec in latest.items():
        cache_payload: dict[str, Any] = {
            "data": rec["data"],
            "status": rec["status"],
            "last_polled": rec["ts"].isoformat(),
            "source": rec["source"],
        }
        if rec["error_msg"]:
            cache_payload["error_msg"] = rec["error_msg"]

        try:
            await cache_telemetry(hw_id, cache_payload, ttl=_CACHE_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001
            _logger.debug("Telemetry ingest cache failed hw:%d: %s", hw_id, exc)

        try:
            await publish_telemetry(
                hw_id,
                {"entity_type": "hardware", "hardware_id": hw_id, **cache_payload},
            )
        except Exception as exc:  # noqa: BLE001
            _logger.debug("Telemetry ingest publish failed hw:%d: %s", hw_id, exc)


# ── Consumer loop ─────────────────────────────────────────────────────────────


async def run_ingest_loop(stop_event: asyncio.Event) -> None:
    """Pull-subscribe loop.  Runs as a long-lived asyncio task inside the app lifespan."""
    psub: Any = None
    was_connected = False

    _logger.info("Telemetry ingest worker starting.")

    while not stop_event.is_set():
        now_connected = nats_client.is_connected and nats_client._nc is not None

        if now_connected and not was_connected:
            # (Re)connected — ensure stream exists and create pull subscription.
            try:
                await _ensure_stream()
                js = nats_client._nc.jetstream()
                psub = await js.pull_subscribe(_SUBJECT_FILTER, durable=_CONSUMER_DURABLE)
                _logger.info(
                    "Telemetry ingest worker subscribed to %s stream (durable=%s)",
                    _STREAM_NAME,
                    _CONSUMER_DURABLE,
                )
            except Exception as exc:
                _logger.warning("Telemetry ingest worker JetStream setup failed: %s", exc)
                psub = None

        was_connected = now_connected

        if psub is None:
            # Waiting for NATS — sleep briefly before retry.
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1.0)
            except TimeoutError:
                pass
            continue

        # ── Fetch batch ───────────────────────────────────────────────────────
        try:
            msgs = await psub.fetch(_BATCH_SIZE, timeout=_FETCH_TIMEOUT_S)
        except Exception as exc:
            # TimeoutError is normal (no messages); other errors signal a broken subscription.
            exc_name = type(exc).__name__
            if "Timeout" not in exc_name:
                _logger.warning(
                    "Telemetry ingest fetch error (%s): %s — resetting subscription",
                    exc_name,
                    exc,
                )
                psub = None
                was_connected = False  # Force reconnect path on next iteration
            continue

        if not msgs:
            continue

        # ── Process ───────────────────────────────────────────────────────────
        try:
            await _process_batch(msgs)
        except Exception as exc:  # noqa: BLE001
            _logger.error("Telemetry ingest batch failed: %s", exc, exc_info=True)
            # NAK so NATS will redeliver after the ack-wait period.
            for msg in msgs:
                try:
                    await msg.nak()
                except Exception:
                    pass
            continue

        for msg in msgs:
            try:
                await msg.ack()
            except Exception as exc:  # noqa: BLE001
                _logger.debug("Telemetry ingest ACK failed: %s", exc)

    _logger.info("Telemetry ingest worker stopped.")
