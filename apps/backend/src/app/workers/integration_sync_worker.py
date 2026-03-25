"""Background worker: sync all enabled integrations on a schedule."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.job_lock import run_with_advisory_lock
from app.core.time import utcnow
from app.db.models import Integration, IntegrationMonitor, IntegrationMonitorEvent
from app.db.session import SessionLocal
from app.integrations.base import MonitorStatus
from app.integrations.registry import INTEGRATION_REGISTRY

_logger = logging.getLogger(__name__)


def _upsert_monitors(
    db: Session,
    integration_id: int,
    results: list[MonitorStatus],
) -> None:
    """Upsert MonitorStatus list into IntegrationMonitor rows.

    Creates status-change events and updates latency when provided.
    """
    now = utcnow()
    for ms in results:
        mon = db.execute(
            select(IntegrationMonitor).where(
                IntegrationMonitor.integration_id == integration_id,
                IntegrationMonitor.external_id == ms.external_id,
            )
        ).scalar_one_or_none()
        if mon:
            old_status = mon.status
            mon.status = ms.status
            mon.uptime_7d = ms.uptime_7d
            mon.uptime_30d = ms.uptime_30d
            mon.last_checked_at = now
            if ms.avg_response_ms is not None:
                mon.avg_response_ms = ms.avg_response_ms
            # Emit a status-change event whenever the status transitions
            if old_status != ms.status:
                db.add(
                    IntegrationMonitorEvent(
                        monitor_id=mon.id,
                        previous_status=old_status,
                        new_status=ms.status,
                    )
                )
        else:
            db.add(
                IntegrationMonitor(
                    integration_id=integration_id,
                    external_id=ms.external_id,
                    name=ms.name,
                    url=ms.url,
                    status=ms.status,
                    uptime_7d=ms.uptime_7d,
                    uptime_30d=ms.uptime_30d,
                    last_checked_at=now,
                    avg_response_ms=ms.avg_response_ms,
                )
            )


def _run_sync_impl() -> None:
    db = SessionLocal()
    try:
        # Process all enabled integrations whose type has a registered plugin
        integrations = (
            db.execute(select(Integration).where(Integration.enabled.is_(True))).scalars().all()
        )

        for integ in integrations:
            plugin_cls = INTEGRATION_REGISTRY.get(integ.type)
            if plugin_cls is None:
                continue  # unknown type — skip
            try:
                with db.begin_nested():  # SAVEPOINT — isolates per-integration failures
                    plugin = plugin_cls()
                    results = plugin.sync(integ, db=db)
                    _upsert_monitors(db, integ.id, results)
                    integ.last_synced_at = utcnow()
                    integ.sync_status = "ok"
                    integ.sync_error = None
                _logger.info(
                    "Sync OK: integration=%d type=%s monitors=%d",
                    integ.id,
                    integ.type,
                    len(results),
                )
            except Exception as exc:
                integ.sync_status = "error"
                integ.sync_error = str(exc)[:512]
                _logger.exception(
                    "Sync failed for integration %d (%s): %s", integ.id, integ.type, exc
                )

        db.commit()
    except Exception:
        db.rollback()
        _logger.exception("Integration sync job failed")
        raise
    finally:
        db.close()


def run_integration_sync_job() -> None:
    """Sync all enabled integrations. Guarded by advisory lock."""
    run_with_advisory_lock("integration_sync_job", job_fn=_run_sync_impl)
