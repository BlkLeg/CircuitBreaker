"""Lightweight audit logging helper.

Writes structured entries to the existing ``Log`` table using
``category="audit"`` so they surface in the existing /logs endpoint with
the ``?category=audit`` filter (or the dedicated /logs/audit alias).

Usage::

    from app.core.audit import log_audit
    log_audit(db, request, user_id=user.id, action="login_success",
              resource="auth", status="ok")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.orm import Session

_logger = logging.getLogger(__name__)


def log_audit(
    db: Session,
    request: Request | None,
    *,
    user_id: int | None = None,
    action: str,
    resource: str = "",
    status: str = "ok",
    details: str | None = None,
    severity: str = "info",
) -> None:
    """Append an audit entry to the Log table.

    Args:
        db:        SQLAlchemy session (must be committed by caller or here).
        request:   FastAPI Request object — used to extract IP and User-Agent.
        user_id:   ID of the acting user; None for anonymous/system actions.
        action:    Short snake_case verb, e.g. ``login_success``, ``settings_update``.
        resource:  The entity or subsystem being acted on, e.g. ``"auth"``, ``"settings"``.
        status:    ``"ok"`` | ``"fail"`` | ``"denied"``.
        details:   Optional free-text or JSON detail string.
        severity:  ``"info"`` | ``"warn"`` | ``"error"``.
    """
    try:
        from app.core.time import utcnow
        from app.db.models import Log

        ip: str | None = None
        ua: str | None = None
        if request is not None:
            ip = request.client.host if request.client else None
            ua = request.headers.get("user-agent")

        # Resolve actor display info from DB when possible.
        actor_email: str | None = None
        actor_name: str | None = None
        actor_gravatar_hash: str | None = None
        if user_id is not None:
            try:
                from app.db.models import User

                u = db.get(User, user_id)
                if u:
                    actor_email = u.email
                    actor_name = u.display_name or u.email
                    actor_gravatar_hash = u.gravatar_hash
            except Exception as e:
                _logger.debug(
                    "Audit: could not resolve actor for user_id=%s: %s", user_id, e, exc_info=True
                )

        # Check the global hide-IP setting.
        redact_ip = False
        try:
            from app.services.settings_service import get_or_create_settings

            cfg = get_or_create_settings(db)
            redact_ip = getattr(cfg, "audit_log_hide_ip", False)
        except Exception as e:
            _logger.debug("Audit: could not load hide-IP setting: %s", e, exc_info=True)

        now = utcnow()
        entry = Log(
            timestamp=now,
            level=severity,
            severity=severity,
            category="audit",
            action=action,
            actor=actor_email,
            actor_id=user_id,
            actor_name=actor_name,
            actor_gravatar_hash=actor_gravatar_hash,
            entity_type=resource or None,
            ip_address=None if redact_ip else ip,
            user_agent=ua,
            details=f"status={status}" + (f" | {details}" if details else ""),
            created_at_utc=now.isoformat(),
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        # Audit logging must never crash the request it decorates.
        _logger.debug("Audit log write failed: %s", e, exc_info=True)
