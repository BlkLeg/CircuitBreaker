"""Audit log hash chain verification.

The audit log is written with each entry's log_hash = SHA256(payload) and
previous_hash = log_hash of the prior entry. This module verifies the chain.
"""

import json
import logging
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Log

_logger = logging.getLogger(__name__)

REPAIR_AUTHORIZATION = "REPAIR_AUDIT_CHAIN"


def canonical_log_payload(log: Log, previous_hash: str | None) -> dict[str, Any]:
    """Return the stable payload covered by an audit log row hash."""
    return {
        "timestamp": log.created_at_utc or "",
        "action": log.action or "",
        "actor_id": log.actor_id,
        "role_at_time": log.role_at_time,
        "entity_type": log.entity_type,
        "entity_id": log.entity_id,
        "diff": log.diff,
        "ip_address": log.ip_address,
        "previous_hash": previous_hash,
    }


def compute_log_hash(log: Log, previous_hash: str | None) -> str:
    import hashlib

    payload = json.dumps(canonical_log_payload(log, previous_hash), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def lock_audit_chain(session: Session) -> None:
    """Take the strongest audit-chain write lock available for this database.

    On PostgreSQL this must succeed. The lock is what serialises hash-chain
    appends; losing it silently lets two concurrent writers compute
    `previous_hash` from the same tip and produce a fork that later reads as
    tampering. Swallowing the error turned the one control protecting chain
    integrity into a no-op precisely when the database was under stress.

    Non-PostgreSQL backends (SQLite in tests and single-user installs) have no
    advisory locks and are single-writer anyway, so they are a no-op by design
    rather than by failure.
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    try:
        session.execute(text("SELECT pg_advisory_xact_lock(487143216)"))
    except Exception as exc:
        _logger.error("audit-chain advisory lock could not be acquired", exc_info=True)
        raise RuntimeError(
            "Refusing to append to the audit chain without its serialisation lock"
        ) from exc


def verify_audit_chain(session: Session) -> dict[str, Any]:
    """Load logs in id order, recompute expected hash for each, verify linkage.

    Returns a dict: valid (bool), first_failure_id (int | None), message (str),
    checked_count (int).
    """
    stmt = select(Log).order_by(Log.id.asc())
    logs = list(session.execute(stmt).scalars().all())

    if not logs:
        return {
            "valid": True,
            "first_failure_id": None,
            "message": "No log entries to verify.",
            "checked_count": 0,
        }

    previous_hash: str | None = None
    for checked_count, log in enumerate(logs, start=1):
        expected_hash = compute_log_hash(log, previous_hash)

        if log.previous_hash != previous_hash:
            return {
                "valid": False,
                "first_failure_id": log.id,
                "message": f"Log id={log.id}: previous_hash mismatch (chain broken).",
                "checked_count": checked_count,
            }
        if log.log_hash != expected_hash:
            return {
                "valid": False,
                "first_failure_id": log.id,
                "message": f"Log id={log.id}: log_hash mismatch (entry tampered).",
                "checked_count": checked_count,
            }
        previous_hash = expected_hash

    return {
        "valid": True,
        "first_failure_id": None,
        "message": f"Chain verified ({len(logs)} entries).",
        "checked_count": len(logs),
    }


def repair_audit_chain(
    session: Session,
    *,
    authorization: str,
    actor_id: int | None,
    reason: str,
) -> dict[str, Any]:
    """Explicitly relink audit-chain hashes from the first failing row onward.

    This does not restore original row content. It records a report of changed
    hash fields and appends a separate audit event after the repaired segment.
    """
    if authorization != REPAIR_AUTHORIZATION:
        raise ValueError(f"authorization must equal {REPAIR_AUTHORIZATION!r}")

    before = verify_audit_chain(session)
    if before["valid"]:
        return {"repaired": False, "before": before, "changed": [], "after": before}

    first_failure_id = before["first_failure_id"]
    logs = list(session.execute(select(Log).order_by(Log.id.asc()).with_for_update()).scalars())
    previous_hash: str | None = None
    changed: list[dict[str, Any]] = []
    in_repair_segment = False

    lock_audit_chain(session)
    for log in logs:
        expected_hash = compute_log_hash(log, previous_hash)
        if log.id == first_failure_id:
            in_repair_segment = True
        if in_repair_segment:
            old_previous_hash = log.previous_hash
            old_log_hash = log.log_hash
            if old_previous_hash != previous_hash or old_log_hash != expected_hash:
                log.previous_hash = previous_hash
                log.log_hash = expected_hash
                changed.append(
                    {
                        "id": log.id,
                        "old_previous_hash": old_previous_hash,
                        "new_previous_hash": previous_hash,
                        "old_log_hash": old_log_hash,
                        "new_log_hash": expected_hash,
                    }
                )
        previous_hash = expected_hash

    session.flush()

    from app.services.log_service import write_log

    write_log(
        db=session,
        action="audit_chain_repair",
        entity_type="audit_log",
        entity_id=first_failure_id,
        entity_name=f"from:{first_failure_id}",
        diff={
            "reason": reason,
            "first_failure_id": first_failure_id,
            "changed_count": len(changed),
        },
        actor_name="system" if actor_id is None else f"user:{actor_id}",
        actor_id=actor_id,
        severity="warn",
        category="audit",
        details=json.dumps(
            {
                "authorization": REPAIR_AUTHORIZATION,
                "reason": reason,
                "first_failure_id": first_failure_id,
                "changed_count": len(changed),
            },
            sort_keys=True,
        ),
    )
    after = verify_audit_chain(session)
    return {"repaired": True, "before": before, "changed": changed, "after": after}
