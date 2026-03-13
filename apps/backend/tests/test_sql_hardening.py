from datetime import datetime

import pytest

from app.core.sql_hardening import build_audit_partition_sql, quote_audit_partition_name
from app.db.duckdb_client import _quoted_table_identifier


def test_quote_audit_partition_name_rejects_invalid_identifier():
    with pytest.raises(ValueError, match="Invalid audit partition name"):
        quote_audit_partition_name("audit_log_2026_03;drop_table")


def test_build_audit_partition_sql_uses_constrained_identifier():
    sql = build_audit_partition_sql(datetime(2026, 12, 15))
    assert '"audit_log_2026_12"' in sql
    assert "FOR VALUES FROM ('2026-12-01')" in sql
    assert "TO ('2027-01-01')" in sql


def test_quoted_table_identifier_rejects_invalid_name():
    with pytest.raises(ValueError, match="Invalid table name"):
        _quoted_table_identifier("scan-results;DROP TABLE users")


def test_quoted_table_identifier_quotes_valid_name():
    assert _quoted_table_identifier("scan_results_2026") == '"scan_results_2026"'
