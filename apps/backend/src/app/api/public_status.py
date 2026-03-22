"""Public (unauthenticated) status page API."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException

from app.db.models import (
    Integration,
    IntegrationMonitor,
    IntegrationMonitorEvent,
    StatusGroup,
    StatusPage,
)
from app.db.session import get_session_context
from app.schemas.public_status import (
    PublicGroup,
    PublicIncident,
    PublicMonitor,
    PublicStatusPageResponse,
)

router = APIRouter()

_INCIDENT_WINDOW_DAYS = 30


def _overall_status(monitors: list[PublicMonitor]) -> str:
    if not monitors:
        return "unknown"
    statuses = {m.status for m in monitors}
    if statuses == {"up"}:
        return "operational"
    if "up" not in statuses:
        return "major"
    return "partial"


def _build_incidents(
    events: list[IntegrationMonitorEvent],
    monitor_names: dict[int, str],
    monitor_integration_names: dict[int, str],
) -> list[PublicIncident]:
    """Convert raw events into incident objects (down events with optional resolved_at)."""
    # Build a map: monitor_id -> sorted list of events (oldest first)
    by_monitor: dict[int, list[IntegrationMonitorEvent]] = defaultdict(list)
    for ev in events:
        by_monitor[ev.monitor_id].append(ev)
    for lst in by_monitor.values():
        lst.sort(key=lambda e: e.detected_at)

    incidents: list[PublicIncident] = []
    for monitor_id, evs in by_monitor.items():
        i = 0
        while i < len(evs):
            ev = evs[i]
            if ev.new_status == "down":
                # find resolution
                resolved_at = None
                for j in range(i + 1, len(evs)):
                    if evs[j].new_status == "up":
                        resolved_at = evs[j].detected_at
                        i = j  # skip to resolution
                        break
                incidents.append(
                    PublicIncident(
                        monitor_name=monitor_names.get(monitor_id, f"Monitor {monitor_id}"),
                        integration_name=monitor_integration_names.get(monitor_id, ""),
                        previous_status=ev.previous_status,
                        new_status=ev.new_status,
                        detected_at=ev.detected_at,
                        resolved_at=resolved_at,
                    )
                )
            i += 1

    # Sort newest first
    incidents.sort(key=lambda inc: inc.detected_at, reverse=True)
    return incidents


@router.get("/status/{slug}", response_model=PublicStatusPageResponse)
def get_public_status_page(slug: str) -> PublicStatusPageResponse:
    with get_session_context() as db:
        page = db.query(StatusPage).filter(StatusPage.slug == slug).first()
        if page is None:
            raise HTTPException(status_code=404, detail="Status page not found")
        if not page.is_public:
            raise HTTPException(status_code=403, detail="This status page is private")

        groups = db.query(StatusGroup).filter(StatusGroup.status_page_id == page.id).all()

        # Collect all integration_monitor node IDs across all groups
        monitor_ids: list[int] = []
        group_monitor_ids: dict[int, list[int]] = {}  # group_id -> [monitor_id, ...]
        for group in groups:
            nodes = group.nodes or []
            ids = [n["id"] for n in nodes if n.get("type") == "integration_monitor"]
            group_monitor_ids[group.id] = ids
            monitor_ids.extend(ids)

        # Bulk-load monitors with integration name
        monitor_rows: dict[int, tuple[IntegrationMonitor, str]] = {}
        if monitor_ids:
            results = (
                db.query(IntegrationMonitor, Integration.name)
                .join(Integration, IntegrationMonitor.integration_id == Integration.id)
                .filter(IntegrationMonitor.id.in_(monitor_ids))
                .all()
            )
            for m, integ_name in results:
                monitor_rows[m.id] = (m, integ_name)

        # Build PublicGroup list
        public_groups: list[PublicGroup] = []
        all_monitors: list[PublicMonitor] = []
        for group in groups:
            pub_monitors: list[PublicMonitor] = []
            for mid in group_monitor_ids.get(group.id, []):
                if mid not in monitor_rows:
                    continue
                m, integ_name = monitor_rows[mid]
                pm = PublicMonitor(
                    id=m.id,
                    name=m.name,
                    url=m.url,
                    status=m.status,
                    uptime_7d=m.uptime_7d,
                    uptime_30d=m.uptime_30d,
                    last_checked_at=m.last_checked_at,
                    integration_name=integ_name,
                )
                pub_monitors.append(pm)
                all_monitors.append(pm)
            public_groups.append(PublicGroup(id=group.id, name=group.name, monitors=pub_monitors))

        # Load recent events for incident history
        cutoff = datetime.now(tz=UTC) - timedelta(days=_INCIDENT_WINDOW_DAYS)
        events: list[IntegrationMonitorEvent] = []
        if monitor_ids:
            events = (
                db.query(IntegrationMonitorEvent)
                .filter(
                    IntegrationMonitorEvent.monitor_id.in_(monitor_ids),
                    IntegrationMonitorEvent.detected_at >= cutoff,
                )
                .all()
            )
        monitor_names = {
            mid: monitor_rows[mid][0].name for mid in monitor_ids if mid in monitor_rows
        }
        monitor_integration_names = {
            mid: monitor_rows[mid][1] for mid in monitor_ids if mid in monitor_rows
        }
        incidents = _build_incidents(events, monitor_names, monitor_integration_names)

        return PublicStatusPageResponse(
            id=page.id,
            title=page.name,
            slug=page.slug,
            is_public=page.is_public,
            overall_status=_overall_status(all_monitors),
            updated_at=(
                page.updated_at if page.updated_at.tzinfo else page.updated_at.replace(tzinfo=UTC)
            ),
            groups=public_groups,
            incidents=incidents,
        )
