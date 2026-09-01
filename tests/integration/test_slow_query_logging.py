"""Task 1d fix: slow-query timing state must not survive a failing statement.

The original design stashed a start-time stack under a key in
``Connection.info``. SQLAlchemy documents ``info`` as living on the physical
DBAPI connection and surviving return to the pool — it is not scoped to one
logical checkout. Because ``after_cursor_execute`` is only dispatched when
``do_execute`` succeeds (a raising statement — IntegrityError, a deadlock, a
statement timeout — goes straight to ``_handle_dbapi_exception`` and skips it
entirely), every failing statement left an un-popped ``perf_counter()`` entry
on that key forever: unbounded, silent, and on by default
(``CB_SLOW_QUERY_MS=100``). LIFO ordering meant it never corrupted another
query's *measurement*, which is exactly what made it invisible.

The fix moves the start time onto the per-statement ``ExecutionContext``
(``context``) instead of ``conn.info``: a fresh object SQLAlchemy creates for
each statement execution, which is simply discarded — success or failure —
rather than kept around. This suite proves that directly against a live
Postgres connection: ``conn.info`` never gains the old key, a failure does
not corrupt the timing of the next statement, and repeated failures on the
same pooled connection accumulate nothing.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import session as db_session_module

# The key the pre-fix design used on Connection.info — asserted absent below.
_LEGACY_STACK_KEY = "_cb_query_start_times"


@pytest.fixture(autouse=True)
def _low_slow_query_threshold(monkeypatch):
    """Force every statement to qualify as "slow" so success is observable
    without a real 100ms-plus query."""
    monkeypatch.setattr(db_session_module, "_SLOW_QUERY_THRESHOLD_MS", 0.001)


def test_a_failing_statement_leaves_no_state_on_the_pooled_connection():
    """conn.info is the physical-connection-scoped dict the old design leaked
    into. The fix never touches it — proven directly, not inferred."""
    engine = db_session_module.engine
    with engine.connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text("SELECT 1/0"))
        conn.rollback()

        assert _LEGACY_STACK_KEY not in conn.info
        assert not any(str(k).startswith("_cb_query_start") for k in conn.info)


def test_repeated_failures_on_the_same_connection_accumulate_nothing():
    """The original stack-based design grew by one un-popped entry per
    failure; this asserts the replacement does not, across several in a row
    on the very same pooled connection (conn.info's scope, not a fresh one
    per statement)."""
    engine = db_session_module.engine
    with engine.connect() as conn:
        for _ in range(5):
            with pytest.raises(DBAPIError):
                conn.execute(text("SELECT 1/0"))
            conn.rollback()

        assert not any(str(k).startswith("_cb_query_start") for k in conn.info)


def test_a_failure_does_not_corrupt_timing_for_the_next_statement(caplog):
    """The self-healing claim: not just "does not crash", but "keeps
    correctly logging" immediately after a statement that raised."""
    engine = db_session_module.engine
    with caplog.at_level(logging.WARNING, logger="app.db.session"):
        with engine.connect() as conn:
            with pytest.raises(DBAPIError):
                conn.execute(text("SELECT 1/0"))
            conn.rollback()

            caplog.clear()
            conn.execute(text("SELECT 1 AS after_failure"))

    slow_query_records = [r for r in caplog.records if "[slow_query]" in r.getMessage()]
    assert len(slow_query_records) == 1
    assert "after_failure" in slow_query_records[0].getMessage()
    # Confirms the message logs the statement, never bound parameter values.
    assert "params" not in slow_query_records[0].getMessage().lower()
