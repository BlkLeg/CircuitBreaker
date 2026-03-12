import logging
import os
from contextlib import contextmanager

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

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
)

# PG-only: kept for compatibility with admin_db and db_backup.
is_sqlite = False

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── RLS: set app.current_tenant on every connection checkout ─────────────
from sqlalchemy import event  # noqa: E402


@event.listens_for(engine, "checkout")
def _set_tenant_on_checkout(dbapi_conn, connection_record, connection_proxy):
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
                cursor.execute("SET app.current_tenant = %s", (str(tid),))
            else:
                cursor.execute("RESET app.current_tenant")
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


def get_db():
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
def get_session_context():
    """Context manager for scheduler jobs and scripts. Yields a session; on exit rolls back on exception and always closes."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
