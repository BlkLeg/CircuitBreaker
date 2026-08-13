"""
Test migration 0091: hardware.machine_id_hash column.

Tests verify:
1. Migration file exists and is loadable
2. Migration has correct revision properties and down_revision chain
3. Migration adds column and index as per database schema
"""

from pathlib import Path


def test_migration_module_exists():
    """Test that migration 0091 module can be found."""
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0091_hardware_machine_id_hash.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"


def test_migration_revision_properties():
    """Test that migration has correct revision properties."""
    import importlib.util

    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0091_hardware_machine_id_hash.py"
    )

    spec = importlib.util.spec_from_file_location("migration_0091", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load migration 0091 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "0091_hardware_machine_id_hash"
    assert module.down_revision == "0090_agent_server_private_key"
    assert hasattr(module, "upgrade"), "Migration should have upgrade function"
    assert hasattr(module, "downgrade"), "Migration should have downgrade function"
    assert callable(module.upgrade), "upgrade should be callable"
    assert callable(module.downgrade), "downgrade should be callable"


def test_schema_has_machine_id_hash_column(setup_db):
    """Integration test: verify Hardware table has machine_id_hash column and index."""
    from sqlalchemy import inspect as sa_inspect

    from app.db.session import engine

    # After setup_db fixture, the schema should be created from current models,
    # which now includes the machine_id_hash column added by the migration.
    insp = sa_inspect(engine)

    # Verify machine_id_hash column exists
    cols = {c["name"] for c in insp.get_columns("hardware")}
    assert "machine_id_hash" in cols, "machine_id_hash column should exist in hardware table"

    # Verify column is nullable
    col_info = {c["name"]: c for c in insp.get_columns("hardware")}
    machine_id_col = col_info.get("machine_id_hash")
    assert machine_id_col is not None, "machine_id_hash column should exist"
    assert machine_id_col.get("nullable") is True, "machine_id_hash should be nullable"

    # Verify index exists
    indexes = {idx["name"] for idx in insp.get_indexes("hardware")}
    assert "ix_hardware_machine_id_hash" in indexes, (
        f"ix_hardware_machine_id_hash index should exist. Available indexes: {indexes}"
    )


def test_hardware_model_has_machine_id_hash():
    """Test that Hardware SQLAlchemy model defines machine_id_hash column."""
    from app.db.models import Hardware

    # Verify the model has the attribute
    assert hasattr(Hardware, "machine_id_hash"), (
        "Hardware model should have machine_id_hash attribute"
    )

    # Verify the column is mapped
    mapper = Hardware.__mapper__
    assert "machine_id_hash" in mapper.columns, "machine_id_hash should be in Hardware mapper"

    # Verify the column properties
    col = mapper.columns["machine_id_hash"]
    assert col.nullable is True, "machine_id_hash column should be nullable"
    assert col.index is True, "machine_id_hash column should be indexed"


def test_can_query_hardware_with_machine_id_hash(setup_db, db_session, factories):
    """Integration test: verify Hardware records can include machine_id_hash."""
    from app.db.models import Hardware

    # Create a hardware record with no machine_id_hash (should be NULL)
    factories.hardware(name="NoHash")
    db_session.commit()

    # Query it back
    hw_found = db_session.query(Hardware).filter_by(name="NoHash").first()
    assert hw_found is not None, "Hardware record should be found"
    assert hw_found.machine_id_hash is None, "machine_id_hash should be NULL for new record"

    # Create a hardware record and manually set machine_id_hash
    hw2 = factories.hardware(name="WithHash")
    hw2.machine_id_hash = "abc123def456"
    db_session.commit()

    # Query it back with the hash
    hw_found2 = db_session.query(Hardware).filter_by(name="WithHash").first()
    assert hw_found2 is not None, "Hardware record should be found"
    assert hw_found2.machine_id_hash == "abc123def456", "machine_id_hash should be retrieved"

    # Query by machine_id_hash (verify index is functional)
    hw_by_hash = db_session.query(Hardware).filter_by(machine_id_hash="abc123def456").first()
    assert hw_by_hash is not None, "Should be able to query by machine_id_hash"
    assert hw_by_hash.name == "WithHash", "Should retrieve correct record"


def test_migration_column_addition_logic():
    """Test that migration has idempotent column addition logic."""
    import importlib.util

    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0091_hardware_machine_id_hash.py"
    )

    spec = importlib.util.spec_from_file_location("migration_0091", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load migration 0091 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Verify the upgrade function uses sa_inspect to check for existing column
    import inspect as py_inspect

    upgrade_source = py_inspect.getsource(module.upgrade)
    assert "sa_inspect" in upgrade_source, "upgrade should use sa_inspect for idempotency"
    assert "machine_id_hash" in upgrade_source, "upgrade should mention machine_id_hash"
    assert "add_column" in upgrade_source, "upgrade should call op.add_column"
    assert "create_index" in upgrade_source, "upgrade should create an index"


def test_migration_downgrade_removes_column():
    """Test that downgrade function removes column and index."""
    import importlib.util

    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0091_hardware_machine_id_hash.py"
    )

    spec = importlib.util.spec_from_file_location("migration_0091", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load migration 0091 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    import inspect as py_inspect

    downgrade_source = py_inspect.getsource(module.downgrade)
    assert "machine_id_hash" in downgrade_source, "downgrade should mention machine_id_hash"
    assert "drop_index" in downgrade_source, "downgrade should call op.drop_index"
    assert "drop_column" in downgrade_source, "downgrade should call op.drop_column"
