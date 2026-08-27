"""Audit log hash chain verification.

The audit log is written with each entry's log_hash = SHA256(payload) and
previous_hash = log_hash of the prior entry. This module verifies the chain.
"""

import json
import logging
import time
from typing import Any

from sqlalchemy import BigInteger, bindparam, select, text
from sqlalchemy.orm import Session, load_only

from app.db.models import AppSettings, Log

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


# The columns canonical_log_payload hashes, plus the two chain columns and the
# implicitly-loaded primary key. Everything else on a Log row — old_value,
# new_value, details, user_agent — is untruncated body text that no hash covers,
# so loading it to verify a chain buys nothing and costs the whole table. Keep
# this tuple in step with canonical_log_payload: a field added to the payload
# and not added here would be lazy-loaded one row at a time (correct, but a
# SELECT per row), and one removed from the payload but left here is dead
# weight.
_HASHED_COLUMNS = (
    Log.created_at_utc,
    Log.action,
    Log.actor_id,
    Log.role_at_time,
    Log.entity_type,
    Log.entity_id,
    Log.diff,
    Log.ip_address,
    Log.previous_hash,
    Log.log_hash,
)

# Rows per round trip while streaming the chain. Peak memory is this window
# rather than the table; the identity map is weak and the instances are clean,
# so each batch is collectable as the walk advances.
_VERIFY_YIELD_PER = 1000


# Rows per window while relinking a damaged suffix. Smaller than the verify
# window because each row here is dirtied and flushed rather than only read.
_REPAIR_BATCH_ROWS = 500


def chain_seed_hash(session: Session) -> str | None:
    """Return the hash the chain walk must start from.

    NULL — genesis — on a fresh install. After a retention purge it is the
    ``log_hash`` of the last row that purge deleted, recorded by
    :func:`app.services.log_purge.purge_old_audit_logs`, because the row that is
    now first still names its deleted predecessor in ``previous_hash``. Seeding
    from the checkpoint is what keeps a purged chain verifiable; seeding from
    the first surviving row's own ``previous_hash`` instead would "work" too and
    would be a hole, since it would make any deletion of the head self-
    justifying. An unrecorded deletion still fails, which is the point.
    """
    return session.execute(
        select(AppSettings.audit_chain_checkpoint_hash).order_by(AppSettings.id.asc()).limit(1)
    ).scalar_one_or_none()


def verify_audit_chain(session: Session) -> dict[str, Any]:
    """Stream logs in id order, recompute expected hash for each, verify linkage.

    Returns a dict: valid (bool), first_failure_id (int | None), message (str),
    checked_count (int).

    The walk is streamed and column-restricted on purpose. This runs against the
    largest table in the product, and materialising it — every row, every body
    column — put the whole audit log in the Python heap for a read that touches
    ten columns. Do not "simplify" this back to ``list(session.execute(
    select(Log)).scalars())``.
    """
    stmt = (
        select(Log)
        .options(load_only(*_HASHED_COLUMNS))
        .order_by(Log.id.asc())
        .execution_options(stream_results=True, yield_per=_VERIFY_YIELD_PER)
    )

    previous_hash: str | None = chain_seed_hash(session)
    checked_count = 0
    failure: dict[str, Any] | None = None

    result = session.execute(stmt)
    try:
        for log in result.scalars():
            checked_count += 1
            expected_hash = compute_log_hash(log, previous_hash)

            if log.previous_hash != previous_hash:
                failure = {
                    "valid": False,
                    "first_failure_id": log.id,
                    "message": f"Log id={log.id}: previous_hash mismatch (chain broken).",
                    "checked_count": checked_count,
                }
                break
            if log.log_hash != expected_hash:
                failure = {
                    "valid": False,
                    "first_failure_id": log.id,
                    "message": f"Log id={log.id}: log_hash mismatch (entry tampered).",
                    "checked_count": checked_count,
                }
                break
            previous_hash = expected_hash
    finally:
        # Breaking out of a server-side cursor leaves it open on the connection
        # until the transaction ends; close it where the walk stops.
        result.close()

    if failure is not None:
        return failure

    if checked_count == 0:
        return {
            "valid": True,
            "first_failure_id": None,
            "message": "No log entries to verify.",
            "checked_count": 0,
        }

    return {
        "valid": True,
        "first_failure_id": None,
        "message": f"Chain verified ({checked_count} entries).",
        "checked_count": checked_count,
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

    # Taken before the rows are read, not after: this is the lock that keeps a
    # concurrent append from linking onto a row this repair is about to rewrite.
    lock_audit_chain(session)

    # verify_audit_chain has already proved that every row before the first
    # failure recomputes to its stored log_hash, so the stored hash of the row
    # just before it is a sound seed. Replaying the prefix would recompute
    # values already known to be right; selecting it FOR UPDATE would also lock
    # the entire table for the duration of the repair. Only the damaged suffix
    # is loaded and locked. When the failure is at the head there is no prior
    # row, and the seed is the retention checkpoint (genesis on a chain that has
    # never been purged) — re-anchoring to NULL there would rewrite every hash
    # in the table and still not verify.
    seed = session.execute(
        select(Log.log_hash).where(Log.id < first_failure_id).order_by(Log.id.desc()).limit(1)
    ).scalar_one_or_none()
    if seed is None:
        seed = chain_seed_hash(session)

    previous_hash: str | None = seed
    changed: list[dict[str, Any]] = []

    # Walked in bounded windows, and column-restricted exactly like the verify
    # walk above. The damaged suffix is not a small thing: when the failure is
    # at the head — which is every install whose chain head was cut before the
    # retention checkpoint existed — the suffix *is* the whole logs table, and
    # the earlier `list(session.execute(select(Log)...))` pulled every row into
    # the heap complete with old_value, new_value, details and user_agent, none
    # of which the hash covers. Each window is flushed before the next is read,
    # and nothing holds a reference to the previous one, so the rows are
    # collectable as the repair advances. Do not collapse this back into one
    # unbounded select.
    next_id = first_failure_id
    while True:
        window = list(
            session.execute(
                select(Log)
                .options(load_only(*_HASHED_COLUMNS))
                .where(Log.id >= next_id)
                .order_by(Log.id.asc())
                .limit(_REPAIR_BATCH_ROWS)
                .with_for_update()
            ).scalars()
        )
        if not window:
            break

        for log in window:
            expected_hash = compute_log_hash(log, previous_hash)
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

        # FOR UPDATE with a LIMIT drops rows another transaction deleted under
        # us rather than re-running the query, so a short window is not proof
        # the suffix is exhausted. Advance past the last id seen and stop only
        # on an empty window.
        next_id = window[-1].id + 1
        session.flush()
        del window

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
