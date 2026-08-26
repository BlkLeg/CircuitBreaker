"""Redis-backed telemetry cache with TTL and pub/sub publish.

All functions degrade gracefully when Redis is unavailable — they return
``None`` on cache miss (caller falls back to DB) and silently skip publishes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

import redis.asyncio as aioredis

from app.core.constants import TELEMETRY_CACHE_TTL_SECONDS
from app.core.redis import get_redis
from app.services.stream_faults import FAULT_DECODE, record_stream_fault

_logger = logging.getLogger(__name__)

# REL-07 fault-metric identity. Every function here runs once per monitored
# entity per poll, so an unthrottled WARNING per failure is a log storm the
# moment Redis goes away — which is exactly when the log needs to stay readable.
_COMPONENT = "telemetry_cache"

_TELEMETRY_TTL = TELEMETRY_CACHE_TTL_SECONDS
_METRIC_TTL = TELEMETRY_CACHE_TTL_SECONDS

_KEY_TELEMETRY = "telemetry:{entity_id}"
_KEY_METRIC = "metric:{ip}"
_CHANNEL_TELEMETRY = "telemetry:{entity_id}"


async def cache_telemetry(entity_id: int, data: dict, ttl: int | None = None) -> None:
    """SET telemetry:{entity_id} with TTL (default 300s)."""
    r = await get_redis()
    if r is None:
        return
    try:
        key = _KEY_TELEMETRY.format(entity_id=entity_id)
        await r.set(key, json.dumps(data, default=str), ex=ttl or _TELEMETRY_TTL)
    except (aioredis.ConnectionError, aioredis.RedisError, OSError) as exc:
        record_stream_fault(
            f"{_COMPONENT}.write", exc, logger=_logger, context={"entity_id": entity_id}
        )
    except Exception as exc:
        record_stream_fault(
            f"{_COMPONENT}.write", exc, logger=_logger, context={"entity_id": entity_id}
        )


async def get_cached_telemetry(entity_id: int) -> dict | None:
    """GET telemetry:{entity_id} — returns parsed dict or None (cache miss / Redis down)."""
    r = await get_redis()
    if r is None:
        return None
    key = _KEY_TELEMETRY.format(entity_id=entity_id)
    try:
        # Guard: key type collision from migration — non-string keys cause WRONGTYPE
        key_type = await r.type(key)
        if key_type not in ("string", "none"):
            await r.delete(key)
            _logger.warning("Nuked corrupt Redis key %s type=%s", key, key_type)
            return None
        raw = await r.get(key)
        if raw is None:
            return None
        return cast(dict[Any, Any], json.loads(raw))
    except (aioredis.ConnectionError, aioredis.RedisError, OSError) as exc:
        record_stream_fault(
            f"{_COMPONENT}.read", exc, logger=_logger, context={"entity_id": entity_id, "key": key}
        )
        return None
    except json.JSONDecodeError as exc:
        record_stream_fault(
            f"{_COMPONENT}.read",
            exc,
            logger=_logger,
            context={"entity_id": entity_id, "key": key},
            fault=FAULT_DECODE,
        )
        try:
            await r.delete(key)
        except Exception as delete_exc:
            # The delete is a best-effort repair of a poisoned key; failing it
            # only means the next read re-detects the same corruption.
            record_stream_fault(f"{_COMPONENT}.read_repair", delete_exc, logger=_logger)
        return None
    except Exception as exc:
        record_stream_fault(
            f"{_COMPONENT}.read", exc, logger=_logger, context={"entity_id": entity_id, "key": key}
        )
        return None


async def cache_live_metric(ip: str, data: dict) -> None:
    """SET metric:{ip} with 60 s TTL."""
    r = await get_redis()
    if r is None:
        return
    try:
        key = _KEY_METRIC.format(ip=ip)
        await r.set(key, json.dumps(data, default=str), ex=_METRIC_TTL)
    except (aioredis.ConnectionError, aioredis.RedisError, OSError) as exc:
        record_stream_fault(f"{_COMPONENT}.metric_write", exc, logger=_logger, context={"ip": ip})
    except Exception as exc:
        record_stream_fault(f"{_COMPONENT}.metric_write", exc, logger=_logger, context={"ip": ip})


async def get_cached_metric(ip: str) -> dict | None:
    """GET metric:{ip} — returns parsed dict or None."""
    r = await get_redis()
    if r is None:
        return None
    key = _KEY_METRIC.format(ip=ip)
    try:
        key_type = await r.type(key)
        if key_type not in ("string", "none"):
            await r.delete(key)
            _logger.warning("Nuked corrupt Redis key %s type=%s", key, key_type)
            return None
        raw = await r.get(key)
        if raw is None:
            return None
        return cast(dict[Any, Any], json.loads(raw))
    except (aioredis.ConnectionError, aioredis.RedisError, OSError) as exc:
        record_stream_fault(
            f"{_COMPONENT}.metric_read", exc, logger=_logger, context={"ip": ip, "key": key}
        )
        return None
    except json.JSONDecodeError as exc:
        record_stream_fault(
            f"{_COMPONENT}.metric_read",
            exc,
            logger=_logger,
            context={"ip": ip, "key": key},
            fault=FAULT_DECODE,
        )
        try:
            await r.delete(key)
        except Exception as delete_exc:
            # The delete is a best-effort repair of a poisoned key; failing it
            # only means the next read re-detects the same corruption.
            record_stream_fault(f"{_COMPONENT}.metric_read_repair", delete_exc, logger=_logger)
        return None
    except Exception as exc:
        record_stream_fault(
            f"{_COMPONENT}.metric_read", exc, logger=_logger, context={"ip": ip, "key": key}
        )
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
    except (aioredis.ConnectionError, aioredis.RedisError, OSError) as exc:
        record_stream_fault(
            f"{_COMPONENT}.publish", exc, logger=_logger, context={"entity_id": entity_id}
        )
    except Exception as exc:
        record_stream_fault(
            f"{_COMPONENT}.publish", exc, logger=_logger, context={"entity_id": entity_id}
        )
