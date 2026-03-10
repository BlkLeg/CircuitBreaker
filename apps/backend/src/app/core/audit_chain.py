"""Audit log hash chain verification.

The audit log is written with each entry's log_hash = SHA256(payload) and
previous_hash = log_hash of the prior entry. This module verifies the chain.
"""

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Log


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
    for log in logs:
        entry_data = {
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
        payload = json.dumps(entry_data, sort_keys=True)
        expected_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        if log.previous_hash != previous_hash:
            return {
                "valid": False,
                "first_failure_id": log.id,
                "message": f"Log id={log.id}: previous_hash mismatch (chain broken).",
                "checked_count": len(logs),
            }
        if log.log_hash != expected_hash:
            return {
                "valid": False,
                "first_failure_id": log.id,
                "message": f"Log id={log.id}: log_hash mismatch (entry tampered).",
                "checked_count": len(logs),
            }
        previous_hash = expected_hash

    return {
        "valid": True,
        "first_failure_id": None,
        "message": f"Chain verified ({len(logs)} entries).",
        "checked_count": len(logs),
    }
