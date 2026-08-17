"""Durable spool for audit entries that could not be hash-chained in time.

Why this exists
---------------
Appending to the audit log is not a plain INSERT. Each row's ``previous_hash``
is the prior row's ``log_hash``, so a writer must read the chain tail and write
the next link while holding the audit-chain advisory lock
(:func:`app.core.audit_chain.lock_audit_chain`). That lock is transaction-scoped:
a request whose session appended an entry keeps it until that transaction ends.

Background writers — ``LoggingMiddleware`` calls ``write_log(db=None)`` on a
shared executor thread — therefore queue behind arbitrary request transactions.
Waiting without a deadline parks executor threads for the lifetime of somebody
else's transaction, and once they are all parked the awaited work on the request
path stops being served: a slow audit write takes the API down with it. Waiting
*with* a deadline and then discarding the entry fixes that by destroying the
record of an action that really happened, which is the one thing an audit log
exists to prevent.

This module is the third option. On timeout the entry is committed to
``pending_audit_logs`` — a table with no chain, so its INSERT takes no lock and
cannot contend — and :func:`drain` links the spooled rows into the chain once
the lock is obtainable. Nothing is dropped, nothing is written unserialised, and
the wait stays bounded.

Ordering
--------
A drained entry lands at a later chain position than entries written while it
sat in the spool. That is correct and verifiable: ``verify_audit_chain`` walks
rows in ``id`` order and rehashes each against its predecessor, while the time
the audited action actually happened travels inside the payload as
``created_at_utc`` and is covered by the hash. Chain position proves integrity;
``created_at_utc`` proves when. They are allowed to disagree, and the spool is
the only thing that makes them.

What the spool window does not protect against
----------------------------------------------
A spooled row is committed but not yet chained, so between defer and drain it
carries no tamper evidence of its own — an attacker with write access to the
database could delete it and leave no chain gap behind. That window is the
price of not dropping the entry, and it is bounded by how often :func:`drain`
runs. It is strictly better than the alternative it replaces, where the same
attacker needed to do nothing at all because the entry was never written.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow

_logger = logging.getLogger(__name__)

# How many spooled entries one drain moves into the chain. The lock is held for
# the whole batch, so this bounds how long a drain can block request-path
# writers; leftovers are picked up by the next run.
DRAIN_BATCH_SIZE = 500


def defer(fields: dict[str, Any], *, reason: str) -> None:
    """Commit an audit entry to the spool instead of the chain.

    ``fields`` is the exact ``Log`` constructor payload the contended write
    would have used, minus the chain columns, so a later drain reproduces that
    row rather than an approximation of it. Datetimes are already ISO strings
    by the time they arrive here — see :func:`_encode`.

    Raises nothing: this is the last line of defence, and a caller in an
    ``except`` block cannot handle a failure here. A spool insert that fails
    means the database is unreachable, in which case the chained write was
    never going to succeed either; it is logged at ERROR because at that point
    the entry really is lost.
    """
    from app.db.models import PendingAuditLog
    from app.db.session import SessionLocal

    try:
        with SessionLocal() as session:
            session.add(
                PendingAuditLog(payload=_encode(fields), deferred_at=utcnow(), reason=reason)
            )
            session.commit()
        _logger.warning(
            "audit entry deferred to the spool (action=%r, reason=%s); it will be "
            "chained by the next drain",
            fields.get("action"),
            reason,
        )
    except Exception:  # noqa: BLE001
        _logger.exception(
            "AUDIT ENTRY LOST (action=%r): could not be chained and could not be spooled either",
            fields.get("action"),
        )


def drain(session: Session | None = None, *, limit: int = DRAIN_BATCH_SIZE) -> int:
    """Append spooled entries to the audit chain, oldest first.

    Returns the number of entries chained. Takes the audit-chain lock once for
    the batch and waits for it without a deadline — unlike the background
    writers this exists to rescue, a drain runs on the scheduler rather than on
    an executor thread serving requests, so blocking here costs nothing on the
    request path.

    Safe to call concurrently with itself: the lock serialises drains against
    each other and against live writers, and each row is deleted in the same
    transaction that chains it, so no entry can be appended twice.
    """
    from app.db.session import SessionLocal

    if session is not None:
        return _drain_within(session, limit)
    with SessionLocal() as owned:
        return _drain_within(owned, limit)


def _drain_within(session: Session, limit: int) -> int:
    from app.core.audit_chain import compute_log_hash, lock_audit_chain
    from app.db.models import Log, PendingAuditLog

    pending = list(
        session.execute(
            select(PendingAuditLog).order_by(PendingAuditLog.id.asc()).limit(limit)
        ).scalars()
    )
    if not pending:
        return 0

    # Unbounded wait by design — see this function's docstring.
    lock_audit_chain(session)

    last = session.execute(select(Log).order_by(Log.id.desc()).limit(1)).scalar_one_or_none()
    previous_hash = last.log_hash if last else None

    chained = 0
    for row in pending:
        entry = Log(**_decode(row.payload), previous_hash=previous_hash)
        entry.log_hash = compute_log_hash(entry, previous_hash)
        session.add(entry)
        session.delete(row)
        previous_hash = entry.log_hash
        chained += 1

    session.commit()
    _logger.info("audit spool: chained %d deferred entr%s", chained, "y" if chained == 1 else "ies")
    return chained


def spool_depth(session: Session | None = None) -> int:
    """How many entries are waiting to be chained.

    Exposed so the spool can be alarmed on rather than only logged about: a
    depth that keeps growing means drains are failing or a transaction is
    sitting on the audit-chain lock, and both are conditions an operator wants
    to hear about before the window gets long.
    """
    from sqlalchemy import func

    from app.db.models import PendingAuditLog
    from app.db.session import SessionLocal

    if session is not None:
        return int(session.execute(select(func.count(PendingAuditLog.id))).scalar_one())
    with SessionLocal() as owned:
        return int(owned.execute(select(func.count(PendingAuditLog.id))).scalar_one())


# ── payload encoding ─────────────────────────────────────────────────────────
# The payload column is JSONB, so datetimes have to cross as strings. Encoding
# and decoding live next to each other, and both name every datetime field, so
# adding one to Log without handling it here fails loudly at drain rather than
# silently writing a string into a DateTime column.

_DATETIME_FIELDS = ("timestamp",)


def _encode(fields: dict[str, Any]) -> dict[str, Any]:
    encoded = dict(fields)
    for name in _DATETIME_FIELDS:
        value = encoded.get(name)
        if value is not None and not isinstance(value, str):
            encoded[name] = value.isoformat()
    return encoded


def _decode(payload: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime

    decoded = dict(payload)
    for name in _DATETIME_FIELDS:
        value = decoded.get(name)
        if isinstance(value, str):
            decoded[name] = datetime.fromisoformat(value)
    return decoded
