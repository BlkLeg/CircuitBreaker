"""Monitor service: monitor-id CRUD, events, history, and hardware summaries."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.nats_client import nats_client
from app.core.subjects import MONITOR_POLL_ITEM
from app.db.models import (
    DailyUptimeStats,
    Hardware,
    MonitorEvent,
    MonitorItem,
    TelemetryTimeseries,
)
from app.schemas.monitor import MonitorCreate, MonitorUpdate
from app.services.monitoring.state import PENDING

logger = logging.getLogger(__name__)


def _to_dict(
    item: MonitorItem, uptime_pct_24h: float | None = None, latency_ms: float | None = None
) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "check_type": item.check_type,
        "host": item.host,
        "config": item.params or {},
        "interval_secs": item.interval_secs,
        "max_retries": item.max_retries,
        "retry_interval_secs": item.retry_interval_secs,
        "enabled": item.enabled,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "status": item.last_status or PENDING,
        "retries": item.consecutive_failures,
        "last_polled_at": item.last_polled_at,
        "last_status_change_at": item.last_status_change_at,
        "uptime_pct_24h": uptime_pct_24h,
        "latency_ms": latency_ms,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _latest_metric_map(db: Session, item_ids: list[int], metric: str) -> dict[int, float]:
    if not item_ids:
        return {}
    rows = (
        db.query(TelemetryTimeseries)
        .filter(TelemetryTimeseries.item_id.in_(item_ids), TelemetryTimeseries.metric == metric)
        .distinct(TelemetryTimeseries.item_id)
        .order_by(TelemetryTimeseries.item_id, TelemetryTimeseries.ts.desc())
        .all()
    )
    return {r.item_id: r.value for r in rows}


def _uptime_pct_map(db: Session, item_ids: list[int], hours: int = 24) -> dict[int, float]:
    if not item_ids:
        return {}
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = db.execute(
        select(
            TelemetryTimeseries.item_id,
            func.avg(TelemetryTimeseries.value),
        )
        .where(
            TelemetryTimeseries.item_id.in_(item_ids),
            TelemetryTimeseries.metric == "avail",
            TelemetryTimeseries.ts >= since,
        )
        .group_by(TelemetryTimeseries.item_id)
    ).all()
    return {item_id: round(avg * 100, 1) for item_id, avg in rows if avg is not None}


def list_monitors(
    db: Session,
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    enabled: bool | None = None,
) -> list[dict]:
    query = select(MonitorItem).order_by(MonitorItem.name, MonitorItem.id)
    if target_type is not None:
        query = query.where(MonitorItem.target_type == target_type)
    if target_id is not None:
        query = query.where(MonitorItem.target_id == target_id)
    if enabled is not None:
        query = query.where(MonitorItem.enabled == enabled)
    items = list(db.scalars(query).all())
    ids = [i.id for i in items]
    uptimes = _uptime_pct_map(db, ids)
    latencies = _latest_metric_map(db, ids, "latency_ms")
    return [_to_dict(i, uptimes.get(i.id), latencies.get(i.id)) for i in items]


def get_monitor(db: Session, monitor_id: int) -> dict | None:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return None
    uptimes = _uptime_pct_map(db, [item.id])
    latencies = _latest_metric_map(db, [item.id], "latency_ms")
    return _to_dict(item, uptimes.get(item.id), latencies.get(item.id))


def create_monitor(db: Session, payload: MonitorCreate) -> dict:
    item = MonitorItem(
        name=payload.name,
        check_type=payload.check_type,
        host=payload.host,
        params=payload.config,
        interval_secs=payload.interval_secs,
        max_retries=payload.max_retries,
        retry_interval_secs=payload.retry_interval_secs,
        enabled=payload.enabled,
        target_type=payload.target_type,
        target_id=payload.target_id,
        last_status=PENDING,
        next_due_at=datetime.now(UTC),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_dict(item)


def update_monitor(db: Session, monitor_id: int, payload: MonitorUpdate) -> dict | None:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return None
    data = payload.model_dump(exclude_unset=True)
    if "config" in data and data["config"] is not None:
        from app.schemas.monitor import CONFIG_MODELS

        model = CONFIG_MODELS[item.check_type]
        data["config"] = model(**data["config"]).model_dump(exclude_unset=True)
        item.params = data.pop("config")
    for field in (
        "name",
        "host",
        "interval_secs",
        "max_retries",
        "retry_interval_secs",
        "enabled",
        "target_type",
        "target_id",
    ):
        if field in data:
            setattr(item, field, data[field])
    db.commit()
    db.refresh(item)
    return _to_dict(item)


def delete_monitor(db: Session, monitor_id: int) -> bool:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return False
    db.delete(item)
    db.commit()
    return True


def set_paused(db: Session, monitor_id: int, paused: bool) -> dict | None:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return None
    item.enabled = not paused
    if not paused:
        item.next_due_at = datetime.now(UTC)
    db.add(
        MonitorEvent(
            item_id=item.id,
            event_type="paused" if paused else "resumed",
            status_from=item.last_status,
            status_to=item.last_status or PENDING,
            msg="paused by user" if paused else "resumed by user",
        )
    )
    db.commit()
    db.refresh(item)
    return _to_dict(item)


def get_events(db: Session, monitor_id: int, limit: int = 50) -> list[dict]:
    rows = db.scalars(
        select(MonitorEvent)
        .where(MonitorEvent.item_id == monitor_id)
        .order_by(MonitorEvent.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": e.id,
            "monitor_id": e.item_id,
            "event_type": e.event_type,
            "status_from": e.status_from,
            "status_to": e.status_to,
            "msg": e.msg,
            "duration_secs": e.duration_secs,
            "created_at": e.created_at,
        }
        for e in rows
    ]


def get_history(
    db: Session, monitor_id: int, metric: str = "latency_ms", hours: int = 24
) -> list[dict]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        db.query(TelemetryTimeseries)
        .filter(
            TelemetryTimeseries.item_id == monitor_id,
            TelemetryTimeseries.metric == metric,
            TelemetryTimeseries.ts >= since,
        )
        .order_by(TelemetryTimeseries.ts.asc())
        .all()
    )
    return [{"ts": r.ts, "value": r.value} for r in rows]


def get_uptime(db: Session, monitor_id: int) -> dict:
    return {"pct_24h": _uptime_pct_map(db, [monitor_id]).get(monitor_id)}


def run_immediate_check(db: Session, monitor_id: int) -> bool:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return False
    payload = {
        "item_id": item.id,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "host": item.host,
        "check_type": item.check_type,
        "params": item.params,
        "interval_secs": item.interval_secs,
    }
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(nats_client.js_publish(MONITOR_POLL_ITEM, payload))
        return True
    except RuntimeError:
        logger.warning("No running async loop to publish immediate check.")
        return False


# ── Hardware summary view (map + integrations panels) ─────────────────────────
# _synthesize_monitor is retained verbatim from the pre-slice-1 service (it reads
# DailyUptimeStats + latest telemetry per item) and is now exposed only through
# list_hardware_summaries.


def _synthesize_monitor(db: Session, hardware_id: int, items: list[MonitorItem]) -> dict | None:
    if not items:
        return None

    item_ids = [item.id for item in items]

    # Use DISTINCT ON to get the latest value per item_id
    latest_telemetry = (
        db.query(TelemetryTimeseries)
        .filter(TelemetryTimeseries.item_id.in_(item_ids), TelemetryTimeseries.metric == "avail")
        .distinct(TelemetryTimeseries.item_id)
        .order_by(TelemetryTimeseries.item_id, TelemetryTimeseries.ts.desc())
        .all()
    )

    latency_telemetry = (
        db.query(TelemetryTimeseries)
        .filter(
            TelemetryTimeseries.item_id.in_(item_ids),
            TelemetryTimeseries.metric == "latency_ms",
        )
        .distinct(TelemetryTimeseries.item_id)
        .order_by(TelemetryTimeseries.item_id, TelemetryTimeseries.ts.desc())
        .all()
    )

    avail_map = {t.item_id: t for t in latest_telemetry}
    latency_map = {t.item_id: t for t in latency_telemetry}

    icmp_item = next((i for i in items if i.check_type == "icmp"), None)

    last_status = "unknown"
    if icmp_item and icmp_item.id in avail_map:
        last_status = "up" if avail_map[icmp_item.id].value > 0 else "down"
    elif avail_map:
        last_status = "up" if any(t.value > 0 for t in avail_map.values()) else "down"

    latency_ms = None
    if icmp_item and icmp_item.id in latency_map:
        latency_ms = latency_map[icmp_item.id].value
    elif latency_map:
        latency_ms = next(iter(latency_map.values())).value

    last_checked_at = None
    if avail_map:
        valid_ts = [t.ts for t in avail_map.values() if t.ts is not None]
        if valid_ts:
            last_checked_at = max(valid_ts).isoformat()

    uptime_pct_24h = None
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    yesterday_str = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    stats = db.scalars(
        select(DailyUptimeStats).where(
            DailyUptimeStats.hardware_id == hardware_id,
            DailyUptimeStats.date.in_([today_str, yesterday_str]),
        )
    ).all()

    total_mins = sum(s.total_minutes for s in stats)
    if total_mins > 0:
        uptime_pct_24h = round((sum(s.uptime_minutes for s in stats) / total_mins) * 100, 1)

    created_at = min(item.created_at for item in items).isoformat()
    updated_at = max(item.updated_at for item in items).isoformat()
    enabled = any(item.enabled for item in items)
    interval_secs = min(item.interval_secs for item in items)

    return {
        "id": items[0].id,
        "hardware_id": hardware_id,
        "enabled": enabled,
        "interval_secs": interval_secs,
        "probe_methods": [item.check_type for item in items],
        "last_status": last_status,
        "last_checked_at": last_checked_at,
        "latency_ms": latency_ms,
        "consecutive_failures": 0,
        "uptime_pct_24h": uptime_pct_24h,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _hardware_monitors(db: Session, hardware_id: int) -> list[MonitorItem]:
    return list(
        db.scalars(
            select(MonitorItem).where(
                MonitorItem.target_type == "hardware",
                MonitorItem.target_id == hardware_id,
            )
        ).all()
    )


def create_hardware_monitor(db: Session, hardware_id: int, check_type: str = "icmp") -> dict | None:
    """Quick-create a default reachability monitor for a hardware node (map UX).

    Returns the created (or pre-existing) monitor, or None if the hardware is
    unknown or has no IP to probe. Idempotent per (hardware, check_type).
    """
    hw = db.get(Hardware, hardware_id)
    if hw is None or not hw.ip_address:
        return None
    existing = db.scalars(
        select(MonitorItem).where(
            MonitorItem.target_type == "hardware",
            MonitorItem.target_id == hardware_id,
            MonitorItem.check_type == check_type,
        )
    ).first()
    if existing is not None:
        return _to_dict(existing)
    label = hw.name or hw.hostname or hw.ip_address
    item = MonitorItem(
        name=f"{label} ({check_type})",
        check_type=check_type,
        host=hw.ip_address,
        params={"packet_count": 5} if check_type == "icmp" else {},
        interval_secs=60,
        max_retries=0,
        enabled=True,
        target_type="hardware",
        target_id=hardware_id,
        last_status=PENDING,
        next_due_at=datetime.now(UTC),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_dict(item)


def set_hardware_paused(db: Session, hardware_id: int, paused: bool) -> bool:
    """Pause/resume every monitor attached to a hardware node."""
    items = _hardware_monitors(db, hardware_id)
    if not items:
        return False
    now = datetime.now(UTC)
    for item in items:
        item.enabled = not paused
        if not paused:
            item.next_due_at = now
        db.add(
            MonitorEvent(
                item_id=item.id,
                event_type="paused" if paused else "resumed",
                status_from=item.last_status,
                status_to=item.last_status or PENDING,
                msg="paused by user" if paused else "resumed by user",
            )
        )
    db.commit()
    return True


def run_hardware_check(db: Session, hardware_id: int) -> bool:
    """Publish an immediate check for every monitor attached to a hardware node."""
    items = _hardware_monitors(db, hardware_id)
    if not items:
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No running async loop to publish immediate check.")
        return True
    for item in items:
        payload = {
            "item_id": item.id,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "host": item.host,
            "check_type": item.check_type,
            "params": item.params,
            "interval_secs": item.interval_secs,
        }
        loop.create_task(nats_client.js_publish(MONITOR_POLL_ITEM, payload))
    return True


def list_hardware_summaries(db: Session, hardware_ids: list[int] | None = None) -> list[dict]:
    query = select(MonitorItem).where(MonitorItem.target_type == "hardware")
    if hardware_ids is not None:
        query = query.where(MonitorItem.target_id.in_(hardware_ids))
    items = db.scalars(query).all()
    grouped: dict[int, list[MonitorItem]] = {}
    for item in items:
        if item.target_id is not None:
            grouped.setdefault(item.target_id, []).append(item)
    res = []
    for hw_id, hw_items in grouped.items():
        synthesized = _synthesize_monitor(db, hw_id, hw_items)
        if synthesized:
            res.append(synthesized)
    return res
