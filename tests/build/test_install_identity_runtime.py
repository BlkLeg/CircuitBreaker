"""The shell identity writer and validator agree with install_identity.py about `runtime`."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "deploy" / "lib" / "install-identity.sh"
CB = REPO_ROOT / "cb"


def _write(tmp_path: Path, *pairs: str) -> subprocess.CompletedProcess[str]:
    dest = tmp_path / "install-identity.json"
    return subprocess.run(
        ["bash", "-c", f'source "{LIB}" && write_install_identity "{dest}" ' + " ".join(pairs)],
        capture_output=True, text=True, check=False,
    )


def test_shell_writer_records_runtime(tmp_path: Path) -> None:
    result = _write(tmp_path, "mode=native", "version=1.2.3", "runtime=pbs")
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "install-identity.json").read_text())["runtime"] == "pbs"


def test_shell_writer_rejects_an_unknown_runtime(tmp_path: Path) -> None:
    result = _write(tmp_path, "mode=native", "version=1.2.3", "runtime=nuitka")
    assert result.returncode == 1
    assert "runtime" in result.stderr
    assert not (tmp_path / "install-identity.json").exists()


def test_shell_writer_omits_runtime_when_not_given(tmp_path: Path) -> None:
    assert _write(tmp_path, "mode=package", "version=1.2.3").returncode == 0
    assert "runtime" not in json.loads((tmp_path / "install-identity.json").read_text())


def test_shell_validator_rejects_an_unknown_runtime(tmp_path: Path) -> None:
    path = tmp_path / "install-identity.json"
    path.write_text(json.dumps({"schema_version": 1, "mode": "native", "version": "1", "installed_at": "now", "runtime": "nuitka"}))
    result = subprocess.run(["bash", "-c", f'source "{LIB}" && cb_validate_install_identity_file "{path}"'],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1


def test_cb_info_json_reports_runtime(tmp_path: Path) -> None:
    path = tmp_path / "install-identity.json"
    path.write_text(json.dumps({
        "schema_version": 1, "mode": "native", "version": "1.2.3", "installed_at": "2026-09-22T00:00:00Z",
        "runtime": "pbs", "data_dir": str(tmp_path), "cli_path": "/usr/local/bin/cb",
    }))
    result = subprocess.run([str(CB), "info", "--json"], env={"CB_IDENTITY_PATH": str(path), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["runtime"] == "pbs"


def test_cb_and_deploy_cli_cb_are_identical() -> None:
    assert CB.read_bytes() == (REPO_ROOT / "deploy" / "cli" / "cb").read_bytes()
