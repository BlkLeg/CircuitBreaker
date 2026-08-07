"""Schema-level guarantees for the agent spool-state columns (Task 16, D-12).

`agents.spool_depth` / `spool_bytes` / `spool_reported_at` are what the Agent
Detail catch-up indicator reads, and they are the only user-visible evidence
that Task 13's bounded catch-up drain is making progress.

Two things are pinned here:

1. Migration `0097_agent_spool_state` chains onto `0096`, adds all three
   columns as nullable, is idempotent, and its `downgrade` really drops them.
2. Nothing backfills them. NULL means "never reported" (an agent whose build
   predates `HeartbeatPayload`); 0 means "reported, and the spool is empty".
   A backfill to 0 would claim a report that never happened.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.db.models import Agent

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
_MIGRATION = "0097_agent_spool_state"
_COLUMNS = ("spool_depth", "spool_bytes", "spool_reported_at")


def _load_migration(name: str):
    """`migrations/versions` is not a package, so import by file path."""
    path = _VERSIONS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0097_chains_onto_0096():
    module = _load_migration(_MIGRATION)

    assert module.revision == _MIGRATION
    assert module.down_revision == "0096_drop_agent_projection_attempts"


def test_migration_0097_is_the_only_child_of_0096():
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
                and node.value.value == "0096_drop_agent_projection_attempts"
            ):
                children.append(path.name)

    assert children == [f"{_MIGRATION}.py"]


def test_agent_model_declares_the_three_nullable_spool_columns():
    for name in _COLUMNS:
        column = Agent.__table__.columns[name]
        assert column.nullable is True, f"{name} must be nullable — NULL means 'never reported'"


@pytest.mark.parametrize("run", [1, 2])
def test_migration_0097_upgrade_is_idempotent(db_session, run):
    """The columns already exist (the test schema is built from the models),
    so every pass must be a clean no-op rather than a duplicate-column error."""
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    for _ in range(run):
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.upgrade()

    columns = {c["name"] for c in sa.inspect(connection).get_columns("agents")}
    assert set(_COLUMNS) <= columns


def test_migration_0097_downgrade_drops_the_columns_and_upgrade_restores_them(db_session):
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.downgrade()
    columns = {c["name"] for c in sa.inspect(connection).get_columns("agents")}
    assert not (set(_COLUMNS) & columns)

    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.upgrade()
    restored = {c["name"]: c for c in sa.inspect(connection).get_columns("agents")}
    assert set(_COLUMNS) <= set(restored)
    for name in _COLUMNS:
        assert restored[name]["nullable"] is True


def test_migration_0097_backfills_nothing(db_session, factories):
    """No UPDATE/INSERT in the migration body, and an existing row is left
    NULL by a replay: an agent that has never reported must not be given a
    fabricated depth of 0, which the UI would read as "reported, drained"."""
    source = (_VERSIONS_DIR / f"{_MIGRATION}.py").read_text().lower()
    assert "update " not in source
    assert "insert " not in source

    agent = factories.agent(status="active")
    module = _load_migration(_MIGRATION)
    connection = db_session.get_bind()
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        module.upgrade()

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.spool_depth is None
    assert refreshed.spool_bytes is None
    assert refreshed.spool_reported_at is None
