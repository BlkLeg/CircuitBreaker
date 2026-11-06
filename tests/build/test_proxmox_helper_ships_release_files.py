"""cb-proxmox-deploy.sh must hand install.sh what it needs to verify the bundle.

install.sh --local-bundle verifies the tarball against SHA256SUMS and
SHA256SUMS.sig found next to it, and finds the tarball's line in SHA256SUMS by
its release file name. The helper used to push only the tarball, renamed to
/tmp/cb-bundle.tar.gz, so every Proxmox install ran UNVERIFIED.

cb-proxmox-deploy.sh runs `main` at import time, so the functions under test
are extracted and eval'd in a clean bash with fake curl and pct on PATH. jq
is required, as it is by the helper itself.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "cb-proxmox-deploy.sh"
TARBALL = "circuit-breaker_0.4.7_linux_amd64.tar.gz"

def _function(name: str) -> str:
    body = re.search(rf"^{name}\(\) \{{\n.*?^\}}$", HELPER.read_text(), re.MULTILINE | re.DOTALL)
    assert body, f"{name}() not found in cb-proxmox-deploy.sh"
    return body.group(0)


def _constant(name: str) -> str:
    line = re.search(rf'^{name}="[^"]*"$', HELPER.read_text(), re.MULTILINE)
    assert line, f"{name} not found in cb-proxmox-deploy.sh"
    return line.group(0)


def _run(tmp: Path, asset_names: tuple[str, ...]) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    assets = tmp / "assets"
    assets.mkdir()
    for name in asset_names:
        (assets / name).write_text(f"contents of {name}\n")
    release = {"tag_name": "v0.4.7", "assets": [
        {"name": n, "browser_download_url": f"https://dl.invalid/{n}"} for n in asset_names]}
    container = tmp / "container"
    container.mkdir()
    bindir = tmp / "bin"
    bindir.mkdir()
    curl = bindir / "curl"
    curl.write_text(f"""#!/bin/sh
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift 2 ;; http*) url="$1"; shift ;; *) shift ;; esac
done
cp "{assets}/$(basename "$url")" "$out"
""")
    # Fake pct: `exec <ct> -- mkdir -p <d>` and `push <ct> <src> <dst>` act on
    # a directory standing in for the container's filesystem.
    pct = bindir / "pct"
    pct.write_text(f"""#!/bin/sh
case "$1" in
  exec) shift 3; [ "$1" = mkdir ] && mkdir -p "{container}$3" ;;
  push) cp "$3" "{container}$4" ;;
esac
""")
    for f in (curl, pct):
        f.chmod(0o755)
    host = tmp / "host"
    host.mkdir()
    script = "\n".join([
        "set -euo pipefail",
        'msg_err() { echo "ERR: $1"; }',
        _constant("CB_CT_RELEASE_DIR"),
        _function("download_release_files"),
        _function("push_release_files"),
        _function("build_installer_cmd"),
        'CB_NO_TLS=false CB_FQDN="" CB_PORT=8088 CB_DOCKER=false',
        f"download_release_files '{host}' '{json.dumps(release)}' '{TARBALL}'",
        f"push_release_files 101 '{host}'",
        f"build_installer_cmd '{TARBALL}'",
    ])
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=False)
    return r, container, host


def test_the_tarball_sums_and_signature_are_pushed_side_by_side_under_release_names(tmp_path: Path) -> None:
    r, container, _ = _run(tmp_path, (TARBALL, "SHA256SUMS", "SHA256SUMS.sig"))
    assert r.returncode == 0, r.stdout + r.stderr
    release_dir = container / "tmp" / "cb-release"
    assert sorted(p.name for p in release_dir.iterdir()) == sorted([TARBALL, "SHA256SUMS", "SHA256SUMS.sig"])
    for name in (TARBALL, "SHA256SUMS", "SHA256SUMS.sig"):
        assert (release_dir / name).read_text() == f"contents of {name}\n"
    assert f"--local-bundle /tmp/cb-release/{TARBALL}" in r.stdout


def test_an_unsigned_release_pushes_only_what_it_has(tmp_path: Path) -> None:
    """Releases before 0.4.7 have no SHA256SUMS.sig; install.sh decides what that means."""
    r, container, _ = _run(tmp_path, (TARBALL, "SHA256SUMS"))
    assert r.returncode == 0, r.stdout + r.stderr
    release_dir = container / "tmp" / "cb-release"
    assert sorted(p.name for p in release_dir.iterdir()) == sorted([TARBALL, "SHA256SUMS"])


def test_a_release_without_sums_is_refused(tmp_path: Path) -> None:
    r, container, _ = _run(tmp_path, (TARBALL,))
    assert r.returncode != 0
    assert "ERR: SHA256SUMS not found" in r.stdout
    assert not (container / "tmp" / "cb-release").exists()


def test_the_install_flow_uses_the_release_files_and_no_renamed_tarball() -> None:
    text = HELPER.read_text()
    assert "/tmp/cb-bundle.tar.gz" not in text
    assert 'download_release_files "$host_release_dir" "$release_json" "$tarball_name"' in text
    assert 'push_release_files "$CTID" "$host_release_dir"' in text
    assert 'installer_cmd=$(build_installer_cmd "$tarball_name")' in text
