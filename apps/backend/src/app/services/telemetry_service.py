from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import Hardware, HardwareLiveMetric
from app.schemas.telemetry import TelemetryResponse
from app.services.telemetry_cache import cache_telemetry, get_cached_telemetry, publish_telemetry

_logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60
_NON_LIVE_STATUSES = {"unknown", "unreachable", "error", "unconfigured"}


def _safe_json(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bytes_to_mb(value: Any) -> float | None:
    f = _as_float(value)
    if f is None:
        return None
    return round(f / (1024 * 1024), 2)


def _derive_mem_pct(data: dict[str, Any]) -> float | None:
    mem_pct = _as_float(data.get("mem_pct"))
    if mem_pct is not None:
        return mem_pct
    used = _as_float(data.get("mem_used"))
    total = _as_float(data.get("mem_total"))
    if used is None or total is None or total == 0:
        return None
    return round((used / total) * 100.0, 2)


def _derive_disk_pct(data: dict[str, Any]) -> float | None:
    disk_pct = _as_float(data.get("disk_pct"))
    if disk_pct is not None:
        return disk_pct
    used = _as_float(data.get("rootfs_used") or data.get("disk_used_bytes"))
    total = _as_float(data.get("rootfs_total") or data.get("disk_total_bytes"))
    if used is None or total is None or total == 0:
        return None
    return round((used / total) * 100.0, 2)


def _extract_profile(telemetry_config: Any) -> str | None:
    cfg = _safe_json(telemetry_config)
    if cfg is None:
        return None
    profile = cfg.get("profile")
    return str(profile) if isinstance(profile, str) and profile.strip() else None


def _normalise_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str, str | None]:
    raw_data = payload.get("data")
    data: dict[str, Any]
    if isinstance(raw_data, dict):
        data = raw_data
    else:
        data = {
            k: v
            for k, v in payload.items()
            if k not in {"status", "error", "error_msg", "last_polled", "source", "entity_type"}
        }

    status = str(payload.get("status") or data.get("status") or "unknown")
    error_msg = payload.get("error_msg") or payload.get("error")
    if error_msg is not None:
        error_msg = str(error_msg)
    if error_msg and status == "unknown":
        status = "unreachable"
    return data, status, error_msg


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
        cpu_pct=_as_float(data.get("cpu_pct") or data.get("cpu")),
        mem_pct=_derive_mem_pct(data),
        mem_used_mb=_as_float(data.get("mem_used_mb")) or _bytes_to_mb(data.get("mem_used")),
        mem_total_mb=_as_float(data.get("mem_total_mb")) or _bytes_to_mb(data.get("mem_total")),
        disk_pct=_derive_disk_pct(data),
        temp_c=_as_float(data.get("temp_c") or data.get("cpu_temp")),
        power_w=_as_float(data.get("power_w") or data.get("system_power_w")),
        uptime_s=_as_int(data.get("uptime_s") or data.get("uptime")),
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

    from app.services.status_service import recalculate_hardware_status

    recalculate_hardware_status(db, hardware_id)
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
