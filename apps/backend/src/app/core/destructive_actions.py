"""Shared guardrails for high-impact destructive operations."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.services.log_service import write_log

CONFIRMATION_HEADER = "x-cb-confirmation"
IDEMPOTENCY_HEADER = "idempotency-key"
BACKUP_HEADER = "x-cb-backup-verified"


def require_destructive_confirmation(
    request: Request,
    db: Session,
    *,
    actor_id: int | None,
    action: str,
    target: str,
    confirmation: str,
    backup_required: bool = False,
) -> None:
    """Require explicit confirmation/idempotency headers for destructive actions."""
    supplied = request.headers.get(CONFIRMATION_HEADER)
    idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
    backup_verified = request.headers.get(BACKUP_HEADER)

    missing: list[str] = []
    if supplied != confirmation:
        missing.append(f"{CONFIRMATION_HEADER}: {confirmation}")
    if not idempotency_key or len(idempotency_key.strip()) < 12:
        missing.append(f"{IDEMPOTENCY_HEADER}: <stable key, at least 12 chars>")
    if backup_required and backup_verified != "true":
        missing.append(f"{BACKUP_HEADER}: true")

    if missing:
        write_log(
            db=db,
            action=f"{action}_denied",
            entity_type="destructive_action",
            entity_name=target,
            actor_id=actor_id,
            actor_name="unknown" if actor_id is None else f"user:{actor_id}",
            severity="warn",
            category="audit",
            diff={"target": target, "missing": missing, "backup_required": backup_required},
        )
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "message": "Destructive action requires explicit confirmation.",
                "required": missing,
            },
        )

    write_log(
        db=db,
        action=f"{action}_authorized",
        entity_type="destructive_action",
        entity_name=target,
        actor_id=actor_id,
        actor_name=f"user:{actor_id}" if actor_id is not None else "unknown",
        severity="warn",
        category="audit",
        diff={
            "target": target,
            "idempotency_key": idempotency_key,
            "backup_required": backup_required,
        },
    )


def audit_destructive_outcome(
    db: Session,
    *,
    actor_id: int | None,
    action: str,
    target: str,
    outcome: str,
    details: dict[str, Any] | None = None,
) -> None:
    write_log(
        db=db,
        action=f"{action}_{outcome}",
        entity_type="destructive_action",
        entity_name=target,
        actor_id=actor_id,
        actor_name=f"user:{actor_id}" if actor_id is not None else "unknown",
        severity="warn" if outcome == "completed" else "error",
        category="audit",
        diff={"target": target, "outcome": outcome, **(details or {})},
    )
