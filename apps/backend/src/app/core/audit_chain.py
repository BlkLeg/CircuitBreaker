"""Audit log hash chain verification.

The audit log is written with each entry's log_hash = SHA256(payload) and
previous_hash = log_hash of the prior entry. This module verifies the chain.
"""

import json
import logging
import time
from typing import Any

from sqlalchemy import BigInteger, bindparam, select, text
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


_AUDIT_CHAIN_LOCK_ID = 487143216

# How often a bounded waiter re-tries the advisory lock while waiting.
_LOCK_RETRY_INTERVAL_SECONDS = 0.02

# The lock id is a module constant, never user input, but interpolating it into
# the statement text still made these two lines the only `text(f"...")` in the
# backend — which is what Semgrep's avoid-sqlalchemy-text rule blocks on, and
# what failed the Semgrep job and both security gates. Binding the id instead
# leaves the SQL a literal string, so the rule has nothing dynamic to flag and
# the value can no longer become part of the statement text. BigInteger is
# explicit because PostgreSQL exposes pg_advisory_xact_lock(bigint) and
# pg_advisory_xact_lock(int, int) but no single-argument integer overload; the
# type keeps resolution unambiguous under server-side parameter binding, where
# an untyped placeholder would otherwise have to be inferred.
_ADVISORY_LOCK_STMT = text("SELECT pg_advisory_xact_lock(:lock_id)").bindparams(
    bindparam("lock_id", _AUDIT_CHAIN_LOCK_ID, type_=BigInteger)
)
_TRY_ADVISORY_LOCK_STMT = text("SELECT pg_try_advisory_xact_lock(:lock_id)").bindparams(
    bindparam("lock_id", _AUDIT_CHAIN_LOCK_ID, type_=BigInteger)
)


class AuditChainLockTimeout(RuntimeError):
    """The audit-chain lock stayed held by another connection past the deadline."""


def lock_audit_chain(session: Session, *, wait_seconds: float | None = None) -> None:
    """Take the strongest audit-chain write lock available for this database.

    On PostgreSQL this must succeed. The lock is what serialises hash-chain
    appends; losing it silently lets two concurrent writers compute
    `previous_hash` from the same tip and produce a fork that later reads as
    tampering. Swallowing the error turned the one control protecting chain
    integrity into a no-op precisely when the database was under stress.

    ``wait_seconds`` bounds how long the caller queues for the lock. Writers
    that append inside their own request transaction leave it ``None`` and wait
    as long as it takes. Background writers — LoggingMiddleware persists its
    route-derived entry on a throwaway connection in the default executor —
    must pass a deadline: the lock is transaction-scoped, so a connection that
    is idle-in-transaction after having appended a log entry holds it, and an
    unbounded wait pins one of the few shared executor threads for as long as
    that transaction lives. Exhaust them and the awaited executor work on the
    request path (actor resolution, old-value fetch) stops being served, i.e.
    a stalled audit write takes the API down with it.

    Timing out raises :class:`AuditChainLockTimeout`. That drops the entry
    loudly rather than appending it unserialised — the chain is never forked.

    Non-PostgreSQL backends have no advisory locks, so the guard below is a
    no-op by design rather than by failure. Nothing ships on one any more:
    PostgreSQL has been the only supported application database since v0.2.0,
    and the single SQLite file left in the product — the CVE store in
    db/cve_session.py — has no audit chain to serialise. The branch stays as a
    defensive no-op, pinned by test_audit_chain_lock_is_a_no_op_on_sqlite.
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    try:
        if wait_seconds is None:
            session.execute(_ADVISORY_LOCK_STMT)
            return

        deadline = time.monotonic() + wait_seconds
        while True:
            acquired = session.execute(_TRY_ADVISORY_LOCK_STMT).scalar()
            if acquired:
                return
            if time.monotonic() >= deadline:
                raise AuditChainLockTimeout(
                    "audit-chain serialisation lock still held by another connection "
                    f"after {wait_seconds}s"
                )
            time.sleep(_LOCK_RETRY_INTERVAL_SECONDS)
    except AuditChainLockTimeout:
        raise
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
