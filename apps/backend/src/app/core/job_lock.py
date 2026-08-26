"""Distributed lock for scheduled jobs using PostgreSQL advisory locks.

Ensures only one worker/container runs a given job at a time when multiple
Uvicorn workers or backend replicas are deployed.
"""

import hashlib
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

_logger = logging.getLogger(__name__)

# ── The connection advisory locks are taken on ─────────────────────────────
#
# Never the request pool. Two reasons, both correctness rather than tuning:
#
# 1. `CB_DB_POOL_URL` points the application engine at pgbouncer when one is
#    deployed. A *session*-level advisory lock is owned by the PostgreSQL
#    backend that took it, and under transaction pooling the next statement
#    can land on a different backend — the lock a job thinks it holds for its
#    duration would silently not be held, which is precisely the guarantee
#    SRV-02 rests on. This engine always uses the direct database URL.
# 2. A lock is held for as long as its job runs. Borrowing a pooled connection
#    for a job that takes minutes would consume request capacity, so each lock
#    opens (and closes) a connection of its own.
_lock_engine = None
_LockSession: sessionmaker | None = None


def lock_session() -> Session:
    """A new session on a connection of its own, for holding an advisory lock."""
    global _lock_engine, _LockSession
    if _LockSession is None:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool

        from app.db.session import db_url

        _lock_engine = create_engine(db_url, poolclass=NullPool, pool_pre_ping=True)
        _LockSession = sessionmaker(autocommit=False, autoflush=False, bind=_lock_engine)
    return _LockSession()


def _lock_id_for(name: str, *args: object) -> int:
    """Return a deterministic bigint for use with pg_try_advisory_lock."""
    key = f"{name}:{':'.join(str(a) for a in args)}"
    h = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(h[:8], "big", signed=True)


def try_advisory_lock(db: Session, lock_id: int) -> bool:
    """Acquire PostgreSQL advisory lock if available. Returns True if acquired."""
    try:
        row = db.execute(
            text("SELECT pg_try_advisory_lock(:id) AS acquired"), {"id": lock_id}
        ).fetchone()
        return bool(row and row[0])
    except Exception as e:
        _logger.warning("Advisory lock acquire failed (lock_id=%s): %s", lock_id, e)
        return False


def advisory_unlock(db: Session, lock_id: int) -> bool:
    """Release PostgreSQL advisory lock. Returns True if released."""
    try:
        row = db.execute(
            text("SELECT pg_advisory_unlock(:id) AS released"), {"id": lock_id}
        ).fetchone()
        return bool(row and row[0])
    except Exception as e:
        _logger.warning("Advisory unlock failed (lock_id=%s): %s", lock_id, e)
        return False


def run_with_advisory_lock(lock_name: str, *lock_args: object, job_fn: Callable[[], None]) -> None:
    """Run job_fn only if the advisory lock for (lock_name, *lock_args) is acquired.

    If another worker holds the lock, job_fn is not called. Uses a dedicated
    DB session for the lock; job_fn may create its own session(s).

    Note: PostgreSQL session-level advisory locks are tied to the DB connection.
    The lock session stays open for the duration of job_fn so the lock holds.
    The connection is always returned to the pool in the outer finally block.
    """
    lock_id = _lock_id_for(lock_name, *lock_args)
    db = lock_session()
    try:
        if not try_advisory_lock(db, lock_id):
            _logger.debug("Skipping job %s (lock not acquired)", lock_name)
            return
        try:
            job_fn()
        except Exception as exc:
            _logger.error("Job %s raised an exception: %s", lock_name, exc, exc_info=True)
            raise
        finally:
            advisory_unlock(db, lock_id)
    finally:
        db.close()


# ── Single-owner background jobs (SRV-02) ──────────────────────────────────
#
# Every scheduled job in this product mutates shared state in the one database
# all replicas share: retention purges, rollups, backups, integration syncs,
# certificate renewal, vault rotation. Registering them on each API process's
# own APScheduler therefore means "run this N times" as soon as there is more
# than one process — two uvicorn workers, a rolling restart with overlap, or an
# API container beside a worker container. SRV-02 requires exactly one owner
# per function, provably; `single_owner` is that proof at the point of
# execution, so it holds however the deployment is composed.
#
# The lock is *tried*, never waited on: a replica that does not get it records
# `skipped_not_owner` and returns immediately, which is what keeps a slow job
# from queueing a second copy behind itself on the next tick.


def _acquire_job_lock(lock_id: int) -> Session | None:
    """Open a dedicated session and take the lock, or return None if held elsewhere."""
    db = lock_session()
    try:
        if try_advisory_lock(db, lock_id):
            return db
    except Exception:
        _logger.warning("Advisory lock acquire failed (lock_id=%s)", lock_id, exc_info=True)
    db.close()
    return None


def _release_job_lock(db: Session, lock_id: int) -> None:
    try:
        advisory_unlock(db, lock_id)
    finally:
        db.close()


def single_owner(func: Callable, *, job_id: str) -> Callable:
    """Wrap a scheduled job so exactly one process in the deployment runs it.

    Returns a callable of the same signature (sync in, sync out; async in,
    async out) so APScheduler's argument validation and its choice of executor
    are unchanged. Jobs that already take a lock of their own — the discovery
    reconciler, the docker sync, the agent-discovery reconciler — keep it: the
    two locks have different ids and both are non-blocking, so nesting them can
    starve nothing and deadlock nothing.
    """
    import asyncio
    import functools
    import inspect

    lock_id = _lock_id_for("scheduled_job", job_id)

    def _record(outcome: str) -> None:
        from app.core import slo_metrics

        slo_metrics.record_job_run(job_id, outcome)

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def _async_single_owner(*args: "Any", **kwargs: "Any") -> "Any":
            db = await asyncio.to_thread(_acquire_job_lock, lock_id)
            if db is None:
                _logger.debug("job %s skipped: another process owns it", job_id)
                _record("skipped_not_owner")
                return None
            try:
                result = await func(*args, **kwargs)
            except Exception:
                _record("failed")
                raise
            else:
                _record("ran")
                return result
            finally:
                await asyncio.to_thread(_release_job_lock, db, lock_id)

        _async_single_owner.cb_single_owner_job_id = job_id  # type: ignore[attr-defined]
        return _async_single_owner

    @functools.wraps(func)
    def _sync_single_owner(*args: "Any", **kwargs: "Any") -> "Any":
        db = _acquire_job_lock(lock_id)
        if db is None:
            _logger.debug("job %s skipped: another process owns it", job_id)
            _record("skipped_not_owner")
            return None
        try:
            result = func(*args, **kwargs)
        except Exception:
            _record("failed")
            raise
        else:
            _record("ran")
            return result
        finally:
            _release_job_lock(db, lock_id)

    # `functools.wraps` makes the wrapper indistinguishable from the job by
    # name, which is what APScheduler's argument validation needs and what a
    # test asserting the wiring cannot see through. The marker is that test's
    # only honest handle on "this job is registered single-owner".
    _sync_single_owner.cb_single_owner_job_id = job_id  # type: ignore[attr-defined]
    return _sync_single_owner
