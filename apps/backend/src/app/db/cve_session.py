"""Dedicated SQLite engine and session factory for the CVE database.

The CVE data lives in ``data/cve.db`` — a separate file from the main
application database — so it can grow independently and be replaced or
rebuilt without affecting operational data.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.models import CVEEntry  # noqa: F401 — ensure model metadata is loaded

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
def _set_sqlite_pragmas(dbapi_connection, _connection_record):
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


def init_cve_db() -> None:
    """Create the ``cve_entries`` table in the CVE database if it doesn't exist."""
    CVEEntry.__table__.create(bind=cve_engine, checkfirst=True)  # type: ignore[attr-defined]
    _logger.info("CVE database initialised at %s", _CVE_DB_PATH)


def get_cve_db():
    """FastAPI dependency: yields a CVE database session."""
    db = CVESessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
