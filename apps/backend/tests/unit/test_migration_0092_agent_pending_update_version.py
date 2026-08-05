"""
Test migration 0092: agents.pending_update_version column.

Tests verify:
1. Migration file exists and is loadable
2. Migration has correct revision properties and down_revision chain
3. Migration adds the column as per database schema
"""

from pathlib import Path

import pytest


def test_migration_module_exists():
    """Test that migration 0092 module can be found."""
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0092_agent_pending_update_version.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"


def test_migration_revision_properties():
    """Test that migration has correct revision properties."""
    import importlib.util

    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0092_agent_pending_update_version.py"
    )

    spec = importlib.util.spec_from_file_location("migration_0092", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load migration 0092 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "0092_agent_pending_update_version"
    assert module.down_revision == "0091_hardware_machine_id_hash"
    assert hasattr(module, "upgrade"), "Migration should have upgrade function"
    assert hasattr(module, "downgrade"), "Migration should have downgrade function"
    assert callable(module.upgrade), "upgrade should be callable"
    assert callable(module.downgrade), "downgrade should be callable"


def test_schema_has_pending_update_version_column(setup_db):
    """Integration test: verify agents table has pending_update_version column."""
    from sqlalchemy import inspect as sa_inspect

    from app.db.session import engine

    # After setup_db fixture, the schema is created from current models, which
    # now includes the pending_update_version column added by the migration.
    insp = sa_inspect(engine)

    cols = {c["name"] for c in insp.get_columns("agents")}
    assert "pending_update_version" in cols, (
        "pending_update_version column should exist in agents table"
    )

    col_info = {c["name"]: c for c in insp.get_columns("agents")}
    col = col_info.get("pending_update_version")
    assert col is not None
    assert col.get("nullable") is True, "pending_update_version should be nullable"


def test_agent_model_has_pending_update_version():
    """Test that Agent SQLAlchemy model defines pending_update_version column."""
    from app.db.models import Agent

    assert hasattr(Agent, "pending_update_version")

    mapper = Agent.__mapper__
    assert "pending_update_version" in mapper.columns
    col = mapper.columns["pending_update_version"]
    assert col.nullable is True


@pytest.mark.asyncio
async def test_can_set_and_clear_pending_update_version(setup_db, db_session, factories):
    """Integration test: verify agents can carry a pending_update_version and
    have it cleared, the two operations Task 24's update lifecycle depends on."""
    from app.db.models import Agent

    agent = factories.agent(status="active")
    db_session.commit()

    fresh = db_session.query(Agent).filter_by(id=agent.id).first()
    assert fresh.pending_update_version is None

    fresh.pending_update_version = "0.2.0"
    db_session.commit()

    reloaded = db_session.query(Agent).filter_by(id=agent.id).first()
    assert reloaded.pending_update_version == "0.2.0"

    reloaded.pending_update_version = None
    db_session.commit()

    cleared = db_session.query(Agent).filter_by(id=agent.id).first()
    assert cleared.pending_update_version is None


def test_migration_column_addition_logic():
    """Test that migration has idempotent column addition logic."""
    import importlib.util
    import inspect as py_inspect

    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0092_agent_pending_update_version.py"
    )

    spec = importlib.util.spec_from_file_location("migration_0092", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load migration 0092 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    upgrade_source = py_inspect.getsource(module.upgrade)
    assert "sa_inspect" in upgrade_source, "upgrade should use sa_inspect for idempotency"
    assert "pending_update_version" in upgrade_source
    assert "add_column" in upgrade_source, "upgrade should call op.add_column"


def test_migration_downgrade_removes_column():
    """Test that downgrade function removes the column."""
    import importlib.util
    import inspect as py_inspect

    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0092_agent_pending_update_version.py"
    )

    spec = importlib.util.spec_from_file_location("migration_0092", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load migration 0092 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    downgrade_source = py_inspect.getsource(module.downgrade)
    assert "pending_update_version" in downgrade_source
    assert "drop_column" in downgrade_source
