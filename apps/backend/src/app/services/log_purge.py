"""Audit log retention purge — scheduled daily by the APScheduler job."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import AppSettings, Log
from app.db.session import SessionLocal
from app.services.log_service import write_log

_logger = logging.getLogger(__name__)

# Rows removed per transaction. The purge takes a row lock on app_settings for
# the length of each transaction (see purge_old_audit_logs for why the lock has
# to be taken in that order), and every settings-mutating request needs that
# same row, so the transaction has to stay short. One batch of this size is a
# single indexed range delete — milliseconds — where the unbatched version was
# one transaction spanning an entire retention window's worth of rows, which on
# the first run after retention is switched on can be millions.
_PURGE_BATCH_ROWS = 1000


def _next_purge_batch(db: Session, cutoff: datetime) -> tuple[int, str | None] | None:
    """Return ``(last_id_to_delete, its log_hash)`` for the next batch, or None.

    Two bounds, and both are load-bearing:

    ``first_kept_id`` — the lowest id whose ``timestamp`` is at or past the
    cutoff — is the contiguous-prefix bound. A row's ``timestamp`` and its chain
    position do not have to agree: ``audit_spool.drain`` chains a deferred entry
    late while preserving the time the event actually happened, so a plain
    ``DELETE WHERE timestamp < cutoff`` can punch a row out of the *middle* of
    the chain and leave a hole no checkpoint can repair. Everything below
    ``first_kept_id`` is by construction both older than the cutoff and a prefix
    of the chain; an old row sitting behind a kept one waits for the next window.

    ``max_id`` — the current chain tip — is never deleted. That is what lets the
    purge run without the audit-chain advisory lock: ``write_log`` chains a new
    entry by reading exactly that row (``ORDER BY id DESC LIMIT 1 FOR UPDATE``),
    so leaving it alone means the purge and an append never contend for the same
    row and an append can never link onto a row this purge is removing. Delete
    the tip instead and the two have to be serialised by the advisory lock,
    which is what the earlier version of this function did — and holding that
    lock across the delete stalled every audit write in the process, including
    the background writers whose bounded lock wait exists precisely so they can
    fall through to the spool instead of blocking. The cost is that one row can
    outlive the retention window until the next purge; the summary entry written
    at the end of this function is normally that row.
    """
    max_id = db.execute(select(Log.id).order_by(Log.id.desc()).limit(1)).scalar_one_or_none()
    if max_id is None:
        return None

    first_kept_id = db.execute(
        select(Log.id).where(Log.timestamp >= cutoff).order_by(Log.id.asc()).limit(1)
    ).scalar_one_or_none()
    bound = max_id if first_kept_id is None else first_kept_id

    ids = list(
        db.execute(
            select(Log.id).where(Log.id < bound).order_by(Log.id.asc()).limit(_PURGE_BATCH_ROWS)
        ).scalars()
    )
    if not ids:
        return None

    tip_id = ids[-1]
    # Read as a column rather than an ORM instance: the value has to survive the
    # bulk delete that follows it in the same transaction.
    tip_hash = db.execute(select(Log.log_hash).where(Log.id == tip_id)).scalar_one_or_none()
    return tip_id, tip_hash


def purge_old_audit_logs() -> int:
    """Delete audit log rows older than the configured retention window.

    Reads ``audit_log_retention_days`` from :class:`AppSettings`, deletes
    matching rows, and writes a summary audit entry.  Returns the number
    of rows deleted.

    The audit log is a hash chain: every row's ``previous_hash`` is its
    predecessor's ``log_hash``, and :func:`verify_audit_chain` walks it in ``id``
    order. Retention deletes the *oldest* rows, which is the head of that chain,
    so this function has to leave the remainder verifiable. Three things are
    required for that and none may be removed:

    1. Only a contiguous ``id`` prefix is deleted, and never the chain tip — see
       :func:`_next_purge_batch` for both bounds and why each one exists.
    2. The hash of the last deleted row is recorded in
       ``AppSettings.audit_chain_checkpoint_hash`` so the verifier can seed its
       walk from it. Without that seed the verifier starts from NULL, the
       genesis value, and the first surviving row's ``previous_hash`` — which
       names the row this purge just deleted — reads as tampering. That is the
       bug this exists to fix: the integrity alarm fired on the product's own
       scheduled housekeeping on every install that outlived its retention
       window.
    3. The checkpoint write and the delete it describes commit together. A
       reader must never see a cut chain with a stale checkpoint, so they cannot
       be split across transactions — which is why the *batching* rather than
       the transaction is what keeps each one short.

    Lock order — do not reorder these, and do not add the advisory lock back:

        app_settings row  →  logs rows

    Every settings-mutating request takes them in exactly that order without
    ever meaning to: ``api/settings.py`` calls ``update_settings``, which dirties
    the AppSettings row, and the following ``log_audit`` → ``write_log`` →
    ``lock_audit_chain`` autoflushes that pending UPDATE (taking the row lock)
    before it asks for the audit-chain advisory lock and the ``FOR UPDATE`` on
    the chain tip. ``settings_service._write_timezone_log`` does the same inside
    the update loop. A version of this purge that took the advisory lock first
    and wrote the checkpoint afterwards inverted that order and deadlocked
    against any concurrent settings write; because ``write_log`` catches bare
    ``Exception`` the losing side lost its audit entry *silently* and left the
    request's session needing a rollback. Taking the app_settings row lock as
    the first statement of each batch transaction — and never taking the
    advisory lock at all — is what removes the cycle.
    """
    deleted = 0
    retention_days = 0

    while True:
        with SessionLocal() as db:
            # First statement of the transaction, and deliberately FOR UPDATE
            # even when the checkpoint value turns out to be unchanged: the
            # ordering guarantee above must not depend on whether SQLAlchemy
            # decides there is an UPDATE to flush.
            settings_row = (
                db.execute(
                    select(AppSettings).order_by(AppSettings.id.asc()).limit(1).with_for_update()
                )
                .scalars()
                .first()
            )
            if settings_row is None:
                # No settings row means first-run setup has not happened, and
                # there is nowhere to record the checkpoint. Purging without one
                # is what broke the chain in the first place, so decline rather
                # than fall back to a default retention.
                _logger.debug("Audit log purge: no app settings row; skipping")
                return 0

            retention_days = settings_row.audit_log_retention_days
            if retention_days <= 0:
                _logger.debug(
                    "Audit log retention disabled (days=%d); skipping purge", retention_days
                )
                # break rather than return: retention can be switched off from
                # the UI mid-purge, and the batches already committed still have
                # to be accounted for in the summary entry below.
                break

            cutoff = utcnow() - timedelta(days=retention_days)
            batch = _next_purge_batch(db, cutoff)
            if batch is None:
                break

            tip_id, tip_hash = batch
            settings_row.audit_chain_checkpoint_hash = tip_hash
            db.flush()

            result = db.execute(delete(Log).where(Log.id <= tip_id))
            rowcount = int(result.rowcount)  # type: ignore[attr-defined]
            db.commit()

        deleted += rowcount
        if rowcount == 0:
            # Nothing moved even though a batch was selected. Committing the
            # checkpoint and looping again would spin forever; stop instead.
            _logger.warning("Audit log purge: batch up to id=%d deleted nothing; stopping", tip_id)
            break

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
