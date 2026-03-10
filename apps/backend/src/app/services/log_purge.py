"""Audit log retention purge — scheduled daily by the APScheduler job."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete

from app.core.time import utcnow
from app.db.models import AppSettings, Log
from app.db.session import SessionLocal
from app.services.log_service import write_log

_logger = logging.getLogger(__name__)


def purge_old_audit_logs() -> int:
    """Delete audit log rows older than the configured retention window.

    Reads ``audit_log_retention_days`` from :class:`AppSettings`, deletes
    matching rows, and writes a summary audit entry.  Returns the number
    of rows deleted.
    """
    with SessionLocal() as db:
        row = db.query(AppSettings).first()
        retention_days = row.audit_log_retention_days if row else 90

        if retention_days <= 0:
            _logger.debug("Audit log retention disabled (days=%d); skipping purge", retention_days)
            return 0

        cutoff = utcnow() - timedelta(days=retention_days)
        result = db.execute(delete(Log).where(Log.timestamp < cutoff))
        deleted = result.rowcount  # type: ignore[attr-defined]
        db.commit()

    if deleted:
        _logger.info("Purged %d audit log entries older than %d days", deleted, retention_days)
        write_log(
            db=None,
            action="audit_log_purge",
            category="settings",
            severity="info",
            details=f"Purged {deleted} audit log entries older than {retention_days} days",
        )
    else:
        _logger.debug("Audit log purge: no entries older than %d days", retention_days)

    return deleted
