"""CRUD and helpers for status pages, groups, and history."""

import json
import logging
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import Hardware, IntegrationConfig, StatusGroup, StatusHistory, StatusPage
from app.schemas.status import (
    DashboardGroupSnapshot,
    StatusGroupCreate,
    StatusGroupUpdate,
    StatusPageCreate,
    StatusPageUpdate,
)

_logger = logging.getLogger(__name__)


def get_or_create_default_page(db: Session) -> StatusPage:
    """Ensure a default status page exists; create if none."""
    page = db.execute(select(StatusPage).where(StatusPage.slug == "default")).scalar_one_or_none()
    if page is None:
        page = StatusPage(slug="default", name="Default", config=None)
        db.add(page)
        db.commit()
        db.refresh(page)
        _logger.info("Created default status page (slug=default)")
    return page


# ── StatusPage CRUD ──────────────────────────────────────────────────────────


def get_status_page(db: Session, page_id: int) -> StatusPage | None:
    return db.get(StatusPage, page_id)


def list_status_pages(db: Session) -> list[StatusPage]:
    return list(db.execute(select(StatusPage).order_by(StatusPage.id)).scalars().all())


def create_status_page(db: Session, data: StatusPageCreate) -> StatusPage:
    page = StatusPage(
        slug=data.slug,
        name=data.name,
        config=json.dumps(data.config) if data.config is not None else None,
    )
    db.add(page)
    db.commit()
    db.refresh(page)
    return page


def update_status_page(db: Session, page_id: int, data: StatusPageUpdate) -> StatusPage | None:
    page = db.get(StatusPage, page_id)
    if not page:
        return None
    if data.slug is not None:
        page.slug = data.slug
    if data.name is not None:
        page.name = data.name
    if data.config is not None:
        page.config = json.dumps(data.config)
    db.commit()
    db.refresh(page)
    return page


def delete_status_page(db: Session, page_id: int) -> bool:
    page = db.get(StatusPage, page_id)
    if not page:
        return False
    db.delete(page)
    db.commit()
    return True


# ── StatusGroup CRUD ─────────────────────────────────────────────────────────


def get_status_group(db: Session, group_id: int) -> StatusGroup | None:
    return db.get(StatusGroup, group_id)


def list_groups_for_page(db: Session, status_page_id: int) -> list[StatusGroup]:
    return list(
        db.execute(
            select(StatusGroup)
            .where(StatusGroup.status_page_id == status_page_id)
            .order_by(StatusGroup.id)
        )
        .scalars()
        .all()
    )


def create_status_group(db: Session, data: StatusGroupCreate) -> StatusGroup:
    group = StatusGroup(
        status_page_id=data.status_page_id,
        name=data.name,
        nodes=data.nodes,
        services=data.services,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def update_status_group(
    db: Session, group_id: int, data: StatusGroupUpdate, *, add_node: dict | None = None
) -> StatusGroup | None:
    """Update group. If add_node is set (e.g. {"type": "hardware", "id": 1}), append to nodes."""
    group = db.get(StatusGroup, group_id)
    if not group:
        return None
    if data.name is not None:
        group.name = data.name
    if data.nodes is not None:
        group.nodes = data.nodes
    if data.services is not None:
        group.services = data.services
    if add_node is not None:
        nodes = list(group.nodes) if group.nodes else []
        if isinstance(add_node, dict) and "type" in add_node and "id" in add_node:
            key = (add_node["type"], add_node["id"])
            existing_keys = {(n.get("type"), n.get("id")) for n in nodes if isinstance(n, dict)}
            if key not in existing_keys:
                nodes.append(add_node)
                group.nodes = nodes
    db.commit()
    db.refresh(group)
    return group


def delete_status_group(db: Session, group_id: int) -> bool:
    group = db.get(StatusGroup, group_id)
    if not group:
        return False
    db.delete(group)
    db.commit()
    return True


# ── Resolve group entities for polling ──────────────────────────────────────


def resolve_group_entity_ids(group: StatusGroup) -> tuple[list[int], list[int], list[int]]:
    """Return (hardware_ids, compute_unit_ids, service_ids) for the group's nodes and services."""
    hardware_ids: list[int] = []
    compute_unit_ids: list[int] = []
    service_ids: list[int] = list(group.services) if group.services else []
    nodes = group.nodes if group.nodes else []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        t = n.get("type")
        ref_id = n.get("id")
        if ref_id is None:
            continue
        try:
            ref_id = int(ref_id)
        except (TypeError, ValueError):
            continue
        if t == "hardware":
            hardware_ids.append(ref_id)
        elif t == "compute_unit":
            compute_unit_ids.append(ref_id)
        elif t == "service":
            service_ids.append(ref_id)
    return hardware_ids, compute_unit_ids, service_ids


# ── StatusHistory ───────────────────────────────────────────────────────────


def list_history(
    db: Session,
    *,
    group_id: int | None = None,
    range_param: str = "7d",
    limit: int = 100,
    offset: int = 0,
) -> list[StatusHistory]:
    """List history rows; range_param is 1h, 24h, 7d, or 30d."""
    now = utcnow()
    if range_param == "1h":
        since = now - timedelta(hours=1)
    elif range_param == "24h":
        since = now - timedelta(hours=24)
    elif range_param == "30d":
        since = now - timedelta(days=30)
    else:
        since = now - timedelta(days=7)
    q = (
        select(StatusHistory)
        .where(StatusHistory.timestamp >= since)
        .order_by(StatusHistory.timestamp.desc())
    )
    if group_id is not None:
        q = q.where(StatusHistory.group_id == group_id)
    q = q.limit(limit).offset(offset)
    return list(db.execute(q).scalars().all())


def append_history(
    db: Session,
    group_id: int,
    overall_status: str,
    uptime_pct: float,
    *,
    avg_ping: float | None = None,
    metrics: dict | None = None,
    raw_telemetry: dict | None = None,
) -> StatusHistory:
    row = StatusHistory(
        group_id=group_id,
        timestamp=utcnow(),
        overall_status=overall_status,
        uptime_pct=uptime_pct,
        avg_ping=avg_ping,
        metrics=json.dumps(metrics) if metrics is not None else None,
        raw_telemetry=json.dumps(raw_telemetry) if raw_telemetry is not None else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def prune_history_older_than(db: Session, days: int = 30) -> int:
    """Delete history rows older than given days; return count deleted."""
    cutoff = utcnow() - timedelta(days=days)
    from sqlalchemy import delete

    result = db.execute(delete(StatusHistory).where(StatusHistory.timestamp < cutoff))
    deleted = int(cast(Any, result).rowcount or 0)
    db.commit()
    if deleted:
        _logger.info("Pruned %d status_history rows older than %d days", deleted, days)
    return deleted


def get_latest_history_per_group(
    db: Session, limit_per_group: int = 100
) -> dict[int, list[StatusHistory]]:
    """Return map group_id -> list of latest history rows (for dashboard trends)."""
    from sqlalchemy import desc

    all_rows = (
        db.execute(select(StatusHistory).order_by(desc(StatusHistory.timestamp)).limit(5000))
        .scalars()
        .all()
    )
    by_group: dict[int, list[StatusHistory]] = {}
    for row in all_rows:
        if row.group_id not in by_group:
            by_group[row.group_id] = []
        if len(by_group[row.group_id]) < limit_per_group:
            by_group[row.group_id].append(row)
    return by_group


# ── Dashboard snapshot ──────────────────────────────────────────────────────


def get_dashboard_snapshots(db: Session) -> tuple[list[StatusPage], list[DashboardGroupSnapshot]]:
    """Return all pages and each group's latest metrics for dashboard."""
    pages = list_status_pages(db)
    groups = list(db.execute(select(StatusGroup)).scalars().all())
    snapshots: list[DashboardGroupSnapshot] = []
    for g in groups:
        latest = db.execute(
            select(StatusHistory)
            .where(StatusHistory.group_id == g.id)
            .order_by(StatusHistory.timestamp.desc())
            .limit(1)
        ).scalar_one_or_none()
        last_poll = latest.timestamp if latest else None
        overall = latest.overall_status if latest else "unknown"
        uptime = latest.uptime_pct if latest else 0.0
        avg_ping = latest.avg_ping if latest else None
        metrics = latest.metrics if latest and latest.metrics else None
        snapshots.append(
            DashboardGroupSnapshot(
                id=g.id,
                name=g.name,
                status_page_id=g.status_page_id,
                overall_status=overall,
                uptime_pct=uptime,
                avg_ping=avg_ping,
                last_poll=last_poll,
                metrics=metrics,
            )
        )
    return pages, snapshots


# ── Dashboard v2 payload (groups + global + history per group) ─────────────────


def _parse_metrics(v: Any) -> dict | None:
    """Parse metrics from JSON string or return dict as-is."""
    if v is None:
        return None
    if isinstance(v, dict):
        return cast(dict, v)
    if isinstance(v, str) and v.strip():
        try:
            return cast(dict, json.loads(v))
        except json.JSONDecodeError:
            return None
    return None


def _history_point(r: StatusHistory) -> dict:
    """Build a chart-ready history point from a StatusHistory row."""
    metrics = _parse_metrics(r.metrics)
    cpu = None
    mem = None
    if isinstance(metrics, dict) and isinstance(metrics.get("cpu_mem"), list):
        cpus = []
        mems = []
        for item in metrics["cpu_mem"]:
            if isinstance(item, dict) and isinstance(item.get("data"), dict):
                d = item["data"]
                if isinstance(d.get("cpu_pct"), (int, float)):
                    cpus.append(float(d["cpu_pct"]))
                if isinstance(d.get("mem_pct"), (int, float)):
                    mems.append(float(d["mem_pct"]))
        cpu = sum(cpus) / len(cpus) if cpus else None
        mem = sum(mems) / len(mems) if mems else None
    return {
        "ts": r.timestamp.isoformat(),
        "uptime_pct": r.uptime_pct,
        "status": r.overall_status,
        "cpu_pct": cpu,
        "mem_pct": mem,
    }


def _metrics_summary(latest: StatusHistory | None) -> dict | None:
    """Build metrics summary (cpu avg/max, mem, events) from latest history row."""
    if not latest:
        return None
    metrics = _parse_metrics(latest.metrics)
    if not isinstance(metrics, dict):
        return None
    out = {"events": metrics.get("events") or []}
    cpu_mem = metrics.get("cpu_mem") or []
    if isinstance(cpu_mem, list):
        cpus = []
        mems = []
        for item in cpu_mem:
            if isinstance(item, dict) and isinstance(item.get("data"), dict):
                d = item["data"]
                if isinstance(d.get("cpu_pct"), (int, float)):
                    cpus.append(float(d["cpu_pct"]))
                if isinstance(d.get("mem_pct"), (int, float)):
                    mems.append(float(d["mem_pct"]))
        if cpus:
            out["cpu"] = {"avg": round(sum(cpus) / len(cpus), 1), "max": round(max(cpus), 1)}
        if mems:
            out["mem"] = {"avg": round(sum(mems) / len(mems), 1), "max": round(max(mems), 1)}
    return out


def get_dashboard_payload(
    db: Session,
    *,
    group_id: int | None = None,
    range_param: str = "7d",
    limit: int = 100,
) -> tuple[list[dict], dict]:
    """
    Return (groups_list, global_summary_dict) for dashboard v2.
    groups_list: list of DashboardGroupItem-like dicts with id, name, status_page_id,
                 status, uptime, avg_ping, entities, metrics, history, last_poll.
    global_summary_dict: overall_uptime, alerts, total_entities.
    """
    groups_q = select(StatusGroup).order_by(StatusGroup.id)
    if group_id is not None:
        groups_q = groups_q.where(StatusGroup.id == group_id)
    group_list = list(db.execute(groups_q).scalars().all())
    cap = min(limit, 500)
    total_entities = 0
    uptime_sum = 0.0
    uptime_count = 0
    alerts_count = 0
    result_groups = []

    for g in group_list:
        hw_ids, cu_ids, svc_ids = resolve_group_entity_ids(g)
        entity_count = len(hw_ids) + len(cu_ids) + len(svc_ids)
        total_entities += entity_count

        latest_row = (
            db.execute(
                select(StatusHistory)
                .where(StatusHistory.group_id == g.id)
                .order_by(StatusHistory.timestamp.desc())
                .limit(1)
            )
            .scalars()
            .one_or_none()
        )
        last_poll = latest_row.timestamp if latest_row else None
        status = latest_row.overall_status if latest_row else "unknown"
        uptime = latest_row.uptime_pct if latest_row else 0.0
        avg_ping = latest_row.avg_ping if latest_row else None
        metrics_summary = _metrics_summary(latest_row)
        events = (metrics_summary or {}).get("events") or []
        if isinstance(events, list):
            alerts_count += sum(
                1
                for e in events
                if isinstance(e, dict) and e.get("severity") in ("warning", "critical")
            )
        uptime_sum += uptime
        uptime_count += 1

        history_rows = list_history(db, group_id=g.id, range_param=range_param, limit=cap, offset=0)
        history_points = [_history_point(r) for r in reversed(history_rows)]

        # If all nodes in this group are from one Proxmox integration, expose for cluster overview.
        is_proxmox = False
        integration_id: int | None = None
        if hw_ids:
            rows = (
                db.execute(
                    select(Hardware.integration_config_id)
                    .where(
                        Hardware.id.in_(hw_ids),
                        Hardware.integration_config_id.isnot(None),
                    )
                    .distinct()
                )
                .scalars()
                .all()
            )
            config_ids = [r for r in (rows or []) if r is not None]
            if len(config_ids) == 1:
                cfg = db.get(IntegrationConfig, config_ids[0])
                if cfg and cfg.type == "proxmox":
                    is_proxmox = True
                    integration_id = config_ids[0]

        result_groups.append(
            {
                "id": g.id,
                "name": g.name,
                "status_page_id": g.status_page_id,
                "status": status,
                "uptime": uptime,
                "avg_ping": avg_ping,
                "entities": entity_count,
                "metrics": metrics_summary,
                "history": history_points,
                "last_poll": last_poll,
                "is_proxmox": is_proxmox,
                "integration_id": integration_id,
            }
        )

    overall_uptime = round(uptime_sum / uptime_count, 1) if uptime_count else 0.0

    global_summary = {
        "overall_uptime": overall_uptime,
        "alerts": alerts_count,
        "total_entities": total_entities,
    }
    return result_groups, global_summary


def list_events_for_group(
    db: Session,
    group_id: int,
    since_param: str = "7d",
    limit: int = 100,
) -> list[dict]:
    """Return events for a group within the since window (from metrics.events on history rows)."""
    rows = list_history(db, group_id=group_id, range_param=since_param, limit=limit * 2, offset=0)
    seen = set()
    out = []
    for r in reversed(rows):
        metrics = _parse_metrics(r.metrics)
        if not isinstance(metrics, dict):
            continue
        events = metrics.get("events") or []
        if not isinstance(events, list):
            continue
        for e in events:
            if not isinstance(e, dict):
                continue
            ts = e.get("ts") or r.timestamp.isoformat()
            msg = e.get("message") or ""
            sev = e.get("severity") or "info"
            key = (ts, msg)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "ts": ts if isinstance(ts, str) else r.timestamp.isoformat(),
                    "message": msg,
                    "severity": sev,
                }
            )
            if len(out) >= limit:
                break
        if len(out) >= limit:
            break
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:limit]


# ── Available Entities & Bulk Group Assignment (v0.2.0) ──────────────────────


def list_available_entities(
    db: Session,
    *,
    q: str | None = None,
    role: str | None = None,
    status: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """
    UNION hardware + services rows not already assigned to any status group.
    Returns matching entities and total count.
    """

    # We need to find all entities (by type and id) that are already in ANY status group.
    # To do this safely and simply across all DB engines without complex JSONB querying,
    # we just fetch all groups and extract their assigned IDs.
    groups = list(db.execute(select(StatusGroup)).scalars().all())
    assigned_hardware_ids = set()
    assigned_service_ids = set()

    for g in groups:
        hw_ids, _, svcs = resolve_group_entity_ids(g)
        assigned_hardware_ids.update(hw_ids)
        assigned_service_ids.update(svcs)

    # Now fetch target entities
    from app.db.models import Hardware, Service

    entities = []

    # Helper to check if entity passes basic string filters
    def passes_filters(name_val: str | None, role_val: str | None, status_val: str | None) -> bool:
        if q and q.lower() not in (name_val or "").lower():
            return False
        if role and role.lower() != (role_val or "").lower():
            return False
        if status and status.lower() != (status_val or "unknown").lower():
            return False
        return True

    # 1. Hardware
    if entity_type in (None, "hardware"):
        hw_query = select(Hardware)
        for hw in db.execute(hw_query).scalars().all():
            if passes_filters(hw.name, hw.role, hw.status):
                entities.append(
                    {
                        "id": hw.id,
                        "name": hw.name,
                        "type": "hardware",
                        "role": hw.role,
                        "status": hw.status or "unknown",
                        "source": hw.source or "manual",
                        "last_seen": hw.last_seen,
                        "telemetry_summary": None,  # Can be expanded later from telemetry_data
                        "already_grouped": hw.id in assigned_hardware_ids,
                    }
                )

    # 2. Services
    if entity_type in (None, "service"):
        svc_query = select(Service)
        for svc in db.execute(svc_query).scalars().all():
            if passes_filters(svc.name, svc.category, svc.status):
                # Service status usually maps to up/down/degraded
                entities.append(
                    {
                        "id": svc.id,
                        "name": svc.name,
                        "type": "service",
                        "role": svc.category or "service",
                        "status": svc.status or "unknown",
                        "source": "manual" if not svc.is_docker_container else "docker",
                        "last_seen": None,
                        "telemetry_summary": None,
                        "already_grouped": svc.id in assigned_service_ids,
                    }
                )

    # Filter out already grouped before pagination
    unassigned = [e for e in entities if not e["already_grouped"]]

    # Sort unassigned: name asc
    unassigned.sort(key=lambda x: str(x.get("name") or "").lower())

    total = len(unassigned)
    paginated = unassigned[offset : offset + limit]

    return paginated, total


def bulk_create_group(
    db: Session, *, name: str, page_id: int, entity_ids: list[int], entity_type: str
) -> StatusGroup:
    """Create one StatusGroup with nodes built from entity_ids+entity_type."""
    nodes = []
    services = []

    if entity_type == "hardware":
        for eid in entity_ids:
            nodes.append({"type": "hardware", "id": eid})
    elif entity_type == "service":
        for eid in entity_ids:
            services.append(eid)

    data = StatusGroupCreate(
        status_page_id=page_id,
        name=name,
        nodes=nodes,
        services=services,
    )
    return create_status_group(db, data)
