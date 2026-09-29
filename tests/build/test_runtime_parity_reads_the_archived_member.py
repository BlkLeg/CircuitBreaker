"""The runtime-parity steps extract a member the release tarball actually has.

release.yml and release-dry-run.yml both run
`tar -xzf <tarball> -C <dir> share/build-info.json`, which names the member
exactly: if the archive had a top-level directory (`bundle/share/...`) or a
`./` prefix, tar would exit "Not found in archive" and the parity check would
never run. The selftest step in the dry run tolerates a top-level directory, so
the two steps disagreed about the layout, and neither had executed.

`create_archive` writes every member relative to the bundle root, and the
published v0.4.4 amd64 tarball lists `share/build-info.json` and
`bin/circuit-breaker` at the root, so the member path is right. This holds the
workflows and the packager to that agreement.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_native_release.py"
WORKFLOWS = [
    REPO_ROOT / ".github" / "workflows" / "release.yml",
    REPO_ROOT / ".github" / "workflows" / "release-dry-run.yml",
]
MEMBER = "share/build-info.json"
# `tar -xzf <...circuit-breaker_...tar.gz> -C <dir> <member>`, across a line continuation.
_EXTRACT = re.compile(r'tar -xzf "?[^"\s]*circuit-breaker_[^"\s]*\.tar\.gz"?\s*\\?\s*-C [^ \n]+ (\S+)')


def _load_build_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cb_build_native_release_parity", BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_archive_carries_build_info_at_the_root(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle-linux-amd64"
    (bundle / "share").mkdir(parents=True)
    (bundle / "bin").mkdir()
    (bundle / "share" / "build-info.json").write_text("{}\n", encoding="utf-8")
    (bundle / "bin" / "circuit-breaker").write_text("#!/bin/sh\n", encoding="utf-8")

    archive = _load_build_module().create_archive(bundle, "0.0.0", "linux", "amd64", tmp_path / "out")
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
    assert MEMBER in names, f"create_archive no longer puts {MEMBER} at the root: {sorted(names)}"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_the_parity_step_extracts_that_member(workflow: Path) -> None:
    members = _EXTRACT.findall(workflow.read_text(encoding="utf-8"))
    assert members, f"{workflow.name} no longer extracts a named member from the release tarball"
    assert set(members) == {MEMBER}, (
        f"{workflow.name} extracts {members} from the release tarball; the archive holds {MEMBER}"
    )
