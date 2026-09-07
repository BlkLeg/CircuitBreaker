"""Startup schema guard: `assert_required_schema` re-runs Alembic once when a
required table is missing, and exits 1 if it is still missing afterwards.

These tests derive their fixture schema states from `schema.REQUIRED_SCHEMA_TABLES`
rather than naming tables literally. The original versions hard-coded
{"app_settings", "status_pages", "webhook_rules"}; when da7b0ed5 deleted the
status-page and webhook features (and their tables) the required set narrowed to
{"app_settings"}, which turned this module's "incomplete schema" fixture into a
*complete* one — so the guard never took the retry branch and both tests failed
without the guard itself having regressed. Deriving the states keeps them
honest against any future change to the required set.
"""

import pytest

import app.startup.schema as schema

# An unrelated table proves the guard checks for a subset, not equality.
_EXTRA_TABLE = "some_unrelated_table"


def _schema_states() -> tuple[set[str], set[str]]:
    """Return (incomplete, complete) `pg_class` snapshots for the real required set."""
    required = set(schema.REQUIRED_SCHEMA_TABLES)
    assert required, "REQUIRED_SCHEMA_TABLES must not be empty or the guard is a no-op"
    complete = required | {_EXTRA_TABLE}
    incomplete = complete - {sorted(required)[0]}
    return incomplete, complete


def test_assert_required_schema_is_a_noop_when_schema_is_complete(monkeypatch):
    """No missing table -> no repair attempt. Pins the branch that a too-narrow
    required set silently forces every call into."""
    _, complete = _schema_states()
    upgrade_calls = []

    monkeypatch.setattr(schema, "get_existing_schema_tables", lambda: complete)
    monkeypatch.setattr(schema, "run_alembic_upgrade", lambda: upgrade_calls.append("upgrade"))

    schema.assert_required_schema()

    assert upgrade_calls == []


def test_assert_required_schema_retries_migration_once(monkeypatch):
    incomplete, complete = _schema_states()
    table_states = iter([incomplete, complete])
    upgrade_calls = []

    monkeypatch.setattr(schema, "get_existing_schema_tables", lambda: next(table_states))
    monkeypatch.setattr(schema, "run_alembic_upgrade", lambda: upgrade_calls.append("upgrade"))

    schema.assert_required_schema()

    assert upgrade_calls == ["upgrade"]


def test_assert_required_schema_exits_when_schema_still_missing(monkeypatch):
    incomplete, _ = _schema_states()
    upgrade_calls = []

    monkeypatch.setattr(schema, "get_existing_schema_tables", lambda: incomplete)
    monkeypatch.setattr(schema, "run_alembic_upgrade", lambda: upgrade_calls.append("upgrade"))

    with pytest.raises(SystemExit) as exc_info:
        schema.assert_required_schema()

    assert exc_info.value.code == 1
    assert upgrade_calls == ["upgrade"]  # repaired exactly once, then gave up
