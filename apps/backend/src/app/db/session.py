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

# Pool defaults suit mid-range servers; tune via env vars on constrained hosts.
# Increased from 10/10 to 20/20 to reduce exhaustion under concurrent + scheduler load.
engine = create_engine(
    db_url,
    pool_size=int(os.environ.get("DB_POOL_SIZE", "20")),
    max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "20")),
    pool_recycle=300,
    pool_pre_ping=True,
)

# PG-only: kept for compatibility with admin_db and db_backup.
is_sqlite = False

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
