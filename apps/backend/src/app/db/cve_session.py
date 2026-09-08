"""Dedicated SQLite engine and session factory for the CVE database.

The CVE data lives in ``data/cve.db`` — a separate file from the main
application database — so it can grow independently and be replaced or
rebuilt without affecting operational data.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.time import utcnow
from app.db.cve_models import CVECacheBase, CVECacheSchema
from app.db.models import CVEEntry

_logger = logging.getLogger(__name__)


def _get_data_dir() -> Path:
    return Path(os.environ.get("CB_DATA_DIR") or (Path.cwd() / "data")).expanduser()


_CVE_DB_PATH = _get_data_dir() / "cve.db"


def _ensure_dir() -> None:
    _CVE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


_ensure_dir()

cve_engine = create_engine(
    f"sqlite:///{_CVE_DB_PATH}",
    connect_args={"check_same_thread": False},
)


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
    _logger.info("CVE database initialised at %s", _CVE_DB_PATH)


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
