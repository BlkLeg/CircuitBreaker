"""Uptime monitoring service (API handlers for continuous polling engine)."""

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.nats_client import nats_client
from app.db.models import DailyUptimeStats, Hardware, MonitorItem, TelemetryTimeseries

logger = logging.getLogger(__name__)


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
        last_checked_at = max(t.ts for t in avail_map.values()).isoformat()

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


def list_monitors(db: Session, hardware_ids: list[int] | None = None) -> list[dict]:
    query = select(MonitorItem).order_by(MonitorItem.target_id)
    if hardware_ids is not None:
        query = query.where(
            MonitorItem.target_type == "hardware",
            MonitorItem.target_id.in_(hardware_ids),
        )
    items = db.scalars(query).all()
    grouped = {}
    for item in items:
        if item.target_type == "hardware" and item.target_id is not None:
            grouped.setdefault(item.target_id, []).append(item)

    res = []
    for hw_id, hw_items in grouped.items():
        synthesized = _synthesize_monitor(db, hw_id, hw_items)
        if synthesized:
            res.append(synthesized)
    return res


def get_monitor(db: Session, hardware_id: int) -> dict | None:
    items = db.scalars(
        select(MonitorItem).where(
            MonitorItem.target_type == "hardware", MonitorItem.target_id == hardware_id
        )
    ).all()
    return _synthesize_monitor(db, hardware_id, list(items))


def create_monitor(
    db: Session,
    hardware_id: int,
    probe_methods: list[str] | None = None,
    interval_secs: int = 60,
    enabled: bool = True,
) -> dict | None:
    hw = db.get(Hardware, hardware_id)
    if not hw or not hw.ip_address:
        return None

    methods = probe_methods or ["icmp", "tcp", "http"]
    now = datetime.now(UTC)

    created_items = []
    for method in methods:
        item = MonitorItem(
            target_type="hardware",
            target_id=hardware_id,
            host=hw.ip_address,
            check_type=method,
            params={"packet_count": 5} if method == "icmp" else {},
            interval_secs=interval_secs,
            enabled=enabled,
            next_due_at=now,
        )
        db.add(item)
        created_items.append(item)

    db.commit()
    for item in created_items:
        db.refresh(item)

    return _synthesize_monitor(db, hardware_id, created_items)


def update_monitor(
    db: Session,
    hardware_id: int,
    *,
    enabled: bool | None = None,
    interval_secs: int | None = None,
    probe_methods: list[str] | None = None,
) -> dict | None:
    items = db.scalars(
        select(MonitorItem).where(
            MonitorItem.target_type == "hardware", MonitorItem.target_id == hardware_id
        )
    ).all()
    if not items:
        return None

    hw = db.get(Hardware, hardware_id)
    if not hw or not hw.ip_address:
        return None

    existing_methods = {item.check_type: item for item in items}
    now = datetime.now(UTC)

    if probe_methods is not None:
        for method, item in existing_methods.items():
            if method not in probe_methods:
                db.delete(item)

        for method in probe_methods:
            if method not in existing_methods:
                fallback_interval = 60
                fallback_enabled = True
                if existing_methods:
                    first_item = next(iter(existing_methods.values()))
                    fallback_interval = first_item.interval_secs
                    fallback_enabled = first_item.enabled

                new_item = MonitorItem(
                    target_type="hardware",
                    target_id=hardware_id,
                    host=hw.ip_address,
                    check_type=method,
                    params={"packet_count": 5} if method == "icmp" else {},
                    interval_secs=(
                        interval_secs if interval_secs is not None else fallback_interval
                    ),
                    enabled=enabled if enabled is not None else fallback_enabled,
                    next_due_at=now,
                )
                db.add(new_item)
                existing_methods[method] = new_item

    for item in existing_methods.values():
        if enabled is not None:
            item.enabled = enabled
        if interval_secs is not None:
            item.interval_secs = interval_secs

    db.commit()

    items_after = db.scalars(
        select(MonitorItem).where(
            MonitorItem.target_type == "hardware", MonitorItem.target_id == hardware_id
        )
    ).all()

    return _synthesize_monitor(db, hardware_id, list(items_after))


def delete_monitor(db: Session, hardware_id: int) -> bool:
    items = db.scalars(
        select(MonitorItem).where(
            MonitorItem.target_type == "hardware", MonitorItem.target_id == hardware_id
        )
    ).all()
    if not items:
        return False

    for item in items:
        db.delete(item)
    db.commit()
    return True


def get_history(db: Session, hardware_id: int, limit: int = 100) -> list[dict]:
    items = db.scalars(
        select(MonitorItem).where(
            MonitorItem.target_type == "hardware", MonitorItem.target_id == hardware_id
        )
    ).all()
    if not items:
        return []

    item_ids = [i.id for i in items]

    telemetry = (
        db.query(TelemetryTimeseries)
        .filter(TelemetryTimeseries.item_id.in_(item_ids), TelemetryTimeseries.metric == "avail")
        .order_by(TelemetryTimeseries.ts.desc())
        .limit(limit)
        .all()
    )

    res = []
    for t in telemetry:
        item = next((i for i in items if i.id == t.item_id), None)
        method = item.check_type if item else "unknown"
        res.append(
            {
                "id": t.id,
                "hardware_id": hardware_id,
                "status": "up" if t.value > 0 else "down",
                "latency_ms": None,
                "probe_method": method,
                "checked_at": t.ts.isoformat(),
            }
        )
    return res


def run_immediate_check(db: Session, hardware_id: int) -> None:
    items = db.scalars(
        select(MonitorItem).where(
            MonitorItem.target_type == "hardware", MonitorItem.target_id == hardware_id
        )
    ).all()

    if not items:
        return

    import asyncio

    try:
        loop = asyncio.get_running_loop()
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
            loop.create_task(nats_client.js_publish("mon.poll.item", json.dumps(payload).encode()))
    except RuntimeError:
        logger.warning("No running async loop to publish immediate check.")
