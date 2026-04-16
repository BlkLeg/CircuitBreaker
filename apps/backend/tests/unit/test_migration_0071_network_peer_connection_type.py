import importlib.util
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0071_network_peer_connection_type.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("migration_0071", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load migration 0071 module")
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


def test_upgrade_uses_schema_qualified_if_not_exists(monkeypatch) -> None:
    migration = _load_migration_module()
    conn = _FakeConnection()
    monkeypatch.setattr(migration.op, "get_bind", lambda: conn)

    migration.upgrade()

    assert (
        'ALTER TABLE "public".network_peers ADD COLUMN IF NOT EXISTS connection_type VARCHAR'
        in conn.executed_sql
    )
    assert (
        'ALTER TABLE "public".network_peers ADD COLUMN IF NOT EXISTS bandwidth_mbps INTEGER'
        in conn.executed_sql
    )


def test_downgrade_uses_schema_qualified_if_exists(monkeypatch) -> None:
    migration = _load_migration_module()
    conn = _FakeConnection()
    monkeypatch.setattr(migration.op, "get_bind", lambda: conn)

    migration.downgrade()

    assert (
        'ALTER TABLE "public".network_peers DROP COLUMN IF EXISTS bandwidth_mbps'
        in conn.executed_sql
    )
    assert (
        'ALTER TABLE "public".network_peers DROP COLUMN IF EXISTS connection_type'
        in conn.executed_sql
    )
