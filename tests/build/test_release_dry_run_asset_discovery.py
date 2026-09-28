"""The dry run's asset-discovery step, executed against the real install.sh.

"Verify the staged release" failed on its first execution expecting an asset
named `$2`. Its inline Python took the FIRST `tarball_name="..."` in
install.sh, which is `local tarball_name="$2"` — a parameter of
`cb_verify_bundle_checksum` — rather than the template install.sh actually
downloads. This runs the step's own `run:` block, byte for byte, in a scratch
directory holding the real install.sh and a staged dist/release with the two
tarballs a build produces, so the step is exercised rather than described.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DRY_RUN = REPO_ROOT / ".github" / "workflows" / "release-dry-run.yml"
STEP_NAME = "Assert install.sh can discover every asset it asks for"
VERSION = "9.8.7"


def _discovery_step() -> dict[str, Any]:
    jobs = yaml.safe_load(DRY_RUN.read_text(encoding="utf-8"))["jobs"]
    steps = [s for s in jobs["staged-publication"]["steps"] if s.get("name") == STEP_NAME]
    assert len(steps) == 1, f"release-dry-run.yml has no single step named {STEP_NAME!r}"
    return steps[0]


def _stage(root: Path, tarballs: list[str]) -> None:
    """A checkout-shaped scratch tree: install.sh, scripts/ci, and dist/release."""
    shutil.copy2(REPO_ROOT / "install.sh", root / "install.sh")
    shutil.copytree(REPO_ROOT / "scripts" / "ci", root / "scripts" / "ci")
    release = root / "dist" / "release"
    release.mkdir(parents=True)
    for name in tarballs:
        (release / name).write_bytes(b"staged")


def _run_step(root: Path) -> subprocess.CompletedProcess[str]:
    step = _discovery_step()
    env = {**os.environ, **{k: str(v) for k, v in (step.get("env") or {}).items()}}
    env["VERSION"] = VERSION
    return subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_the_step_finds_both_tarballs_install_sh_downloads(tmp_path: Path) -> None:
    _stage(
        tmp_path,
        [f"circuit-breaker_{VERSION}_linux_{arch}.tar.gz" for arch in ("amd64", "arm64")],
    )
    result = _run_step(tmp_path)
    assert result.returncode == 0, (
        "the dry run's discovery step rejects a dist/release holding exactly the "
        f"tarballs install.sh downloads:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "$2" not in result.stdout


def test_the_step_fails_when_an_arch_is_missing(tmp_path: Path) -> None:
    """The step is a gate: a missing arm64 tarball is named, not waved through."""
    _stage(tmp_path, [f"circuit-breaker_{VERSION}_linux_amd64.tar.gz"])
    result = _run_step(tmp_path)
    assert result.returncode != 0
    assert f"circuit-breaker_{VERSION}_linux_arm64.tar.gz" in result.stdout + result.stderr
