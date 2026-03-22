import logging
import os
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
    except Exception:  # noqa: BLE001
        _logger.debug("RLS tenant variable not available — skipping SET app.current_tenant")


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
