import importlib.util
import os
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

_REAL_CREATE_ENGINE = sa.create_engine


os.environ.setdefault(
    "CB_DB_URL",
    "postgresql://breaker:test@127.0.0.1:5432/circuitbreaker",
)


def _root_revision_module():
    for module_name in ("app.main", "app.db.models", "app.db.session"):
        sys.modules.pop(module_name, None)
    migration_path = (
        Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0001_init.py"
    )
    spec = importlib.util.spec_from_file_location("cb_migration_0001", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_main_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        sa,
        "create_engine",
        lambda *_args, **_kwargs: _REAL_CREATE_ENGINE("sqlite:///:memory:"),
    )
    for module_name in ("app.main", "app.db.models", "app.db.session"):
        sys.modules.pop(module_name, None)
    from app import main as main_module

    return main_module


def test_root_bootstrap_metadata_includes_core_tables_and_excludes_later_ones(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        sa,
        "create_engine",
        lambda *_args, **_kwargs: _REAL_CREATE_ENGINE("sqlite:///:memory:"),
    )
    root_revision = _root_revision_module()

    metadata = root_revision._build_bootstrap_metadata()

    assert "app_settings" in metadata.tables
    assert "users" in metadata.tables
    assert "hardware" in metadata.tables
    assert "scan_jobs" in metadata.tables
    assert "status_pages" not in metadata.tables
    assert "webhook_rules" not in metadata.tables
    assert "api_tokens" not in metadata.tables

    assert "listener_enabled" not in metadata.tables["app_settings"].c
    assert "self_cluster_enabled" not in metadata.tables["app_settings"].c
    assert "proxmox_node_name" not in metadata.tables["hardware"].c
    assert "integration_config_id" not in metadata.tables["storage"].c
    assert "team_id" not in metadata.tables["networks"].c
    assert "color" not in metadata.tables["tags"].c
    assert metadata.tables["hardware_cluster_members"].c.hardware_id.nullable is False


def test_root_bootstrap_metadata_create_all_emits_single_discovery_profile_index(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        sa,
        "create_engine",
        lambda *_args, **_kwargs: _REAL_CREATE_ENGINE("sqlite:///:memory:"),
    )
    root_revision = _root_revision_module()
    metadata = root_revision._build_bootstrap_metadata()

    discovery_profile_indexes = {
        index.name for index in metadata.tables["discovery_profiles"].indexes
    }
    assert "ix_discovery_profiles_id" in discovery_profile_indexes
    assert len(discovery_profile_indexes) == len(metadata.tables["discovery_profiles"].indexes)

    ddl_statements: list[str] = []
    engine = sa.create_mock_engine(
        "postgresql://",
        lambda sql, *_multiparams, **_params: ddl_statements.append(
            str(sql.compile(dialect=engine.dialect))
        ),
    )
    metadata.create_all(bind=engine, checkfirst=False)

    discovery_profile_index_ddl = [
        statement
        for statement in ddl_statements
        if "CREATE INDEX ix_discovery_profiles_id ON discovery_profiles" in statement
    ]
    assert len(discovery_profile_index_ddl) == 1


def test_run_alembic_upgrade_empty_db_uses_upgrade_only(monkeypatch: pytest.MonkeyPatch):
    import alembic.command

    main_module = _load_main_module(monkeypatch)
    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    monkeypatch.setenv("CB_ALEMBIC_INI", str(alembic_ini))
    monkeypatch.setenv("ALEMBIC_CONFIG", str(alembic_ini))

    calls: list[tuple[str, str | None]] = []

    class _Inspector:
        @staticmethod
        def get_table_names():
            return []

    monkeypatch.setattr(sa, "inspect", lambda _engine: _Inspector())
    monkeypatch.setattr(
        alembic.command,
        "upgrade",
        lambda _cfg, revision: calls.append(("upgrade", revision)),
    )
    monkeypatch.setattr(
        alembic.command,
        "stamp",
        lambda _cfg, revision: calls.append(("stamp", revision)),
    )

    main_module.run_alembic_upgrade()

    assert ("upgrade", "head") in calls
    assert not any(action == "stamp" for action, _ in calls)


def test_run_alembic_upgrade_legacy_db_stamps_then_upgrades(monkeypatch: pytest.MonkeyPatch):
    import alembic.command

    main_module = _load_main_module(monkeypatch)
    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    monkeypatch.setenv("CB_ALEMBIC_INI", str(alembic_ini))
    monkeypatch.setenv("ALEMBIC_CONFIG", str(alembic_ini))

    calls: list[tuple[str, str | None]] = []

    class _Inspector:
        @staticmethod
        def get_table_names():
            return ["users"]

    monkeypatch.setattr(sa, "inspect", lambda _engine: _Inspector())
    monkeypatch.setattr(
        alembic.command,
        "upgrade",
        lambda _cfg, revision: calls.append(("upgrade", revision)),
    )
    monkeypatch.setattr(
        alembic.command,
        "stamp",
        lambda _cfg, revision: calls.append(("stamp", revision)),
    )

    main_module.run_alembic_upgrade()

    assert ("stamp", "a3b4c5d6e7fc") in calls
    assert ("upgrade", "head") in calls


def test_schema_guard_raises_clear_error_when_required_tables_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    main_module = _load_main_module(monkeypatch)

    class _Inspector:
        @staticmethod
        def get_table_names():
            return ["users", "alembic_version"]

    monkeypatch.setattr(sa, "inspect", lambda _engine: _Inspector())

    with pytest.raises(SystemExit):
        main_module._assert_required_schema()
