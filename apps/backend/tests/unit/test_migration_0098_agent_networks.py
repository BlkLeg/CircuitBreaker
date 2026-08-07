"""Schema-level guarantees for `agent_networks` (Task 2, D-1).

The table holds one current normalized network report per agent — the whole
input to the slice-3 scope evaluator — so the guarantees that matter here are
that the migration is reachable (a single head chaining onto `0097`) and that
running it really produces the table plus the one-row-per-agent unique index.
Mirrors `tests/unit/test_migration_0093_agent_pending_device_key.py`, with the
second-head guard from `tests/test_agent_spool_schema.py`.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"
_MIGRATION = "0098_agent_networks"
_PARENT = "0097_agent_spool_state"
_TABLE = "agent_networks"


def _load_migration(name: str):
    """`migrations/versions` is not a package, so import by file path."""
    path = _VERSIONS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_file_exists():
    assert (_VERSIONS_DIR / f"{_MIGRATION}.py").exists()


def test_revision_chains_onto_0097():
    module = _load_migration(_MIGRATION)

    assert module.revision == _MIGRATION
    assert module.down_revision == _PARENT


def test_migration_0098_is_the_only_child_of_0097():
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


def test_agent_networks_table_and_indexes_exist(db_session):
    """Drive the migration itself rather than the models-built test schema:
    `agent_networks` is in 0001_init's `_EXCLUDED_TABLES`, so on a fresh
    install this migration is the *only* thing that creates it."""
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.downgrade()
    assert _TABLE not in set(sa.inspect(connection).get_table_names())

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.upgrade()

    inspector = sa.inspect(connection)
    assert _TABLE in set(inspector.get_table_names())

    columns = {c["name"]: c for c in inspector.get_columns(_TABLE)}
    assert set(columns) >= {"id", "agent_id", "generation", "observed_at", "facts"}
    for name in ("agent_id", "generation", "observed_at", "facts"):
        assert columns[name]["nullable"] is False

    unique = {tuple(c["column_names"]) for c in inspector.get_unique_constraints(_TABLE)}
    assert ("agent_id",) in unique, f"one report per agent must be enforced, got {unique}"

    fks = {
        (tuple(fk["constrained_columns"]), fk["referred_table"], fk["options"].get("ondelete"))
        for fk in inspector.get_foreign_keys(_TABLE)
    }
    assert (("agent_id",), "agents", "CASCADE") in fks
