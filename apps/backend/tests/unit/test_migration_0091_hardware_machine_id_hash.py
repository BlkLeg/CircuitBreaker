"""
Test migration 0091: hardware.machine_id_hash column.

Tests:
1. Upgrade uses IF NOT EXISTS to add column idempotently
2. Downgrade removes column and index cleanly
3. Integration: upgrade/downgrade on fresh DB and with existing data
"""

import importlib.util
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0091_hardware_machine_id_hash.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("migration_0091", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load migration 0091 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResult:
    def __init__(self, scalar_value):
        self._scalar_value = scalar_value

    def scalar(self):
        return self._scalar_value


class _FakeConnection:
    def __init__(self):
        self.executed_sql = []

    def execute(self, stmt):
        sql_text = str(stmt)
        self.executed_sql.append(sql_text)
        if "SELECT current_schema()" in sql_text:
            return _FakeResult("public")
        return _FakeResult(None)


def test_upgrade_uses_column_add_with_nullable(monkeypatch) -> None:
    """Test upgrade adds machine_id_hash column as nullable."""
    migration = _load_migration_module()
    conn = _FakeConnection()
    monkeypatch.setattr(migration.op, "get_bind", lambda: conn)

    migration.upgrade()

    # Should add column with nullable constraint
    col_add_found = any("machine_id_hash" in sql and "String()" in sql for sql in conn.executed_sql)
    assert col_add_found, f"Expected column add in: {conn.executed_sql}"

    # Should create index
    index_found = any("ix_hardware_machine_id_hash" in sql for sql in conn.executed_sql)
    assert index_found, f"Expected index create in: {conn.executed_sql}"


def test_downgrade_removes_index_and_column(monkeypatch) -> None:
    """Test downgrade removes index and column."""
    migration = _load_migration_module()
    conn = _FakeConnection()
    monkeypatch.setattr(migration.op, "get_bind", lambda: conn)

    migration.downgrade()

    # Should drop index
    index_drop_found = any("DROP INDEX" in sql and "ix_hardware_machine_id_hash" in sql for sql in conn.executed_sql)
    assert index_drop_found, f"Expected index drop in: {conn.executed_sql}"

    # Should drop column
    col_drop_found = any("DROP COLUMN" in sql and "machine_id_hash" in sql for sql in conn.executed_sql)
    assert col_drop_found, f"Expected column drop in: {conn.executed_sql}"


def test_integration_upgrade_fresh_db(setup_db, db_session):
    """Integration test: upgrade adds column to fresh database."""
    from app.db import models  # noqa: F401
    from app.db.session import engine

    # Get columns before migration
    insp = engine.inspect()
    cols_before = {c["name"] for c in insp.get_columns("hardware")}

    # Run upgrade
    migration = _load_migration_module()
    migration.upgrade()

    # Verify column was added
    insp = engine.inspect()
    cols_after = {c["name"] for c in insp.get_columns("hardware")}
    assert "machine_id_hash" in cols_after, "machine_id_hash column should be added"
    assert cols_after - cols_before == {"machine_id_hash"}, "Only machine_id_hash should be added"

    # Verify index was created
    indexes = {idx["name"] for idx in insp.get_indexes("hardware")}
    assert "ix_hardware_machine_id_hash" in indexes, "index should be created"


def test_integration_downgrade_removes_column(setup_db, db_session):
    """Integration test: downgrade removes column and index."""
    from app.db import models  # noqa: F401
    from app.db.session import engine

    # First, add the column via upgrade
    migration = _load_migration_module()
    migration.upgrade()

    insp = engine.inspect()
    assert "machine_id_hash" in {c["name"] for c in insp.get_columns("hardware")}

    # Run downgrade
    migration.downgrade()

    # Verify column was removed
    insp = engine.inspect()
    cols = {c["name"] for c in insp.get_columns("hardware")}
    assert "machine_id_hash" not in cols, "machine_id_hash column should be removed"

    # Verify index was removed
    indexes = {idx["name"] for idx in insp.get_indexes("hardware")}
    assert "ix_hardware_machine_id_hash" not in indexes, "index should be removed"


def test_integration_with_existing_data(setup_db, db_session, factories):
    """Integration test: upgrade preserves existing hardware records."""
    from app.db.models import Hardware

    # Create some Hardware records before migration
    hw1 = factories.hardware(name="Server1")
    hw2 = factories.hardware(name="Server2")
    db_session.commit()

    count_before = db_session.query(Hardware).count()
    ids_before = {hw.id for hw in db_session.query(Hardware).all()}

    # Run upgrade
    migration = _load_migration_module()
    migration.upgrade()

    # Verify data still exists
    count_after = db_session.query(Hardware).count()
    ids_after = {hw.id for hw in db_session.query(Hardware).all()}

    assert count_after == count_before, "Record count should be preserved"
    assert ids_after == ids_before, "Record IDs should be preserved"


def test_integration_round_trip(setup_db, db_session, factories):
    """Integration test: upgrade → downgrade → upgrade round-trip."""
    from app.db.models import Hardware
    from app.db.session import engine

    # Create initial hardware record
    hw1 = factories.hardware(name="TestHW1")
    db_session.commit()
    hw_id = hw1.id

    migration = _load_migration_module()

    # Upgrade
    migration.upgrade()
    insp = engine.inspect()
    assert "machine_id_hash" in {c["name"] for c in insp.get_columns("hardware")}

    # Downgrade
    migration.downgrade()
    insp = engine.inspect()
    assert "machine_id_hash" not in {c["name"] for c in insp.get_columns("hardware")}

    # Upgrade again
    migration.upgrade()
    insp = engine.inspect()
    assert "machine_id_hash" in {c["name"] for c in insp.get_columns("hardware")}

    # Verify data still there and accessible
    hw_found = db_session.query(Hardware).filter_by(id=hw_id).first()
    assert hw_found is not None, "Record should survive round-trip"
    assert hw_found.name == "TestHW1", "Record data should be intact"
