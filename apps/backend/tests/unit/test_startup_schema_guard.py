import pytest

import app.main as main


def test_assert_required_schema_retries_migration_once(monkeypatch):
    table_states = iter(
        [
            {"app_settings"},
            {"app_settings", "status_pages", "webhook_rules"},
        ]
    )
    upgrade_calls = []

    monkeypatch.setattr(main, "_get_existing_schema_tables", lambda: next(table_states))
    monkeypatch.setattr(main, "run_alembic_upgrade", lambda: upgrade_calls.append("upgrade"))

    main._assert_required_schema()

    assert upgrade_calls == ["upgrade"]


def test_assert_required_schema_exits_when_schema_still_missing(monkeypatch):
    monkeypatch.setattr(main, "_get_existing_schema_tables", lambda: {"app_settings"})
    monkeypatch.setattr(main, "run_alembic_upgrade", lambda: None)

    with pytest.raises(SystemExit) as exc_info:
        main._assert_required_schema()

    assert exc_info.value.code == 1
