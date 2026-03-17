"""Distributed lock for scheduled jobs using PostgreSQL advisory locks.

Ensures only one worker/container runs a given job at a time when multiple
Uvicorn workers or backend replicas are deployed.
"""

import hashlib
import logging
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal

_logger = logging.getLogger(__name__)


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
    db = SessionLocal()
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
