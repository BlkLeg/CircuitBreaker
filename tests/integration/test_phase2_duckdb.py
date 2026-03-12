"""Phase 2 tests — DuckDB analytics client."""

from unittest.mock import patch

from app.db import duckdb_client


def test_is_available_returns_false_by_default():
    """Without DuckDB configured, is_available() should return False."""
    assert duckdb_client.is_available() is False


def test_query_falls_back_to_postgres():
    """query() should succeed even without DuckDB, using the PostgreSQL fallback."""
    result = duckdb_client.query("SELECT 1 AS val")
    assert len(result) == 1
    assert result[0]["val"] == 1


def test_ingest_csv_raises_without_duckdb():
    """ingest_csv() should raise RuntimeError when DuckDB is not available."""
    import pytest

    with pytest.raises(RuntimeError, match="DuckDB is not available"):
        duckdb_client.ingest_csv("/nonexistent.csv", "test_table")


def test_is_available_true_when_duckdb():
    """is_available() should return True when the analytics engine dialect is duckdb."""
    from unittest.mock import MagicMock

    from app.db.db_client import get_engine as _real_get_engine

    _real_get_engine.cache_clear()
    mock_engine = MagicMock()
    mock_engine.dialect.name = "duckdb"
    with patch("app.db.duckdb_client.get_engine", return_value=mock_engine):
        assert duckdb_client.is_available() is True
    _real_get_engine.cache_clear()


def test_catalog_service_fallback():
    """Catalog service fuzzy search should work without DuckDB."""
    from app.services.catalog_service import fuzzy_search_catalog

    results = fuzzy_search_catalog("nonexistent_query_12345")
    assert isinstance(results, list)
    assert len(results) >= 1
    assert results[-1].get("_freeform") is True
