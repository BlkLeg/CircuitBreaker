from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import Hardware, HardwareLiveMetric
from app.schemas.telemetry import TelemetryResponse
from app.services.telemetry_cache import cache_telemetry, get_cached_telemetry, publish_telemetry

# The normalization helpers moved to `app.services.telemetry_normalize`, which is
# now the one home for the platform-dict -> HardwareLiveMetric mapping. They are
# re-exported from here so importers that reference their historical home keep
# working (`app/services/monitoring/proxmox_override.py` imports
# `_NON_LIVE_STATUSES`). The `noqa` covers the names this module no longer uses
# itself, which are re-exports rather than dead imports.
from app.services.telemetry_normalize import (  # noqa: F401
    _NON_LIVE_STATUSES,
    _as_float,
    _as_int,
    _bytes_to_mb,
    _derive_disk_pct,
    _derive_mem_pct,
    _normalise_payload,
    live_metric_fields,
)

_logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60


def _safe_json(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _safe_config(telemetry_config: Any) -> dict[str, Any] | None:
    """Parse telemetry_config and return it with password redacted."""
    import json

    if isinstance(telemetry_config, dict):
        cfg = telemetry_config
    elif isinstance(telemetry_config, str):
        try:
            parsed = json.loads(telemetry_config)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        cfg = parsed
    else:
        return None
    return {k: v for k, v in cfg.items() if k != "password"}


def _extract_profile(telemetry_config: Any) -> str | None:
    cfg = _safe_json(telemetry_config)
    if cfg is None:
        return None
    profile = cfg.get("profile")
    return str(profile) if isinstance(profile, str) and profile.strip() else None


def _row_to_payload(row: HardwareLiveMetric) -> dict[str, Any]:
    raw = _safe_json(row.raw) or {}
    if raw:
        return raw
    payload: dict[str, Any] = {}
    if row.cpu_pct is not None:
        payload["cpu_pct"] = row.cpu_pct
    if row.mem_pct is not None:
        payload["mem_pct"] = row.mem_pct
    if row.mem_used_mb is not None:
        payload["mem_used_mb"] = row.mem_used_mb
    if row.mem_total_mb is not None:
        payload["mem_total_mb"] = row.mem_total_mb
    if row.disk_pct is not None:
        payload["disk_pct"] = row.disk_pct
    if row.temp_c is not None:
        payload["temp_c"] = row.temp_c
    if row.power_w is not None:
        payload["power_w"] = row.power_w
    if row.uptime_s is not None:
        payload["uptime_s"] = row.uptime_s
    return payload


async def get_telemetry_for_hardware(hardware_id: int, db: Session) -> TelemetryResponse:
    hw = db.get(Hardware, hardware_id)
    if hw is None:
        raise ValueError(f"Hardware {hardware_id} not found")

    telemetry_profile = _extract_profile(hw.telemetry_config)

    cached: dict[str, Any] | None = None
    try:
        cached = await get_cached_telemetry(hardware_id)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("Telemetry cache read failed hw:%d: %s", hardware_id, exc)

    if cached:
        return TelemetryResponse(
            hardware_id=hardware_id,
            name=hw.name,
            status=str(cached.get("status") or "unknown"),
            data=_safe_json(cached.get("data")) or {},
            source="cache",
            last_polled=hw.telemetry_last_polled,
            error_msg=str(cached.get("error_msg")) if cached.get("error_msg") else None,
            telemetry_profile=telemetry_profile,
            config=_safe_config(hw.telemetry_config),
        )

    row = (
        db.query(HardwareLiveMetric)
        .filter(HardwareLiveMetric.hardware_id == hardware_id)
        .order_by(HardwareLiveMetric.collected_at.desc())
        .first()
    )
    if row is not None:
        payload = _row_to_payload(row)
        response = TelemetryResponse(
            hardware_id=hardware_id,
            name=hw.name,
            status=row.status or "unknown",
            data=payload,
            source="db",
            last_polled=row.collected_at,
            error_msg=row.error_msg,
            telemetry_profile=telemetry_profile,
            config=_safe_config(hw.telemetry_config),
        )
        try:
            await cache_telemetry(
                hardware_id,
                {
                    "data": response.data,
                    "status": response.status,
                    "last_polled": response.last_polled.isoformat()
                    if response.last_polled
                    else None,
                    "error_msg": response.error_msg,
                },
                ttl=_CACHE_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.debug("Telemetry cache backfill failed hw:%d: %s", hardware_id, exc)
        return response

    unconfigured_msg = (
        "No telemetry profile configured."
        if telemetry_profile is None
        else "No telemetry samples collected yet."
    )
    return TelemetryResponse(
        hardware_id=hardware_id,
        name=hw.name,
        status="unconfigured",
        data={},
        source="none",
        last_polled=hw.telemetry_last_polled,
        error_msg=unconfigured_msg,
        telemetry_profile=telemetry_profile,
        config=_safe_config(hw.telemetry_config),
    )


async def write_telemetry(
    hardware_id: int,
    payload: dict[str, Any],
    source: str,
    db: Session,
) -> TelemetryResponse:
    hw = db.get(Hardware, hardware_id)
    if hw is None:
        raise ValueError(f"Hardware {hardware_id} not found")

    data, status, error_msg = _normalise_payload(payload)
    now = utcnow()

    row = HardwareLiveMetric(
        hardware_id=hardware_id,
        collected_at=now,
        **live_metric_fields(data),
        status=status,
        source=source,
        raw=data,
        error_msg=error_msg,
    )
    db.add(row)

    hw.telemetry_data = data
    hw.telemetry_status = status
    hw.telemetry_last_polled = now
    if status not in _NON_LIVE_STATUSES:
        hw.last_seen = now.isoformat()

    db.commit()
    db.refresh(row)

    cache_payload = {
        "data": data,
        "status": status,
        "last_polled": now.isoformat(),
        "source": source,
    }
    if error_msg:
        cache_payload["error_msg"] = error_msg

    try:
        await cache_telemetry(hardware_id, cache_payload, ttl=_CACHE_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("Telemetry cache write failed hw:%d: %s", hardware_id, exc)

    try:
        await publish_telemetry(
            hardware_id,
            {
                **cache_payload,
                "entity_type": "hardware",
                "hardware_id": hardware_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        _logger.debug("Telemetry publish failed hw:%d: %s", hardware_id, exc)

    return TelemetryResponse(
        hardware_id=hardware_id,
        name=hw.name,
        status=status,
        data=data,
        source=source,
        last_polled=row.collected_at,
        error_msg=error_msg,
        telemetry_profile=_extract_profile(hw.telemetry_config),
    )


def purge_old_hardware_live_metrics(db: Session, *, days: int = 7) -> int:
    cutoff = utcnow() - timedelta(days=days)
    deleted = (
        db.query(HardwareLiveMetric)
        .filter(HardwareLiveMetric.collected_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)
