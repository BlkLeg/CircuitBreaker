"""Task 1d fix: slow-query timing state must not survive a failing statement.

Unit-level and DB-free by construction: drives the `before_cursor_execute` /
`after_cursor_execute` listener functions in `app.db.session` directly with
stub `conn`/`context` objects rather than a real engine, so this test
executes wherever `apps/backend/tests/` runs — including CI's sharded
backend job (`tests/build/backend_shard.py` enumerates this directory, not
`tests/integration/`) — with no live Postgres required.

`tests/integration/test_slow_query_logging.py` covers the same defect class
against a real connection pool (worth having for `make test-backend`); this
file is what actually executes in CI on every push.

Context: the original design stashed a start-time stack under a key on
`Connection.info`, which SQLAlchemy documents as living on the physical
DBAPI connection and surviving return to the pool. Because
`after_cursor_execute` is only dispatched when `do_execute` succeeds, a
statement that raises never triggers the pop, so every failure left an
un-popped entry there forever. The fix moved the start time onto the
per-statement `ExecutionContext` instead — a fresh, disposable object per
statement — so there is nothing left on the connection to leak regardless of
whether a statement raises.
"""

from __future__ import annotations

import logging
import types

import pytest

from app.db import session as db_session_module

# The key the pre-fix design used on Connection.info — asserted absent below.
_LEGACY_STACK_KEY = "_cb_query_start_times"


class _FakeConn:
    """Stands in for SQLAlchemy's `Connection`: only `.info` is exercised by
    these listeners, and `.info` is exactly the physical-connection-scoped
    dict the original bug leaked into."""

    def __init__(self) -> None:
        self.info: dict[str, object] = {}


def _fake_context() -> types.SimpleNamespace:
    """Stands in for one statement's `ExecutionContext` — a fresh, disposable
    object per statement, exactly as SQLAlchemy provides one."""
    return types.SimpleNamespace()


@pytest.fixture(autouse=True)
def _low_slow_query_threshold(monkeypatch):
    """Force every statement to qualify as "slow" so success is observable
    without a real elapsed duration."""
    monkeypatch.setattr(db_session_module, "_SLOW_QUERY_THRESHOLD_MS", 0.001)


def test_a_failing_statement_leaves_no_state_on_the_connection():
    """`_record_query_start` fires; the statement then "raises", so
    `_log_slow_query` is deliberately never called for it — exactly what
    SQLAlchemy does for a real failing statement. Nothing should be left on
    the connection regardless."""
    conn = _FakeConn()
    context = _fake_context()

    db_session_module._record_query_start(
        conn,
        cursor=None,
        statement="SELECT 1/0",
        parameters=None,
        context=context,
        executemany=False,
    )
    # The statement "raised" here — after_cursor_execute is not invoked.

    assert conn.info == {}
    assert _LEGACY_STACK_KEY not in conn.info


def test_repeated_failures_on_the_same_connection_accumulate_nothing():
    """The original stack-based design grew `conn.info[_LEGACY_STACK_KEY]` by
    one un-popped entry per failure. This drives ten of them on the same
    connection object and asserts nothing accumulates."""
    conn = _FakeConn()

    for _ in range(10):
        context = _fake_context()
        db_session_module._record_query_start(
            conn,
            cursor=None,
            statement="SELECT 1/0",
            parameters=None,
            context=context,
            executemany=False,
        )
        # No corresponding _log_slow_query call: every one of these "raised".

    assert conn.info == {}


def test_a_failure_does_not_corrupt_timing_for_the_next_statement(caplog):
    """The self-healing claim: a failure right before a successful statement
    must not prevent that statement from being timed and logged correctly."""
    conn = _FakeConn()

    failed_context = _fake_context()
    db_session_module._record_query_start(
        conn,
        cursor=None,
        statement="SELECT 1/0",
        parameters=None,
        context=failed_context,
        executemany=False,
    )
    # failed_context "raised" — after_cursor_execute never runs for it.

    ok_context = _fake_context()
    with caplog.at_level(logging.WARNING, logger="app.db.session"):
        db_session_module._record_query_start(
            conn,
            cursor=None,
            statement="SELECT 1 AS after_failure",
            parameters=None,
            context=ok_context,
            executemany=False,
        )
        db_session_module._log_slow_query(
            conn,
            cursor=None,
            statement="SELECT 1 AS after_failure",
            parameters=None,
            context=ok_context,
            executemany=False,
        )

    slow_query_records = [r for r in caplog.records if "[slow_query]" in r.getMessage()]
    assert len(slow_query_records) == 1
    assert "after_failure" in slow_query_records[0].getMessage()
    # Confirms the message logs the statement, never bound parameter values.
    assert "params" not in slow_query_records[0].getMessage().lower()

    # And the failed statement's own context never leaked onto the connection.
    assert conn.info == {}


def test_start_time_lives_on_the_context_not_the_connection():
    """Direct proof of the design change: `_record_query_start` must not
    touch `conn.info` at all, on either the success or the failure path."""
    conn = _FakeConn()
    context = _fake_context()

    db_session_module._record_query_start(
        conn, cursor=None, statement="SELECT 1", parameters=None, context=context, executemany=False
    )

    assert conn.info == {}
    assert hasattr(context, db_session_module._QUERY_START_ATTR)
