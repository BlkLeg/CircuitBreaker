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
from typing import Any

from app.core.nats_client import nats_client
from app.core.time import utcnow
from app.db.models import Hardware, HardwareLiveMetric
from app.db.session import get_session_context
from app.services.status_service import recalculate_hardware_status
from app.services.telemetry_cache import cache_telemetry, publish_telemetry
from app.services.telemetry_service import (
    _NON_LIVE_STATUSES,
    _as_float,
    _as_int,
    _bytes_to_mb,
    _derive_disk_pct,
    _derive_mem_pct,
    _normalise_payload,
)

_logger = logging.getLogger(__name__)

_STREAM_NAME = "TELEMETRY"
_SUBJECT_FILTER = "telemetry.ingest.>"
_CONSUMER_DURABLE = "telemetry_ingest"
_BATCH_SIZE = 50
_FETCH_TIMEOUT_S = 5.0
_CACHE_TTL_SECONDS = 60


# ── Stream bootstrap ──────────────────────────────────────────────────────────


async def _ensure_stream() -> None:
    """Create the TELEMETRY JetStream stream if it does not exist."""
    if not nats_client.is_connected or not nats_client._nc:
        return
    try:
        js = nats_client._nc.jetstream()
        try:
            await js.add_stream(name=_STREAM_NAME, subjects=[_SUBJECT_FILTER])
            _logger.info("NATS %s stream created", _STREAM_NAME)
        except Exception as exc:
            msg = str(exc).lower()
            if "already in use" in msg or "already exists" in msg or "name already in use" in msg:
                _logger.debug("NATS %s stream already exists", _STREAM_NAME)
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
        "cpu_pct": _as_float(data.get("cpu_pct") or data.get("cpu")),
        "mem_pct": _derive_mem_pct(data),
        "mem_used_mb": _as_float(data.get("mem_used_mb")) or _bytes_to_mb(data.get("mem_used")),
        "mem_total_mb": (
            _as_float(data.get("mem_total_mb")) or _bytes_to_mb(data.get("mem_total"))
        ),
        "disk_pct": _derive_disk_pct(data),
        "temp_c": _as_float(data.get("temp_c") or data.get("cpu_temp")),
        "power_w": _as_float(data.get("power_w") or data.get("system_power_w")),
        "uptime_s": _as_int(data.get("uptime_s") or data.get("uptime")),
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
        db.bulk_insert_mappings(HardwareLiveMetric, rows)  # type: ignore[arg-type]

        for hw_id, rec in latest.items():
            hw = db.get(Hardware, hw_id)
            if hw is None:
                continue
            hw.telemetry_data = rec["data"]
            hw.telemetry_status = rec["status"]
            hw.telemetry_last_polled = rec["ts"]
            if rec["status"] not in _NON_LIVE_STATUSES:
                hw.last_seen = rec["ts"].isoformat()
            recalculate_hardware_status(db, hw_id)

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
