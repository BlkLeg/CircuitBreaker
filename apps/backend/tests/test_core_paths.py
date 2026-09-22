"""`app.core.paths` is the one place `CB_DATA_DIR` and `UPLOADS_DIR` resolve.

Before this module existed, the same `CB_DATA_DIR or Path.cwd()/"data"`
formula was hand-copied into `app.db.cve_session`, `app.services.vault_service`
and `app.services.auth_service`, each as a module-level constant computed
once at import — which is what made a monkeypatched `CB_DATA_DIR` invisible to
them after the fact, and what this test proves is no longer true.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.paths import data_dir, uploads_dir


def test_data_dir_uses_cb_data_dir_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CB_DATA_DIR", "/tmp/example-data")
    assert data_dir() == Path("/tmp/example-data")


def test_data_dir_falls_back_to_cwd_data_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CB_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert data_dir() == tmp_path / "data"


def test_data_dir_expands_a_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CB_DATA_DIR", "~/cb-data")
    assert data_dir() == Path.home() / "cb-data"


def test_uploads_dir_derives_from_data_dir_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CB_DATA_DIR", "/tmp/example-data")
    monkeypatch.setattr("app.core.paths.settings.uploads_dir", "")
    assert uploads_dir() == Path("/tmp/example-data/uploads")


def test_uploads_dir_explicit_override_wins_even_against_a_different_data_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CB_DATA_DIR", "/tmp/example-data")
    monkeypatch.setattr("app.core.paths.settings.uploads_dir", "/data/uploads")
    assert uploads_dir() == Path("/data/uploads")


def test_data_dir_reflects_a_change_made_after_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bug class this module exists to close: no module may cache this."""
    monkeypatch.setenv("CB_DATA_DIR", "/tmp/first")
    assert data_dir() == Path("/tmp/first")
    monkeypatch.setenv("CB_DATA_DIR", "/tmp/second")
    assert data_dir() == Path("/tmp/second")


@pytest.mark.parametrize(
    ("module_path", "attr"),
    [
        ("app.db.cve_session", "_cve_db_path"),
        ("app.services.vault_service", "_data_env_path"),
        ("app.services.auth_service", "_bootstrap_token_file_path"),
    ],
)
def test_migrated_call_sites_follow_a_monkeypatched_cb_data_dir(
    monkeypatch: pytest.MonkeyPatch, module_path: str, attr: str
) -> None:
    """Each of these used to be a module-level constant computed once at
    import; a CB_DATA_DIR change afterwards was invisible to it. All three now
    go through app.core.paths.data_dir(), which reads the environment fresh
    on every call.
    """
    import importlib

    module = importlib.import_module(module_path)
    fn = getattr(module, attr)

    monkeypatch.setenv("CB_DATA_DIR", "/tmp/probe-one")
    first = str(fn())
    assert first.startswith("/tmp/probe-one/"), f"{module_path}.{attr}() = {first!r}"

    monkeypatch.setenv("CB_DATA_DIR", "/tmp/probe-two")
    second = str(fn())
    assert second.startswith("/tmp/probe-two/"), f"{module_path}.{attr}() = {second!r}"
