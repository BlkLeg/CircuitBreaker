"""A contended audit-chain lock must defer the entry, never drop it.

Background audit writes (LoggingMiddleware, via write_log with db=None) run on
a shared executor thread and take the audit-chain advisory lock on their own
connection. That lock is transaction-scoped, so a request whose session has
appended a log entry and not yet committed holds it; an unbounded wait there
parks executor threads until that transaction ends and eventually starves the
request path. The bounded wait that fixed the starvation dropped the entry when
it expired, which trades a liveness bug for a non-repudiation hole: the record
of an action that really happened disappears, and nothing downstream can tell
the difference between "never happened" and "was not written".

So the entry is spooled instead. `pending_audit_logs` carries no hash chain, so
inserting into it needs no lock and cannot contend; a reconciler appends the
spooled rows to the chain once the lock is free. The chain is never forked, the
entry is never lost, and because verify_audit_chain walks rows in id order
while the hashed payload carries created_at_utc, an entry chained late is still
valid — it simply sits at a later chain position than its event time.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select, text

from app.core.audit_chain import _AUDIT_CHAIN_LOCK_ID, verify_audit_chain
from app.db.models import Log, PendingAuditLog
from app.db.session import SessionLocal, engine
from app.services import audit_spool, log_service


@pytest.fixture
def clean_audit_tables(setup_db):
    """write_log(db=None) and the spool commit on their own connections, so they
    escape db_session's rollback. Clear both tables either side of the test.

    Depends on setup_db rather than db_session: these tests deliberately use
    real committing connections, so the SAVEPOINT isolation db_session provides
    would hide exactly the durability this spool exists to give."""

    def _clear():
        with SessionLocal() as s:
            s.execute(delete(PendingAuditLog))
            s.execute(delete(Log))
            s.commit()

    _clear()
    yield
    _clear()


@pytest.fixture
def lock_held():
    """Hold the audit-chain advisory lock on a separate connection, the way an
    uncommitted request transaction does."""
    conn = engine.connect()
    conn.begin()
    conn.execute(text(f"SELECT pg_advisory_xact_lock({_AUDIT_CHAIN_LOCK_ID})"))
    try:
        yield
    finally:
        conn.rollback()
        conn.close()


def _logs():
    with SessionLocal() as s:
        return list(s.execute(select(Log).order_by(Log.id)).scalars().all())


def _pending():
    with SessionLocal() as s:
        return list(s.execute(select(PendingAuditLog).order_by(PendingAuditLog.id)).scalars().all())


def test_a_lock_timeout_defers_the_entry_rather_than_dropping_it(clean_audit_tables, lock_held):
    log_service.write_log(None, action="delete_user", entity_type="user", entity_id=7)

    assert _logs() == [], "the entry must not be chained while the lock is held"
    pending = _pending()
    assert len(pending) == 1, "the entry was dropped instead of spooled"
    assert pending[0].payload["action"] == "delete_user", (
        "the spooled row must carry the entry itself, recoverable without the original process"
    )


def test_a_deferred_entry_is_committed_not_held_in_memory(clean_audit_tables, lock_held):
    """The whole point: a crash after this returns must not lose the record, so
    the spool row has to be visible to an independent connection immediately."""
    log_service.write_log(None, action="revoke_session", entity_type="session", entity_id=3)

    with SessionLocal() as other_connection:
        count = other_connection.execute(select(PendingAuditLog)).scalars().all()
    assert len(count) == 1


def test_deferred_entries_drain_in_the_order_they_happened(clean_audit_tables):
    conn = engine.connect()
    conn.begin()
    conn.execute(text(f"SELECT pg_advisory_xact_lock({_AUDIT_CHAIN_LOCK_ID})"))
    try:
        log_service.write_log(None, action="first", entity_type="user", entity_id=1)
        log_service.write_log(None, action="second", entity_type="user", entity_id=2)
    finally:
        conn.rollback()
        conn.close()

    assert len(_pending()) == 2
    assert audit_spool.drain() == 2

    actions = [log.action for log in _logs()]
    assert actions == ["first", "second"]
    assert _pending() == [], "drained rows must not be left behind to double-append"
    with SessionLocal() as verifier:
        assert verify_audit_chain(verifier)["valid"] is True


def test_a_drained_entry_keeps_the_time_the_event_happened(clean_audit_tables):
    conn = engine.connect()
    conn.begin()
    conn.execute(text(f"SELECT pg_advisory_xact_lock({_AUDIT_CHAIN_LOCK_ID})"))
    before = datetime.now(tz=UTC)
    try:
        log_service.write_log(None, action="deferred_action", entity_type="user", entity_id=1)
    finally:
        conn.rollback()
        conn.close()
    after = datetime.now(tz=UTC)

    audit_spool.drain()

    entry = _logs()[0]
    occurred = datetime.fromisoformat(entry.created_at_utc)
    assert before <= occurred <= after, (
        "the chained entry is stamped with its drain time, not the time the "
        "audited action actually happened"
    )


def test_the_chain_verifies_when_deferred_and_live_entries_interleave(clean_audit_tables):
    """The realistic sequence: something is written normally, something else is
    deferred under contention, then both coexist in one chain."""
    log_service.write_log(None, action="live_before", entity_type="user", entity_id=1)

    conn = engine.connect()
    conn.begin()
    conn.execute(text(f"SELECT pg_advisory_xact_lock({_AUDIT_CHAIN_LOCK_ID})"))
    try:
        log_service.write_log(None, action="deferred", entity_type="user", entity_id=2)
    finally:
        conn.rollback()
        conn.close()

    log_service.write_log(None, action="live_after", entity_type="user", entity_id=3)
    audit_spool.drain()

    assert [log.action for log in _logs()] == ["live_before", "live_after", "deferred"]
    with SessionLocal() as verifier:
        result = verify_audit_chain(verifier)
    assert result["valid"] is True, result["message"]
    assert result["checked_count"] == 3


def test_draining_an_empty_spool_is_a_no_op(clean_audit_tables):
    assert audit_spool.drain() == 0
