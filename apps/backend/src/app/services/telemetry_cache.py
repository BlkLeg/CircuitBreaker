"""Redis-backed telemetry cache with TTL and pub/sub publish.

All functions degrade gracefully when Redis is unavailable — they return
``None`` on cache miss (caller falls back to DB) and silently skip publishes.
"""

from __future__ import annotations

import json
import logging

from app.core.redis import get_redis

_logger = logging.getLogger(__name__)

_TELEMETRY_TTL = 300  # seconds
_METRIC_TTL = 300

_KEY_TELEMETRY = "telemetry:{entity_id}"
_KEY_METRIC = "metric:{ip}"
_CHANNEL_TELEMETRY = "telemetry:{entity_id}"


async def cache_telemetry(entity_id: int, data: dict) -> None:
    """SET telemetry:{entity_id} with 60 s TTL."""
    r = await get_redis()
    if r is None:
        return
    try:
        key = _KEY_TELEMETRY.format(entity_id=entity_id)
        await r.set(key, json.dumps(data, default=str), ex=_TELEMETRY_TTL)
    except Exception as exc:
        _logger.debug("telemetry cache write failed: %s", exc)


async def get_cached_telemetry(entity_id: int) -> dict | None:
    """GET telemetry:{entity_id} — returns parsed dict or None (cache miss / Redis down)."""
    r = await get_redis()
    if r is None:
        return None
    try:
        key = _KEY_TELEMETRY.format(entity_id=entity_id)
        raw = await r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        _logger.debug("telemetry cache read failed: %s", exc)
        return None


async def cache_live_metric(ip: str, data: dict) -> None:
    """SET metric:{ip} with 60 s TTL."""
    r = await get_redis()
    if r is None:
        return
    try:
        key = _KEY_METRIC.format(ip=ip)
        await r.set(key, json.dumps(data, default=str), ex=_METRIC_TTL)
    except Exception as exc:
        _logger.debug("metric cache write failed: %s", exc)


async def get_cached_metric(ip: str) -> dict | None:
    """GET metric:{ip} — returns parsed dict or None."""
    r = await get_redis()
    if r is None:
        return None
    try:
        key = _KEY_METRIC.format(ip=ip)
        raw = await r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        _logger.debug("metric cache read failed: %s", exc)
        return None


async def publish_telemetry(entity_id: int, data: dict) -> None:
    """PUBLISH to channel ``telemetry:{entity_id}`` for WebSocket fan-out."""
    r = await get_redis()
    if r is None:
        return
    try:
        channel = _CHANNEL_TELEMETRY.format(entity_id=entity_id)
        payload = json.dumps({"entity_id": entity_id, **data}, default=str)
        await r.publish(channel, payload)
    except Exception as exc:
        _logger.debug("telemetry publish failed: %s", exc)
