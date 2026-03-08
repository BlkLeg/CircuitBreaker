import logging
import os
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

_logger = logging.getLogger(__name__)

db_url = os.environ.get("CB_DB_URL", settings.database_url)
is_sqlite = db_url.startswith("sqlite")

engine_kwargs: dict[str, Any]
if is_sqlite:
    engine_kwargs = {"connect_args": {"check_same_thread": False}}
else:
    # Pool defaults suit mid-range servers; lower via env vars on constrained hosts
    # (e.g. Raspberry Pi or single-core VMs).  Each idle PG connection uses ~2-5 MB.
    engine_kwargs = {
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "5")),
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }

engine = create_engine(db_url, **engine_kwargs)

if is_sqlite:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        """Apply SQLite performance pragmas on every new connection.

        WAL mode:              concurrent reads don't block writes — critical at startup
                               when bootstrap writes and health-check reads can race.
        cache_size=-32768:     32 MB page cache (SQLite default is ~2 MB).
        synchronous=NORMAL:    safe with WAL; eliminates most fsync() overhead while
                               still guaranteeing durability on OS crash.
        """
        # SQLITE_CACHE_SIZE_KB: negative value = kilobytes, positive = pages.
        # Default 8 MB is safe for Pi; raise to 32768 (32 MB) on richer hardware.
        _cache_kb = int(os.environ.get("SQLITE_CACHE_SIZE_KB", "8192"))
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA cache_size=-{_cache_kb}")
            cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception as e:
            _logger.warning(f"Failed to set SQLite pragmas: {e}")
        finally:
            cursor.close()


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
