from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "assert_runtime_parity.py"
BASE = {"runtime": "pbs", "python": "3.12.9", "pbs_release": "r", "pbs_sha256": "a" * 64,
        "lock_sha256": "b" * 64, "runtime_digest": "c" * 64, "arch": "amd64", "built_by": "ci"}


def _run(tmp_path: Path, native: dict, image: dict) -> subprocess.CompletedProcess[str]:
    (tmp_path / "native.json").write_text(json.dumps(native))
    (tmp_path / "image.json").write_text(json.dumps(image))
    return subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "native.json"), str(tmp_path / "image.json")],
                          capture_output=True, text=True, check=False)


def test_equal_provenance_passes(tmp_path: Path) -> None:
    assert _run(tmp_path, BASE, dict(BASE, built_by="local")).returncode == 0


def test_a_different_digest_fails_and_names_the_field(tmp_path: Path) -> None:
    result = _run(tmp_path, BASE, dict(BASE, runtime_digest="d" * 64))
    assert result.returncode == 1 and "runtime_digest" in result.stdout + result.stderr


def test_a_missing_field_fails(tmp_path: Path) -> None:
    image = dict(BASE)
    del image["lock_sha256"]
    assert _run(tmp_path, BASE, image).returncode == 1
