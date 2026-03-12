import importlib
import os
import sys
from pathlib import Path

import pytest


def _seed_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CB_DB_URL",
        "postgresql://breaker:breaker@localhost:5432/circuitbreaker_test",
    )


def _reload_module(module_name: str):
    original_module = sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    return importlib.reload(module), original_module


def _restore_module(module_name: str, original_module) -> None:
    sys.modules.pop(module_name, None)
    if original_module is not None:
        sys.modules[module_name] = original_module


@pytest.mark.parametrize(
    ("module_name", "path_attr", "file_name"),
    [
        ("app.db.cve_session", "_CVE_DB_PATH", "cve.db"),
        ("app.services.vault_service", "_DATA_ENV_PATH", ".env"),
    ],
)
def test_modules_default_to_workspace_data_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module_name: str,
    path_attr: str,
    file_name: str,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CB_DATA_DIR", raising=False)
    _seed_required_env(monkeypatch)

    module, original_module = _reload_module(module_name)
    try:
        assert getattr(module, path_attr) == tmp_path / "data" / file_name
    finally:
        _restore_module(module_name, original_module)


def test_modules_respect_cb_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    custom_data_dir = tmp_path / "custom-data"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CB_DATA_DIR", os.fspath(custom_data_dir))
    _seed_required_env(monkeypatch)

    cve_session, original_cve_session = _reload_module("app.db.cve_session")
    vault_service, original_vault_service = _reload_module("app.services.vault_service")
    try:
        assert cve_session._CVE_DB_PATH == custom_data_dir / "cve.db"
        assert vault_service._DATA_ENV_PATH == custom_data_dir / ".env"
    finally:
        _restore_module("app.db.cve_session", original_cve_session)
        _restore_module("app.services.vault_service", original_vault_service)
