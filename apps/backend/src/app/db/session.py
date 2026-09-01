import logging
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PostgreSQL-only engine (v0.2.0 — SQLite support removed)
# ---------------------------------------------------------------------------
# CB_DB_URL must be set to a postgresql:// URL; there is no SQLite fallback.
# Set via .env or docker-compose environment block.
# ---------------------------------------------------------------------------

db_url = os.environ.get("CB_DB_URL", settings.database_url)

if not db_url.startswith("postgresql"):
    raise RuntimeError(
        f"CB_DB_URL must start with 'postgresql://' (got: {db_url!r}). "
        "SQLite is no longer supported as of v0.2.0. "
        "Set CB_DB_URL=postgresql://breaker:YOUR_PASSWORD@postgres:5432/circuitbreaker"
    )

# Prefer pgbouncer pool URL if available (port 6432); fall back to direct connection.
# When pgbouncer handles pooling, a smaller SQLAlchemy pool (5/5) avoids double-pooling.
_pool_url = os.environ.get("CB_DB_POOL_URL", db_url)
_using_pgbouncer = _pool_url != db_url
_default_pool = "5" if _using_pgbouncer else "20"
_default_overflow = "5" if _using_pgbouncer else "20"

engine = create_engine(
    _pool_url,
    pool_size=int(os.environ.get("DB_POOL_SIZE", _default_pool)),
    max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", _default_overflow)),
    pool_recycle=300,
    pool_pre_ping=True,
    pool_timeout=5,  # Fail fast on pool exhaustion — default 30s would block the event loop
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── RLS: set app.current_tenant on every connection checkout ─────────────


@event.listens_for(engine, "checkout")
def _set_tenant_on_checkout(dbapi_conn: Any, connection_record: Any, connection_proxy: Any) -> None:
    """Propagate the current tenant from the request context to PostgreSQL."""
    try:
        from app.middleware.tenant_middleware import current_tenant_id

        tid = current_tenant_id.get(None)
    except Exception:  # noqa: BLE001
        tid = None

    try:
        cursor = dbapi_conn.cursor()
        try:
            if tid is not None:
                cursor.execute("SELECT set_config('app.current_tenant', %s, true)", (str(tid),))
            else:
                cursor.execute("SELECT set_config('app.current_tenant', '', true)", ())
        finally:
            cursor.close()
    except Exception as exc:  # noqa: BLE001
        # Runs on every pool checkout, so this cannot be an unthrottled log
        # line — but it also must not stay at DEBUG: a connection handed out
        # with `app.current_tenant` unset is a connection whose row-level
        # security policies are evaluating against an empty tenant. Classified,
        # counted and throttled instead, so the condition is measurable
        # (REL-07). Imported lazily to keep `app.db.session` — which almost
        # every module imports — free of a service-layer import at module load.
        from app.services.stream_faults import record_stream_fault

        record_stream_fault(
            "db_session.rls_tenant",
            exc,
            logger=_logger,
            context={"tenant_id": tid},
            level=logging.WARNING,
        )


# ── Task 1d: slow-query logging (observability phase 2) ────────────────────
# Threshold read once at import, matching every other CB_* value this module
# reads (db_url, pool sizes) above. Set CB_SLOW_QUERY_MS=0 to disable.
_SLOW_QUERY_THRESHOLD_MS = float(os.environ.get("CB_SLOW_QUERY_MS", "100"))
_QUERY_START_ATTR = "_cb_query_start"


@event.listens_for(engine, "before_cursor_execute")
def _record_query_start(
    conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
) -> None:
    """Stash a start time on this statement's execution context.

    Deliberately *not* `conn.info`: an earlier version kept a start-time
    stack there, but `conn.info` belongs to the physical DBAPI connection,
    which survives being returned to the pool, while SQLAlchemy only fires
    `after_cursor_execute` when the statement succeeds — a failing statement
    (IntegrityError, a deadlock, a statement timeout) jumps straight to
    `_handle_dbapi_exception` and skips it entirely. Every failing statement
    would leave an un-popped entry on that connection forever: unbounded,
    silent, and on by default.

    `context` has none of that problem: it is a fresh `ExecutionContext`
    created for *this* statement execution alone (confirmed against a live
    connection — a failing statement's context is simply never read again
    and is garbage collected with it), so there is no shared, persistent
    state to leak regardless of whether the statement succeeds.
    """
    if _SLOW_QUERY_THRESHOLD_MS <= 0:
        return
    if context is not None:
        setattr(context, _QUERY_START_ATTR, time.perf_counter())


@event.listens_for(engine, "after_cursor_execute")
def _log_slow_query(
    conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
) -> None:
    """Log any statement that exceeded CB_SLOW_QUERY_MS, at WARNING.

    Logs the statement text only — never `parameters` — because parameters
    carry user data and the log-redaction filter is a regex net over free
    text, not a guarantee against every shape a value can take. Never fires
    for a statement that raised (see `_record_query_start`), which is exactly
    the statement class this listener has nothing useful to say about a
    duration for anyway.
    """
    if _SLOW_QUERY_THRESHOLD_MS <= 0:
        return
    started = getattr(context, _QUERY_START_ATTR, None)
    if started is None:
        return
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms < _SLOW_QUERY_THRESHOLD_MS:
        return

    from app.middleware.request_id import request_id_var

    _logger.warning(
        "[slow_query] %.1fms (threshold %.0fms) request_id=%s statement=%s",
        elapsed_ms,
        _SLOW_QUERY_THRESHOLD_MS,
        request_id_var.get() or "-",
        statement,
    )


naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=naming_convention)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a database session and ensures cleanup."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_session_context() -> Generator[Session, None, None]:
    """Context manager for scheduler jobs and scripts.

    Yields a session; on exit rolls back on exception and always closes.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
