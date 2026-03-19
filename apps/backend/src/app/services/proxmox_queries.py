"""Proxmox read-only queries — connection testing, sync status, cluster overview."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import (
    ComputeUnit,
    Hardware,
    IntegrationConfig,
    ProxmoxDiscoverRun,
    StatusGroup,
    Storage,
    TelemetryTimeseries,
)
from app.services.proxmox_client import (
    _get_client,
    _proxmox_error_message,
)

_logger = logging.getLogger(__name__)


def list_proxmox_discover_runs(
    db: Session,
    integration_id: int | None = None,
    limit: int = 100,
) -> list[ProxmoxDiscoverRun]:
    """List Proxmox discovery runs, most recent first."""
    q = db.query(ProxmoxDiscoverRun).order_by(ProxmoxDiscoverRun.created_at.desc())
    if integration_id is not None:
        q = q.filter(ProxmoxDiscoverRun.integration_id == integration_id)
    return q.limit(limit).all()


def get_proxmox_discover_run(db: Session, run_id: int) -> ProxmoxDiscoverRun | None:
    """Return a single Proxmox discovery run by id."""
    return db.query(ProxmoxDiscoverRun).filter(ProxmoxDiscoverRun.id == run_id).first()


async def test_connection(db: Session, config: IntegrationConfig) -> dict:
    try:
        client = _get_client(db, config)
        result = await client.test_connection()
        return {"ok": True, **result}
    except Exception as e:
        err_msg = _proxmox_error_message(e)
        return {"ok": False, "error": err_msg}


def get_sync_status(db: Session, config: IntegrationConfig) -> dict:
    nodes_count = (
        db.query(Hardware)
        .filter(
            Hardware.integration_config_id == config.id,
        )
        .count()
    )
    vms_count = (
        db.query(ComputeUnit)
        .filter(
            ComputeUnit.integration_config_id == config.id,
            ComputeUnit.proxmox_type == "qemu",
        )
        .count()
    )
    cts_count = (
        db.query(ComputeUnit)
        .filter(
            ComputeUnit.integration_config_id == config.id,
            ComputeUnit.proxmox_type == "lxc",
        )
        .count()
    )
    storage_count = (
        db.query(Storage)
        .filter(
            Storage.integration_config_id == config.id,
        )
        .count()
    )

    return {
        "integration_id": config.id,
        "last_sync_at": config.last_sync_at,
        "last_sync_status": config.last_sync_status,
        "cluster_name": config.cluster_name,
        "nodes_count": nodes_count,
        "vms_count": vms_count,
        "cts_count": cts_count,
        "storage_count": storage_count,
    }


async def get_cluster_overview(db: Session, integration_id: int) -> dict[str, Any]:
    """Build cluster overview payload for Proxmox dashboard.

    Covers: cluster info, problems, time-series, storage.
    Uses live PVE API for cluster status and DB for telemetry/storage/events.
    """
    from app.services import status_page_service as svc_status

    config = db.get(IntegrationConfig, integration_id)
    if not config or config.type != "proxmox":
        return {
            "cluster": {
                "name": "",
                "quorum": False,
                "nodes_online": 0,
                "nodes_total": 0,
                "vms": 0,
                "lxcs": 0,
                "uptime": "",
            },
            "problems": [],
            "time_series": {"cpu": {}, "memory": {}, "network_in": {}, "network_out": {}},
            "storage": [],
        }

    try:
        client = _get_client(db, config)
    except Exception as e:
        _logger.warning("Cluster overview: no client for integration %d: %s", integration_id, e)
        return {
            "cluster": {
                "name": "",
                "quorum": False,
                "nodes_online": 0,
                "nodes_total": 0,
                "vms": 0,
                "lxcs": 0,
                "uptime": "",
            },
            "problems": [],
            "time_series": {"cpu": {}, "memory": {}, "network_in": {}, "network_out": {}},
            "storage": [],
        }

    nodes = (
        db.query(Hardware)
        .filter(
            Hardware.integration_config_id == integration_id,
            Hardware.proxmox_node_name.isnot(None),
        )
        .all()
    )
    node_ids = [hw.id for hw in nodes]
    node_id_to_name = {hw.id: (hw.proxmox_node_name or f"hw-{hw.id}") for hw in nodes}

    def _boolish(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "online", "ok"}
        return False

    # Cluster status from PVE (with circuit breaker to avoid overwhelming a down host)
    cluster_name = config.cluster_name or ""
    quorum = False
    nodes_online = 0
    nodes_total = 0
    try:
        from app.core.circuit_breaker import call_with_circuit_breaker

        cs_list = await call_with_circuit_breaker(
            f"proxmox:{integration_id}:cluster",
            lambda: client.get_cluster_status(),
            fallback=[],
        )
        for item in cs_list or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "cluster":
                cluster_name = item.get("name") or cluster_name
                # Proxmox commonly reports integer quorate (1/0); prefer it when present.
                if "quorate" in item:
                    quorum = _boolish(item.get("quorate"))
                else:
                    quorum = _boolish(item.get("quorum", 0))
            elif item.get("type") == "node":
                nodes_total += 1
                node_status = str(item.get("status", "")).strip().lower()
                if node_status == "online" or _boolish(item.get("online", 0)):
                    nodes_online += 1
    except Exception as e:
        _logger.debug("Cluster status fetch failed: %s", e)

    vms = (
        db.query(ComputeUnit)
        .filter(
            ComputeUnit.integration_config_id == integration_id,
            ComputeUnit.proxmox_type == "qemu",
        )
        .count()
    )
    lxcs = (
        db.query(ComputeUnit)
        .filter(
            ComputeUnit.integration_config_id == integration_id,
            ComputeUnit.proxmox_type == "lxc",
        )
        .count()
    )

    uptime_str = ""
    if nodes:
        try:
            td = json.loads(nodes[0].telemetry_data or "{}") if nodes[0].telemetry_data else {}  # type: ignore[arg-type]
            uptime_s = td.get("uptime_s", 0)
            if uptime_s:
                d = int(uptime_s) // 86400
                h = (int(uptime_s) % 86400) // 3600
                m = (int(uptime_s) % 3600) // 60
                uptime_str = f"{d}d {h}h {m}m"
        except Exception:
            pass

    # Time-series from TelemetryTimeseries (last 24h)
    since_ts = utcnow() - timedelta(hours=24)
    rows = (
        db.execute(
            select(TelemetryTimeseries)
            .where(
                TelemetryTimeseries.entity_type == "hardware",
                TelemetryTimeseries.entity_id.in_(node_ids),
                TelemetryTimeseries.ts >= since_ts,
                TelemetryTimeseries.metric.in_(
                    [
                        "cpu_pct",
                        "mem_used_gb",
                        "netin",
                        "netout",
                        "rrd_cpu",
                        "rrd_memused",
                        "rrd_netin",
                        "rrd_netout",
                    ]
                ),
            )
            .order_by(TelemetryTimeseries.ts.asc())
        )
        .scalars()
        .all()
    )
    cpu_series: dict[str, list[dict[str, float | str]]] = {}
    mem_series: dict[str, list[dict[str, float | str]]] = {}
    netin_series: dict[str, list[dict[str, float | str]]] = {}
    netout_series: dict[str, list[dict[str, float | str]]] = {}
    for r in rows:
        node_name = node_id_to_name.get(r.entity_id, f"hw-{r.entity_id}")
        ts_str = r.ts.isoformat() if r.ts else ""
        point = {"time": ts_str, "value": r.value}
        if r.metric in ("cpu_pct", "rrd_cpu"):
            cpu_series.setdefault(node_name, []).append(point)  # type: ignore[arg-type]
        elif r.metric in ("mem_used_gb", "rrd_memused"):
            mem_series.setdefault(node_name, []).append(point)  # type: ignore[arg-type]
        elif r.metric in ("netin", "rrd_netin"):
            netin_series.setdefault(node_name, []).append(point)  # type: ignore[arg-type]
        elif r.metric in ("netout", "rrd_netout"):
            netout_series.setdefault(node_name, []).append(point)  # type: ignore[arg-type]

    # Storage
    storage_rows = db.query(Storage).filter(Storage.integration_config_id == integration_id).all()
    storage_list = []
    for st in storage_rows:
        content = (st.notes or "").replace("content: ", "") if st.notes else ""
        storage_list.append(
            {
                "name": st.name or "",
                "used_gb": float(st.used_gb) if st.used_gb is not None else None,
                "total_gb": float(st.capacity_gb) if st.capacity_gb is not None else None,
                "content": content,
            }
        )

    # Problems: events from status groups that contain any of our nodes
    problems_list: list[dict[str, str]] = []
    seen_problems: set[tuple[str, str]] = set()
    try:
        all_groups = list(db.execute(select(StatusGroup)).scalars().all())
        for g in all_groups:
            hw_ids, _, _ = svc_status.resolve_group_entity_ids(g)
            if not any(hid in node_ids for hid in hw_ids):
                continue
            events = svc_status.list_events_for_group(db, g.id, since_param="7d", limit=50)
            for ev in events:
                ts = ev.get("ts") or ev.get("timestamp", "")
                msg = ev.get("message", "")
                key = (str(ts), msg)
                if key in seen_problems:
                    continue
                seen_problems.add(key)
                severity = ev.get("severity", "info")
                problems_list.append(
                    {
                        "time": ts[:19] if isinstance(ts, str) and len(ts) > 19 else str(ts),
                        "severity": severity.title(),
                        "host": "",  # could resolve from event if we store host
                        "problem": msg,
                        "status": "RESOLVED" if severity == "info" else "PROBLEM",
                    }
                )
        problems_list.sort(key=lambda x: x.get("time", ""), reverse=True)
        problems_list = problems_list[:100]
    except Exception as e:
        _logger.debug("Problems aggregation failed: %s", e)

    return {
        "cluster": {
            "name": cluster_name,
            "quorum": quorum,
            "nodes_online": nodes_online,
            "nodes_total": nodes_total,
            "vms": vms,
            "lxcs": lxcs,
            "uptime": uptime_str,
        },
        "problems": problems_list,
        "time_series": {
            "cpu": cpu_series,
            "memory": mem_series,
            "network_in": netin_series,
            "network_out": netout_series,
        },
        "storage": storage_list,
    }
