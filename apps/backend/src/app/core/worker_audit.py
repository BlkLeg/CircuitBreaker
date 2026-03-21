"""Audit logging helper for background workers and scheduled jobs.

Workers run outside HTTP request context, so the standard LoggingMiddleware
cannot intercept their mutations.  This module provides a lightweight wrapper
around :func:`app.core.audit.log_audit` that:

- Opens its own ``SessionLocal`` (workers don't have a request-scoped session)
- Sets ``request=None`` so the audit entry is attributed to ``"system"``
- Never raises — worker audit must not crash the job it decorates
"""

from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


def log_worker_audit(
    *,
    action: str,
    entity_type: str = "",
    entity_id: int | None = None,
    details: str | None = None,
    severity: str = "info",
    worker_name: str = "system",
) -> None:
    """Append an audit entry attributed to a background worker.

    Args:
        action:      Short snake_case verb, e.g. ``"prune_status_history"``.
        entity_type: The entity or subsystem, e.g. ``"status_history"``.
        entity_id:   Optional ID of the affected entity.
        details:     Optional free-text or JSON detail string.
        severity:    ``"info"`` | ``"warn"`` | ``"error"``.
        worker_name: Identifies which worker produced this entry.
    """
    try:
        from app.services.log_service import write_log

        id_suffix = f" entity_id={entity_id}" if entity_id is not None else ""
        full_details = f"worker={worker_name}{id_suffix}"
        if details:
            full_details += f" | {details}"

        write_log(
            db=None,  # write_log opens its own SessionLocal
            action=action,
            entity_type=entity_type or None,
            entity_id=entity_id,
            actor_name=worker_name,
            actor="system",
            actor_id=None,
            category="worker",
            severity=severity,
            details=full_details,
        )
    except Exception:
        _logger.debug("Worker audit log failed for action=%s", action, exc_info=True)
