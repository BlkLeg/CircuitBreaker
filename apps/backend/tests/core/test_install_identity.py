"""Unit tests for install identity path resolution and validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.install_identity import (
    InstallIdentityError,
    find_install_identity_path,
    identity_candidate_paths,
    load_install_identity,
    repair_hint_for_mode,
    validate_install_identity,
)


def _minimal_identity(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": 1,
        "mode": "native",
        "version": "0.4.2",
        "installed_at": "2026-09-16T12:00:00Z",
    }
    base.update(overrides)
    return base


def test_validate_accepts_minimal_identity() -> None:
    result = validate_install_identity(_minimal_identity(data_dir="/var/lib/circuitbreaker"))
    assert result["mode"] == "native"
    assert result["data_dir"] == "/var/lib/circuitbreaker"


def test_validate_rejects_bad_mode() -> None:
    with pytest.raises(InstallIdentityError, match="invalid identity mode"):
        validate_install_identity(_minimal_identity(mode="docker"))


def test_validate_rejects_wrong_schema() -> None:
    with pytest.raises(InstallIdentityError, match="schema_version"):
        validate_install_identity(_minimal_identity(schema_version=99))


def test_find_prefers_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    identity = tmp_path / "custom.json"
    identity.write_text(json.dumps(_minimal_identity()), encoding="utf-8")
    monkeypatch.setenv("CB_IDENTITY_PATH", str(identity))
    assert find_install_identity_path(home=tmp_path / "home") == identity


def test_load_reads_data_dir_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CB_IDENTITY_PATH", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "install-identity.json"
    path.write_text(
        json.dumps(_minimal_identity(mode="mono", data_dir=str(data_dir))),
        encoding="utf-8",
    )
    loaded = load_install_identity(data_dir=data_dir, home=tmp_path / "nouser")
    assert loaded["mode"] == "mono"
    assert loaded["_path"] == str(path)


def test_load_missing_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CB_IDENTITY_PATH", raising=False)
    with pytest.raises(InstallIdentityError, match="not found"):
        load_install_identity(data_dir=tmp_path / "empty", home=tmp_path / "home")


def test_candidate_order_includes_system_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CB_IDENTITY_PATH", raising=False)
    paths = identity_candidate_paths(data_dir="/data", home=tmp_path)
    assert Path("/etc/circuitbreaker/install-identity.json") in paths
    assert Path("/data/install-identity.json") in paths
    assert tmp_path / ".circuit-breaker" / "install-identity.json" in paths


def test_repair_hint_is_mode_specific() -> None:
    assert "native installer" in repair_hint_for_mode("native")
    assert "mono" in repair_hint_for_mode("mono").lower() or "/data" in repair_hint_for_mode("mono")


def test_validate_accepts_a_known_runtime() -> None:
    result = validate_install_identity(_minimal_identity(runtime="pbs"))
    assert result["runtime"] == "pbs"


def test_validate_rejects_an_unknown_runtime() -> None:
    with pytest.raises(InstallIdentityError, match="runtime"):
        validate_install_identity(_minimal_identity(runtime="nuitka"))


def test_missing_runtime_stays_valid_and_absent() -> None:
    """Identities written before 2026-09-22 have no runtime; they must still load."""
    result = validate_install_identity(_minimal_identity())
    assert "runtime" not in result
