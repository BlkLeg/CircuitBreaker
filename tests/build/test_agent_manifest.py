"""`make manifest` must not produce a manifest that promises nothing.

`gen_manifest.py` wrote `{version: {}}` whenever its glob matched no binaries —
a cross-compile that silently failed, a wrong DIST, a partial build. The server
then reads that manifest, `agent_update.latest_version()` returns the version
because the key exists, and every install command and update dispatch 404s with
"No binary for linux/amd64 at version X" on a deployment that looked like it
built fine. A build that produced no binaries should fail at build time.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GEN_MANIFEST = REPO_ROOT / "apps" / "agent" / "scripts" / "gen_manifest.py"


def _run(dist: Path, version: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GEN_MANIFEST), str(dist), version],
        capture_output=True,
        text=True,
    )


def test_manifest_records_every_built_binary(tmp_path):
    dist = tmp_path / "0.3.5"
    dist.mkdir()
    (dist / "cb-agent-linux-amd64").write_bytes(b"amd64 binary")
    (dist / "cb-agent-linux-arm64").write_bytes(b"arm64 binary")

    result = _run(dist, "0.3.5")
    assert result.returncode == 0, result.stderr

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert sorted(manifest["0.3.5"]) == ["linux-amd64", "linux-arm64"]
    assert all(len(digest) == 64 for digest in manifest["0.3.5"].values())


def test_manifest_generation_fails_when_no_binary_was_built(tmp_path):
    dist = tmp_path / "0.3.5"
    dist.mkdir()

    result = _run(dist, "0.3.5")

    assert result.returncode != 0, "an empty dist produced a manifest instead of failing"
    assert not (tmp_path / "manifest.json").exists(), "an empty manifest was written anyway"
    assert "0.3.5" in result.stderr or "no " in result.stderr.lower(), result.stderr


def test_manifest_generation_fails_when_the_dist_directory_is_missing(tmp_path):
    result = _run(tmp_path / "does-not-exist", "0.3.5")
    assert result.returncode != 0, "a missing dist directory produced a manifest"
