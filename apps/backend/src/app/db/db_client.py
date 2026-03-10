"""Database client factory.

Returns the appropriate SQLAlchemy engine for a given workload type:

* ``"primary"`` — the main SQLite database used for all transactional writes.
  Always available; no additional dependencies required.
* ``"analytics"`` — a DuckDB engine for heavy read-only analytical queries
  (device catalog search, metrics aggregation).  Requires ``duckdb-engine``
  to be installed and ``settings.analytics_db_path`` to be set.  Falls back
  to the primary SQLite engine if DuckDB is unavailable so callers never
  crash on environments without DuckDB.

Usage
-----
    from app.db.db_client import get_engine

    engine = get_engine("primary")    # always SQLite
    engine = get_engine("analytics")  # DuckDB if available, else SQLite
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.config import settings

_logger = logging.getLogger(__name__)

EngineType = Literal["primary", "analytics"]


@lru_cache(maxsize=2)
def get_engine(engine_type: EngineType = "primary") -> Engine:
    """Return (and cache) the engine for *engine_type*."""
    if engine_type == "analytics":
        return _make_analytics_engine()
    return _make_primary_engine()


def _make_primary_engine() -> Engine:
    return create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )


def _make_analytics_engine() -> Engine:
    analytics_path = getattr(settings, "analytics_db_path", None)
    if analytics_path:
        try:
            import duckdb_engine  # noqa: F401 — side-effect import registers dialect

            url = f"duckdb:///{analytics_path}"
            _logger.info("Analytics engine: DuckDB at %s", analytics_path)
            return create_engine(url)
        except ImportError:
            _logger.warning(
                "duckdb-engine not installed; falling back to SQLite for analytics queries"
            )
    else:
        _logger.debug(
            "analytics_db_path not configured; using primary SQLite for analytics queries"
        )
    return _make_primary_engine()
