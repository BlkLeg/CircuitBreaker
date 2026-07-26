"""Monitor service: monitor-id CRUD, events, history, and per-target rollups."""

import asyncio
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import NamedTuple
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.nats_client import nats_client
from app.core.subjects import MONITOR_POLL_ITEM
from app.db.models import (
    ComputeUnit,
    ExternalNode,
    Hardware,
    MonitorEvent,
    MonitorItem,
    Service,
    TelemetryTimeseries,
)
from app.schemas.monitor import CONFIG_MODELS, MonitorCreate, MonitorUpdate
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
    return {r.item_id: r.value for r in rows if r.item_id is not None}


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


def _latency_series_map(db: Session, item_ids: list[int], limit: int) -> dict[int, list[float]]:
    """Last `limit` latency samples per monitor, oldest → newest (sparkline order)."""
    if not item_ids:
        return {}
    ranked = (
        select(
            TelemetryTimeseries.item_id,
            TelemetryTimeseries.value,
            TelemetryTimeseries.ts,
            func.row_number()
            .over(
                partition_by=TelemetryTimeseries.item_id,
                order_by=TelemetryTimeseries.ts.desc(),
            )
            .label("rn"),
        )
        .where(
            TelemetryTimeseries.item_id.in_(item_ids),
            TelemetryTimeseries.metric == "latency_ms",
        )
        .subquery()
    )
    rows = db.execute(
        select(ranked.c.item_id, ranked.c.value)
        .where(ranked.c.rn <= limit)
        .order_by(ranked.c.item_id, ranked.c.ts.asc())
    ).all()
    series: dict[int, list[float]] = {}
    for item_id, value in rows:
        series.setdefault(item_id, []).append(value)
    return series


def _recent_checks_map(db: Session, item_ids: list[int], limit: int) -> dict[int, list[dict]]:
    """Last `limit` events per monitor, newest first — the shape CheckHistoryBar takes."""
    if not item_ids:
        return {}
    ranked = (
        select(
            MonitorEvent.id,
            MonitorEvent.item_id,
            MonitorEvent.status_to,
            MonitorEvent.msg,
            MonitorEvent.created_at,
            func.row_number()
            .over(partition_by=MonitorEvent.item_id, order_by=MonitorEvent.created_at.desc())
            .label("rn"),
        )
        .where(MonitorEvent.item_id.in_(item_ids))
        .subquery()
    )
    rows = db.execute(
        select(
            ranked.c.id,
            ranked.c.item_id,
            ranked.c.status_to,
            ranked.c.msg,
            ranked.c.created_at,
        )
        .where(ranked.c.rn <= limit)
        .order_by(ranked.c.item_id, ranked.c.created_at.desc())
    ).all()
    checks: dict[int, list[dict]] = {}
    for ev_id, item_id, status_to, msg, created_at in rows:
        checks.setdefault(item_id, []).append(
            {"id": ev_id, "status_to": status_to, "msg": msg, "created_at": created_at}
        )
    return checks


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


def list_overview(db: Session, *, latency_points: int = 12, check_points: int = 20) -> list[dict]:
    """Everything the monitors dashboard renders, in one round trip.

    Four bulk queries regardless of monitor count — the page it feeds used to
    fetch events per monitor.
    """
    items = list(db.scalars(select(MonitorItem).order_by(MonitorItem.name, MonitorItem.id)).all())
    if not items:
        return []
    ids = [i.id for i in items]
    uptimes = _uptime_pct_map(db, ids)
    latencies = _latest_metric_map(db, ids, "latency_ms")
    series = _latency_series_map(db, ids, latency_points)
    checks = _recent_checks_map(db, ids, check_points)
    return [
        {
            **_to_dict(item, uptimes.get(item.id), latencies.get(item.id)),
            "latency_series": series.get(item.id, []),
            "recent_checks": checks.get(item.id, []),
        }
        for item in items
    ]


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


# ── Target-scoped monitors (inventory pages, map, discovery) ──────────────────
# One monitor "target" is an inventory entity: a hardware node, a compute unit,
# a service, or an external node. Resolving one yields everything needed to spin
# up a sensible default monitor for it. Drives the inventory list pages, the
# detail drawers, the map, and discovery auto-monitoring.

_DEFAULT_ICMP_CONFIG = {"packet_count": 5}


class TargetInfo(NamedTuple):
    """A probeable inventory entity, reduced to what a monitor needs."""

    label: str
    host: str
    check_type: str
    config: dict


def _resolve_hardware(db: Session, target_id: int) -> TargetInfo | None:
    hw = db.get(Hardware, target_id)
    if hw is None:
        return None
    host = hw.ip_address or hw.hostname
    if not host:
        return None
    label = hw.name or hw.hostname or host
    return TargetInfo(label, host, "icmp", dict(_DEFAULT_ICMP_CONFIG))


def _resolve_compute_unit(db: Session, target_id: int) -> TargetInfo | None:
    cu = db.get(ComputeUnit, target_id)
    if cu is None or not cu.ip_address:
        return None
    return TargetInfo(cu.name or cu.ip_address, cu.ip_address, "icmp", dict(_DEFAULT_ICMP_CONFIG))


def _resolve_external_node(db: Session, target_id: int) -> TargetInfo | None:
    """External nodes keep an IP *or* a hostname in ip_address — both probe the same."""
    node = db.get(ExternalNode, target_id)
    if node is None or not node.ip_address:
        return None
    return TargetInfo(
        node.name or node.ip_address, node.ip_address, "icmp", dict(_DEFAULT_ICMP_CONFIG)
    )


def _service_port(svc: Service) -> int | None:
    """First port declared on a service — structured ports_json wins over free text."""
    try:
        entries = json.loads(svc.ports_json) if svc.ports_json else []
    except (TypeError, ValueError):
        entries = []
    for entry in entries if isinstance(entries, list) else []:
        port = entry.get("port") if isinstance(entry, dict) else entry
        try:
            if port is not None and 1 <= int(port) <= 65535:
                return int(port)
        except (TypeError, ValueError):
            continue
    # Free-text fallback: "8080", "8080/tcp", "80,443", "8080:80"
    for chunk in re.split(r"[,\s]+", svc.ports or ""):
        digits = chunk.split(":")[0].split("/")[0]
        if digits.isdigit() and 1 <= int(digits) <= 65535:
            return int(digits)
    return None


def _resolve_service(db: Session, target_id: int) -> TargetInfo | None:
    svc = db.get(Service, target_id)
    if svc is None:
        return None
    label = svc.name or svc.slug
    if svc.url:
        host = urlparse(svc.url).hostname or svc.ip_address
        if host:
            return TargetInfo(label, host, "http", {"url": svc.url})
    if svc.ip_address:
        port = _service_port(svc)
        if port is not None:
            return TargetInfo(label, svc.ip_address, "tcp", {"port": port})
        return TargetInfo(label, svc.ip_address, "icmp", dict(_DEFAULT_ICMP_CONFIG))
    return None


_TARGET_RESOLVERS = {
    "hardware": _resolve_hardware,
    "compute_unit": _resolve_compute_unit,
    "service": _resolve_service,
    "external_node": _resolve_external_node,
}


def resolve_target(db: Session, target_type: str, target_id: int) -> TargetInfo | None:
    """Return probe details for an inventory entity, or None if it can't be probed."""
    resolver = _TARGET_RESOLVERS.get(target_type)
    return resolver(db, target_id) if resolver else None


def _target_monitors(db: Session, target_type: str, target_id: int) -> list[MonitorItem]:
    return list(
        db.scalars(
            select(MonitorItem)
            .where(
                MonitorItem.target_type == target_type,
                MonitorItem.target_id == target_id,
            )
            .order_by(MonitorItem.id)
        ).all()
    )


def _build_target_monitor(
    db: Session,
    target_type: str,
    target_id: int,
    check_type: str | None = None,
    config: dict | None = None,
) -> MonitorItem | None:
    """Add a default monitor for an inventory entity — flushes, does NOT commit.

    Idempotent per (target_type, target_id, check_type): an existing monitor is
    returned untouched. Returns None when the target is unknown or has no address
    to probe. Callers that own the surrounding transaction (discovery merge) use
    this directly; everyone else goes through create_target_monitor().
    """
    info = resolve_target(db, target_type, target_id)
    if info is None:
        return None
    check_type = check_type or info.check_type
    if config is not None:
        # Same per-type validation the generic create path applies.
        params = CONFIG_MODELS[check_type](**config).model_dump(exclude_unset=True)
    else:
        # The resolver's config only describes its own check type.
        params = dict(info.config) if check_type == info.check_type else {}
    existing = db.scalars(
        select(MonitorItem).where(
            MonitorItem.target_type == target_type,
            MonitorItem.target_id == target_id,
            MonitorItem.check_type == check_type,
        )
    ).first()
    if existing is not None:
        return existing
    item = MonitorItem(
        name=f"{info.label} ({check_type})",
        check_type=check_type,
        host=info.host,
        params=params,
        interval_secs=60,
        max_retries=0,
        enabled=True,
        target_type=target_type,
        target_id=target_id,
        last_status=PENDING,
        next_due_at=datetime.now(UTC),
    )
    db.add(item)
    db.flush()
    return item


def create_target_monitor(
    db: Session,
    target_type: str,
    target_id: int,
    check_type: str | None = None,
    config: dict | None = None,
) -> dict | None:
    """Quick-create a default monitor for an inventory entity and commit it."""
    item = _build_target_monitor(db, target_type, target_id, check_type, config)
    if item is None:
        return None
    db.commit()
    db.refresh(item)
    return _to_dict(item)


def set_target_paused(db: Session, target_type: str, target_id: int, paused: bool) -> bool:
    """Pause/resume every monitor attached to an inventory entity."""
    items = _target_monitors(db, target_type, target_id)
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


def run_target_check(db: Session, target_type: str, target_id: int) -> bool:
    """Publish an immediate check for every monitor attached to an inventory entity."""
    items = _target_monitors(db, target_type, target_id)
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


def list_target_summaries(
    db: Session, target_type: str, target_ids: list[int] | None = None
) -> list[dict]:
    """One rollup row per inventory entity that has monitors, for the list pages."""
    query = select(MonitorItem).where(MonitorItem.target_type == target_type)
    if target_ids is not None:
        if not target_ids:
            return []
        query = query.where(MonitorItem.target_id.in_(target_ids))
    items = list(db.scalars(query.order_by(MonitorItem.id)).all())
    if not items:
        return []

    uptimes = _uptime_pct_map(db, [i.id for i in items])
    latencies = _latest_metric_map(db, [i.id for i in items], "latency_ms")

    grouped: dict[int, list[MonitorItem]] = {}
    for item in items:
        if item.target_id is not None:
            grouped.setdefault(item.target_id, []).append(item)

    summaries = []
    for target_id, group in grouped.items():
        primary = group[0]  # lowest id — the monitor auto-created for this target
        statuses = {i.last_status or PENDING for i in group}
        if "down" in statuses:
            status = "down"
        elif "up" in statuses:
            status = "up"
        else:
            status = primary.last_status or PENDING
        summaries.append(
            {
                "target_type": target_type,
                "target_id": target_id,
                "monitor_id": primary.id,
                "monitor_ids": [i.id for i in group],
                "enabled": any(i.enabled for i in group),
                "status": status,
                "latency_ms": latencies.get(primary.id),
                "uptime_pct_24h": uptimes.get(primary.id),
                "last_polled_at": max(
                    (i.last_polled_at for i in group if i.last_polled_at is not None),
                    default=None,
                ),
            }
        )
    return summaries
