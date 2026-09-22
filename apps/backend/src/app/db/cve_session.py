"""Dedicated SQLite engine and session factory for the CVE database.

The CVE data lives in ``data/cve.db`` — a separate file from the main
application database — so it can grow independently and be replaced or
rebuilt without affecting operational data.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.paths import data_dir
from app.core.time import utcnow
from app.db.cve_models import CVECacheBase, CVECacheSchema
from app.db.models import CVEEntry

_logger = logging.getLogger(__name__)


def _cve_db_path() -> Path:
    return data_dir() / "cve.db"


# SQLite's DBAPI connects lazily, so `create_engine` itself touches no
# filesystem — the path is only opened (and its parent only created) when
# something actually connects, via the `do_connect` listener below. That is
# what lets this module import cleanly from a cwd it cannot write to; a
# module-level `mkdir` here previously failed exactly that case.
cve_engine = create_engine(
    f"sqlite:///{_cve_db_path()}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(cve_engine, "do_connect")
def _ensure_cve_dir(_dialect: Any, _conn_rec: Any, _cargs: Any, _cparams: Any) -> None:
    _cve_db_path().parent.mkdir(parents=True, exist_ok=True)


@event.listens_for(cve_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA cache_size=-16384")
        cursor.execute("PRAGMA synchronous=NORMAL")
    except Exception as exc:
        _logger.warning("Failed to set CVE DB pragmas: %s", exc)
    finally:
        cursor.close()


CVESessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cve_engine)
CVE_CACHE_SCHEMA_VERSION = 1


def init_cve_db() -> None:
    """Initialize legacy and normalized tables in the disposable CVE cache."""
    try:
        with CVESessionLocal() as db:
            bind = db.get_bind()
            CVEEntry.__table__.create(bind=bind, checkfirst=True)  # type: ignore[attr-defined]
            CVECacheBase.metadata.create_all(bind=bind, checkfirst=True)
    except OperationalError as exc:
        if not _is_existing_table_race(exc):
            raise
        _logger.info("CVE database table already exists; continuing after startup race")
    with CVESessionLocal() as db:
        schema = db.get(CVECacheSchema, 1)
        if schema is None:
            db.add(
                CVECacheSchema(
                    id=1,
                    version=CVE_CACHE_SCHEMA_VERSION,
                    updated_at=utcnow(),
                )
            )
            db.commit()
        elif schema.version > CVE_CACHE_SCHEMA_VERSION:
            raise RuntimeError(
                "CVE cache schema is newer than this application supports; rebuild the cache"
            )
        elif schema.version < CVE_CACHE_SCHEMA_VERSION:
            raise RuntimeError("CVE cache schema requires an explicit upgrade or rebuild")
    _logger.info("CVE database initialised at %s", _cve_db_path())


def _is_existing_table_race(exc: OperationalError) -> bool:
    message = str(exc).lower()
    if "already exists" not in message:
        return False
    return inspect(cve_engine).has_table(CVEEntry.__tablename__)


def get_cve_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a CVE database session."""
    db = CVESessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
