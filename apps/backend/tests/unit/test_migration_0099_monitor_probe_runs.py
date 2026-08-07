"""Schema-level guarantees for the remote-probe tables (Task 6, §1).

Two things have to be true for a remote vantage to be storable at all: the
`monitor_items.probe_*` columns and their `(probe_agent_id, enabled,
next_due_at)` index exist, and `monitor_probe_runs` carries the partial unique
index that makes "one active run per monitor" a database fact rather than a
convention the dispatcher hopes to honour.

Both live only in `0099` — `monitor_items`' probe columns are in `0001_init`'s
`_EXCLUDED_COLUMNS` and `monitor_probe_runs` is in its `_EXCLUDED_TABLES` (see
`tests/test_monitor_probe_schema.py` for why) — so this module drives the
migration itself rather than the models-built test schema. Mirrors
`tests/unit/test_migration_0098_agent_networks.py`.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"
_MIGRATION = "0099_monitor_probe_runs"
_PARENT = "0098_agent_networks"
_RUNS_TABLE = "monitor_probe_runs"
_PROBE_COLUMNS = (
    "probe_agent_id",
    "probe_execution_status",
    "probe_execution_reason",
    "probe_last_dispatched_at",
    "probe_last_result_at",
)


def _load_migration(name: str):
    """`migrations/versions` is not a package, so import by file path."""
    path = _VERSIONS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _replay(connection, module) -> None:
    """Downgrade then upgrade, so the assertions read the migration's own DDL
    and not the `Base.metadata.create_all` schema the fixture starts from."""
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.downgrade()

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.upgrade()


def test_revision_chains_onto_0098():
    module = _load_migration(_MIGRATION)

    assert module.revision == _MIGRATION
    assert module.down_revision == _PARENT


def test_migration_0099_is_the_only_child_of_0098():
    """A second migration claiming the same parent would give alembic two
    heads and break `upgrade head` on every deployment."""
    children = []
    for path in _VERSIONS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "down_revision" for t in node.targets)
                and isinstance(node.value, ast.Constant)
                and node.value.value == _PARENT
            ):
                children.append(path.name)

    assert children == [f"{_MIGRATION}.py"]


def test_monitor_items_has_probe_columns_and_composite_index(db_session):
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _replay(connection, module)

    inspector = sa.inspect(connection)
    columns = {c["name"]: c for c in inspector.get_columns("monitor_items")}
    assert set(_PROBE_COLUMNS) <= set(columns)
    for name in _PROBE_COLUMNS:
        # discovery_merge flushes a MonitorItem inside its own transaction
        # without setting any of these, so every one of them must be optional.
        assert columns[name]["nullable"] is True

    indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("monitor_items")}
    assert indexes.get("ix_monitor_items_probe_due") == [
        "probe_agent_id",
        "enabled",
        "next_due_at",
    ]


def test_monitor_probe_runs_partial_unique_index_exists_with_its_predicate(db_session):
    """The uniqueness must be *partial*. A full unique index on `monitor_id`
    would allow exactly one probe run per monitor for the lifetime of the
    install; the predicate is what scopes it to the in-flight statuses."""
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    _replay(connection, module)

    assert _RUNS_TABLE in set(sa.inspect(connection).get_table_names())

    # Read the predicate from `pg_indexes` rather than the inspector: the
    # reflected index dict reports `unique`, but the WHERE clause is the whole
    # point here and only the rendered definition is guaranteed to carry it.
    definition = connection.execute(
        sa.text("SELECT indexdef FROM pg_indexes WHERE tablename = :t AND indexname = :n"),
        {"t": _RUNS_TABLE, "n": "uq_monitor_probe_runs_active"},
    ).scalar()
    assert definition is not None, "the partial unique index is missing entirely"
    assert "UNIQUE INDEX" in definition
    assert "(monitor_id)" in definition
    assert "WHERE" in definition
    assert "'queued'" in definition and "'dispatched'" in definition
