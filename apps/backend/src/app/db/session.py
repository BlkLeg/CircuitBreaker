import logging
import os

from sqlalchemy import create_engine
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
        "Set CB_DB_URL=postgresql://breaker:breaker@postgres:5432/circuitbreaker"
    )

# Pool defaults suit mid-range servers; tune via env vars on constrained hosts
# (e.g. Raspberry Pi or single-core VMs).  Each idle PG connection uses ~2-5 MB.
engine = create_engine(
    db_url,
    pool_size=int(os.environ.get("DB_POOL_SIZE", "10")),
    max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "10")),
    pool_recycle=300,
    pool_pre_ping=True,
)

# PG-only: kept for compatibility with admin_db and db_backup.
is_sqlite = False

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


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
