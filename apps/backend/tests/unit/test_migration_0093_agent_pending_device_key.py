"""
Test migration 0093: agents.pending_device_pk / pending_device_pk_expiry columns (Task 27).

Tests verify:
1. Migration file exists and is loadable
2. Migration has correct revision properties and down_revision chain
3. Migration adds both columns (and the pending_device_pk index) as per database schema
"""

from pathlib import Path

import pytest


def _load_migration_module():
    import importlib.util

    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0093_agent_pending_device_key.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0093", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load migration 0093 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_module_exists():
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0093_agent_pending_device_key.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"


def test_migration_revision_properties():
    module = _load_migration_module()

    assert module.revision == "0093_agent_pending_device_key"
    assert module.down_revision == "0092_agent_pending_update_version"
    assert hasattr(module, "upgrade")
    assert hasattr(module, "downgrade")
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_schema_has_pending_device_key_columns(setup_db):
    """Integration test: verify agents table has both new columns and the index."""
    from sqlalchemy import inspect as sa_inspect

    from app.db.session import engine

    insp = sa_inspect(engine)
    col_info = {c["name"]: c for c in insp.get_columns("agents")}

    assert "pending_device_pk" in col_info
    assert col_info["pending_device_pk"].get("nullable") is True

    assert "pending_device_pk_expiry" in col_info
    assert col_info["pending_device_pk_expiry"].get("nullable") is True

    indexes = {idx["name"] for idx in insp.get_indexes("agents")}
    assert "ix_agents_pending_device_pk" in indexes, (
        f"ix_agents_pending_device_pk index should exist. Available indexes: {indexes}"
    )


def test_agent_model_has_pending_device_key_columns():
    from app.db.models import Agent

    assert hasattr(Agent, "pending_device_pk")
    assert hasattr(Agent, "pending_device_pk_expiry")

    mapper = Agent.__mapper__
    assert "pending_device_pk" in mapper.columns
    assert mapper.columns["pending_device_pk"].nullable is True
    assert "pending_device_pk_expiry" in mapper.columns
    assert mapper.columns["pending_device_pk_expiry"].nullable is True


@pytest.mark.asyncio
async def test_can_set_and_clear_pending_device_key(setup_db, db_session, factories):
    from datetime import UTC, datetime

    from app.db.models import Agent

    agent = factories.agent(status="active")
    db_session.commit()

    fresh = db_session.query(Agent).filter_by(id=agent.id).first()
    assert fresh.pending_device_pk is None
    assert fresh.pending_device_pk_expiry is None

    expiry = datetime.now(UTC)
    fresh.pending_device_pk = "ab" * 32
    fresh.pending_device_pk_expiry = expiry
    db_session.commit()

    reloaded = db_session.query(Agent).filter_by(id=agent.id).first()
    assert reloaded.pending_device_pk == "ab" * 32
    assert reloaded.pending_device_pk_expiry is not None

    reloaded.pending_device_pk = None
    reloaded.pending_device_pk_expiry = None
    db_session.commit()

    cleared = db_session.query(Agent).filter_by(id=agent.id).first()
    assert cleared.pending_device_pk is None
    assert cleared.pending_device_pk_expiry is None


def test_migration_column_addition_logic():
    import inspect as py_inspect

    module = _load_migration_module()
    upgrade_source = py_inspect.getsource(module.upgrade)

    assert "sa_inspect" in upgrade_source, "upgrade should use sa_inspect for idempotency"
    assert "pending_device_pk" in upgrade_source
    assert "pending_device_pk_expiry" in upgrade_source
    assert "add_column" in upgrade_source
    assert "create_index" in upgrade_source


def test_migration_downgrade_removes_columns_and_index():
    import inspect as py_inspect

    module = _load_migration_module()
    downgrade_source = py_inspect.getsource(module.downgrade)

    assert "pending_device_pk" in downgrade_source
    assert "pending_device_pk_expiry" in downgrade_source
    assert "drop_column" in downgrade_source
    assert "drop_index" in downgrade_source
