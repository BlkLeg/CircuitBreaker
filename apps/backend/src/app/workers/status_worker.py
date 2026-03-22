"""Status page polling worker: aggregate telemetry per group and write history."""

import json
import logging
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import (
    ComputeUnit,
    DailyUptimeStats,
    Hardware,
    IntegrationMonitor,
    LiveMetric,
    Service,
    StatusGroup,
    StatusHistory,
)
from app.db.session import SessionLocal
from app.services import status_page_service as svc

_logger = logging.getLogger(__name__)

_STATUS_UP = {"up", "online", "healthy", "running"}
_STATUS_DEGRADED = {"degraded", "maintenance"}

# Thresholds for event detection
_CPU_HIGH_PCT = 90
_DOWN_MINUTES_ALERT = 5

_MONITOR_STATUS_MAP = {
    "up": "up",
    "down": "down",
    "pending": "unknown",
    "maintenance": "degraded",
}


def _entity_status(
    db: Session, group: StatusGroup
) -> tuple[list[str], float, list[dict], float | None]:
    """Return (list of status strings, uptime_pct_approx, metrics list, avg_ping)."""
    hw_ids, cu_ids, svc_ids, monitor_ids = svc.resolve_group_entity_ids(group)
    statuses: list[str] = []
    metrics: list[dict] = []
    ping_sum: float = 0.0
    ping_count: int = 0
    uptime_minutes_total = 0
    total_minutes_total = 0

    for hid in hw_ids:
        hw = db.get(Hardware, hid)
        if hw:
            s = (hw.telemetry_status or hw.status or "unknown").lower()
            statuses.append(s)
            if hw.telemetry_data:
                try:
                    data = (
                        hw.telemetry_data
                        if isinstance(hw.telemetry_data, dict)
                        else json.loads(hw.telemetry_data)
                    )
                    if isinstance(data, dict):
                        metrics.append({"type": "hardware", "id": hid, "data": data})
                except Exception as e:
                    _logger.debug(
                        "Status worker: parse telemetry_data for hw %s: %s", hid, e, exc_info=True
                    )
            # Daily uptime for this hardware
            today = utcnow().date().isoformat()
            row = db.execute(
                select(DailyUptimeStats).where(
                    DailyUptimeStats.hardware_id == hid,
                    DailyUptimeStats.date == today,
                )
            ).scalar_one_or_none()
            if row:
                total_minutes_total += row.total_minutes
                uptime_minutes_total += row.uptime_minutes
            # LiveMetric by node_id hw-{id}
            lm = db.execute(
                select(LiveMetric).where(LiveMetric.node_id == f"hw-{hid}")
            ).scalar_one_or_none()
            if lm and lm.status == "up":
                ping_count += 1  # no actual ping ms in LiveMetric; we just count up

    for cid in cu_ids:
        cu = db.get(ComputeUnit, cid)
        if cu:
            s = (cu.status or "unknown").lower()
            statuses.append(s)

    for sid in svc_ids:
        sv = db.get(Service, sid)
        if sv:
            # Service may have status from relation or derived
            s = getattr(sv, "status", None) or "unknown"
            if hasattr(s, "lower"):
                s = s.lower()
            statuses.append(str(s))

    for mid in monitor_ids:
        mon = db.get(IntegrationMonitor, mid)
        if mon:
            cb_status = _MONITOR_STATUS_MAP.get(mon.status or "pending", "unknown")
            statuses.append(cb_status)
            # Contribute uptime_7d to uptime pool if DailyUptimeStats has no data
            if mon.uptime_7d is not None and total_minutes_total == 0:
                # Convert 7d uptime % to equivalent minutes out of a 7-day window
                week_minutes = 7 * 24 * 60
                uptime_minutes_total += int(week_minutes * mon.uptime_7d / 100)
                total_minutes_total += week_minutes

    n = len(statuses)
    up_count = sum(1 for s in statuses if s in _STATUS_UP)

    if n == 0:
        uptime_pct = 0.0
    elif total_minutes_total > 0:
        uptime_pct = 100.0 * uptime_minutes_total / total_minutes_total
    else:
        uptime_pct = 100.0 * up_count / n if n else 0.0

    avg_ping = (ping_sum / ping_count) if ping_count else None
    return statuses, uptime_pct, metrics, avg_ping


def _overall_status(statuses: list[str], uptime_pct: float) -> str:
    if not statuses:
        return "unknown"
    n = len(statuses)
    up_count = sum(1 for s in statuses if s in _STATUS_UP)
    if up_count >= 0.9 * n or uptime_pct >= 90:
        return "up"
    if up_count >= 0.7 * n or (70 <= uptime_pct < 90):
        return "degraded"
    return "down"


def _detect_events(
    group_id: int,
    overall: str,
    metrics_list: list[Any],
    previous_row: StatusHistory | None,
) -> list[dict]:
    """Build events for threshold breaches: cpu > 90%, down > 5 min."""
    now = utcnow()
    ts_iso = now.isoformat()
    events: list[dict] = []

    # CPU high: any entity in cpu_mem with cpu_pct > threshold
    for item in metrics_list or []:
        if not isinstance(item, dict):
            continue
        data = item.get("data")
        if not isinstance(data, dict):
            continue
        cpu = data.get("cpu_pct")
        if isinstance(cpu, (int, float)) and cpu >= _CPU_HIGH_PCT:
            events.append(
                {
                    "ts": ts_iso,
                    "message": f"CPU {cpu:.0f}% (high)",
                    "severity": "warning",
                }
            )

    # Down > 5 min: if overall is down and previous was down and elapsed >= 5 min
    if overall == "down" and previous_row and previous_row.overall_status == "down":
        elapsed = (now - previous_row.timestamp).total_seconds() / 60.0
        if elapsed >= _DOWN_MINUTES_ALERT:
            events.append(
                {
                    "ts": ts_iso,
                    "message": f"Group down for {int(elapsed)}m",
                    "severity": "critical",
                }
            )

    return events


def _run_status_poll_job_impl() -> None:
    """Poll all status groups, compute metrics, append history, prune old.

    Called under advisory lock.
    """
    db = SessionLocal()
    broadcast_payload: list[dict] = []
    try:
        groups = list(db.execute(select(StatusGroup)).scalars().all())
        for group in groups:
            group_id = group.id
            try:
                previous_row = (
                    db.execute(
                        select(StatusHistory)
                        .where(StatusHistory.group_id == group_id)
                        .order_by(desc(StatusHistory.timestamp))
                        .limit(1)
                    )
                    .scalars()
                    .one_or_none()
                )
                statuses, uptime_pct, metrics_list, avg_ping = _entity_status(db, group)
                overall = _overall_status(statuses, uptime_pct)
                events = _detect_events(group_id, overall, metrics_list or [], previous_row)
                raw = {"statuses": statuses, "metrics_count": len(metrics_list)}
                metrics_payload: dict[str, Any] | None = None
                if metrics_list or events:
                    metrics_payload = {
                        "events": events,
                        "cpu_mem": (metrics_list or [])[:20],
                    }
                # Enrich with blast radius when a critical DOWN event is detected
                if events and any(e.get("severity") == "critical" for e in events):
                    try:
                        from app.services.intelligence.dependency_graph import (
                            calculate_blast_radius,
                        )

                        hw_ids, _, _, _ = svc.resolve_group_entity_ids(group)
                        if hw_ids:
                            blast = calculate_blast_radius(db, "hardware", hw_ids[0])
                            if metrics_payload is None:
                                metrics_payload = {"events": events, "cpu_mem": []}
                            metrics_payload["blast_radius"] = {
                                "summary": blast.summary,
                                "total_impact_count": blast.total_impact_count,
                                "impacted_compute_units": len(blast.impacted_compute_units),
                                "impacted_services": len(blast.impacted_services),
                                "impacted_hardware": len(blast.impacted_hardware),
                            }
                    except Exception:
                        pass  # blast radius is enrichment only — never block the status update
                svc.append_history(
                    db,
                    group_id,
                    overall,
                    uptime_pct,
                    avg_ping=avg_ping,
                    metrics=metrics_payload,
                    raw_telemetry=raw,
                )
                broadcast_payload.append(
                    {
                        "id": group_id,
                        "name": group.name,
                        "status": overall,
                        "uptime_pct": round(uptime_pct, 1),
                    }
                )
            except Exception as e:
                _logger.warning("Status poll failed for group %s: %s", group_id, e)
                from app.core.worker_audit import log_worker_audit

                log_worker_audit(
                    action="status_poll_failed",
                    entity_type="status_group",
                    entity_id=group_id,
                    details=str(e)[:200],
                    severity="error",
                    worker_name="status_worker",
                )
        if broadcast_payload:
            try:
                from app.api.ws_status import schedule_status_broadcast

                schedule_status_broadcast({"type": "status_update", "groups": broadcast_payload})
            except Exception as e:
                _logger.debug("Status WS broadcast failed: %s", e)
        pruned = svc.prune_history_older_than(db, days=30)
        if pruned:
            _logger.info("Status history pruned: %d rows", pruned)
            from app.core.worker_audit import log_worker_audit

            log_worker_audit(
                action="prune_status_history",
                entity_type="status_history",
                details=f"pruned={pruned}",
                worker_name="status_worker",
            )
    except Exception as e:
        db.rollback()
        _logger.exception("Status poll job failed: %s", e)
        raise
    finally:
        db.close()


def run_status_poll_job() -> None:
    """Poll all status groups. Single-run via advisory lock."""
    from app.core.job_lock import run_with_advisory_lock

    run_with_advisory_lock("status_page_poll", job_fn=_run_status_poll_job_impl)
