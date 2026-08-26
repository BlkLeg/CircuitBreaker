"""The installer must actually verify the bundle it is about to run as root.

install.sh fetched ``${tarball_url}.sha256`` and verified against that. No
release has ever published such an asset: release.yml builds one
``SHA256SUMS`` for the whole release (``find . -maxdepth 1 -type f !
-name SHA256SUMS -exec sha256sum {} + > SHA256SUMS``) and uploads it with the
rest of ``dist/release/``. So the fetch 404'd on every install.

The skip was silent, which is what made a drifted asset name fatal rather than
merely noisy: the verification lived in an ``elif curl ...`` with no ``else``,
so a failed download of the checksum file meant the whole check was skipped and
nothing was printed. Every ``curl | bash`` install unpacked and ran an
unverified tarball as root while reporting success.

Two things are pinned here. The first is the asset name, checked against
release.yml rather than hard-coded, because name drift between the workflow and
the installer is the drift that killed this check. The second is that
verification fails closed: no SHA256SUMS asset, an unreachable one, one that
does not list our tarball, or a hash that does not match must each stop the
install. Only --skip-checksum may waive it, and it says so out loud.

install.sh runs ``main`` at import time, so cb_verify_bundle_checksum is
extracted and eval'd in a clean bash subshell rather than sourced -- the same
approach test_install_release_selection.py uses for cb_pick_release.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None, reason="the checksum asset is resolved with a jq filter"
)


def _extract(name: str) -> str:
    """Pull one top-level function body out of install.sh by name."""
    body = re.search(
        rf"^{name}\(\) \{{\n.*?^\}}$", INSTALL_SH.read_text(), re.MULTILINE | re.DOTALL
    )
    assert body is not None, f"{name}() not found in install.sh"
    return body.group(0)


def _checksum_asset_name() -> str:
    """The asset name install.sh selects out of the release JSON."""
    source = _extract("cb_verify_bundle_checksum")
    names = re.findall(r'select\(\.name=="([^"]+)"\)', source)
    assert names, f"cb_verify_bundle_checksum selects no asset by name:\n{source}"
    assert len(set(names)) == 1, f"expected one checksum asset name, got {names}"
    return names[0]


# --------------------------------------------------------------------------
# The asset name must be one release.yml actually publishes.
# --------------------------------------------------------------------------


def test_the_checksum_asset_is_one_the_release_workflow_generates():
    """Name drift between workflow and installer is what made the check dead."""
    name = _checksum_asset_name()
    workflow = RELEASE_YML.read_text()
    assert f"> {name}" in workflow, (
        f"install.sh verifies against an asset named {name!r}, but "
        f".github/workflows/release.yml never generates a file by that name"
    )


def test_the_checksum_asset_is_uploaded_with_the_release():
    """Generated is not enough; `gh release create` has to attach it."""
    workflow = RELEASE_YML.read_text()
    # release.yml generates SHA256SUMS into dist/release/ and attaches the
    # whole directory, so the glob is what makes the asset downloadable.
    assert "dist/release/*" in workflow, (
        "release.yml no longer uploads dist/release/* -- confirm the checksum "
        "asset still reaches the release before trusting this test"
    )


def test_no_per_asset_sha256_url_is_constructed_any_more():
    """`${tarball_url}.sha256` is the dead URL; nothing may rebuild it."""
    code = [
        line
        for line in INSTALL_SH.read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]
    offenders = [line for line in code if ".sha256" in line]
    assert offenders == [], f"install.sh still fetches a per-asset .sha256: {offenders}"


# --------------------------------------------------------------------------
# Behaviour: cb_verify_bundle_checksum run for real in a bash sandbox.
# --------------------------------------------------------------------------

# curl is replaced by a shell function that copies a canned SHA256SUMS to
# whatever -o names, or fails like a 404 when STUB_SUMS is unset. cb_fail is
# the real contract -- it exits 1 -- so "install stopped" is observable as a
# non-zero return code rather than as a matched string.
HARNESS = """
set -euo pipefail
RED='' GREEN='' YELLOW='' CYAN='' BOLD='' DIM='' RESET=''
cb_step() { echo "STEP: $1"; }
cb_ok()   { echo "OK: $1"; }
cb_warn() { echo "WARN: $1"; }
cb_fail() { echo "FAIL: $1"; echo "HINT: ${2:-}"; exit 1; }
curl() {
  local dest=""
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "-o" ]]; then dest="$2"; shift 2; else shift; fi
  done
  [[ -n "${STUB_SUMS:-}" ]] || return 22
  cp "$STUB_SUMS" "$dest"
}
"""


def _run(release_json: dict, tarball_name: str, *, sums: Path | None, skip: bool = False):
    script = "\n".join(
        [
            HARNESS,
            f"SKIP_CHECKSUM={'true' if skip else 'false'}",
            "CB_VERSION=1.2.3",
            _extract("cb_verify_bundle_checksum"),
            f"cb_verify_bundle_checksum {json.dumps(json.dumps(release_json))} "
            f"{json.dumps(tarball_name)}",
        ]
    )
    env = dict(os.environ)
    if sums is not None:
        env["STUB_SUMS"] = str(sums)
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env
    )


@pytest.fixture()
def bundle(tmp_path):
    """A tarball at /tmp/<unique name>, where stage0_download_bundle puts it.

    The path is not a knob the installer exposes, so the fixture writes into
    the real /tmp and cleans up; the name is randomised so concurrent runs
    cannot collide.
    """
    name = f"circuit-breaker_1.2.3_linux_amd64.{uuid.uuid4().hex}.tar.gz"
    path = Path("/tmp") / name
    path.write_bytes(b"not really a tarball, but it hashes")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        yield name, digest, tmp_path
    finally:
        path.unlink(missing_ok=True)


def release_with_sums(url: str = "https://example.invalid/SHA256SUMS") -> dict:
    return {
        "tag_name": "v1.2.3",
        "assets": [
            {"name": "circuit-breaker_1.2.3_linux_amd64.tar.gz", "browser_download_url": "x"},
            {"name": "SHA256SUMS", "browser_download_url": url},
        ],
    }


def test_a_matching_checksum_verifies(bundle):
    name, digest, tmp_path = bundle
    sums = tmp_path / "SHA256SUMS"
    # release.yml runs `find . -maxdepth 1` from dist/release/, so every entry
    # is written in ./<name> form. The installer must read that form.
    sums.write_text(f"{digest}  ./{name}\n{'0' * 64}  ./install.sh\n")
    result = _run(release_with_sums(), name, sums=sums)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: SHA256 checksum verified" in result.stdout


def test_a_tampered_bundle_stops_the_install(bundle):
    name, _digest, tmp_path = bundle
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{'a' * 64}  ./{name}\n")
    result = _run(release_with_sums(), name, sums=sums)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "SHA256 mismatch" in result.stdout


def test_a_sha256sums_that_omits_our_tarball_stops_the_install(bundle):
    """The `--ignore-missing` trap, pinned.

    `sha256sum --ignore-missing -c` exits 0 when *none* of the listed files are
    present, so verifying the whole file wholesale would report success for a
    SHA256SUMS that never mentions the bundle at all -- an attacker-supplied
    tarball plus an authentic checksum file for some other release passes.
    """
    name, _digest, tmp_path = bundle
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{'b' * 64}  ./some-other-release.tar.gz\n")
    result = _run(release_with_sums(), name, sums=sums)
    assert result.returncode == 1, result.stdout + result.stderr


def test_an_asc_signature_line_does_not_stand_in_for_the_tarball(bundle):
    """`./x.tar.gz.asc` contains `./x.tar.gz`; a substring match would pass."""
    name, _digest, tmp_path = bundle
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{'c' * 64}  ./{name}.asc\n")
    result = _run(release_with_sums(), name, sums=sums)
    assert result.returncode == 1, result.stdout + result.stderr


def test_a_release_without_a_sha256sums_asset_stops_the_install(bundle):
    """The original bug: nothing to verify against must not mean "carry on"."""
    name, _digest, tmp_path = bundle
    release = {"tag_name": "v1.2.3", "assets": [{"name": "install.sh", "browser_download_url": "x"}]}
    result = _run(release, name, sums=tmp_path / "unused")
    assert result.returncode == 1, result.stdout + result.stderr


def test_an_unreachable_sha256sums_stops_the_install(bundle):
    """A 404 or a dropped connection is the exact case that used to be silent."""
    name, _digest, _tmp_path = bundle
    result = _run(release_with_sums(), name, sums=None)
    assert result.returncode == 1, result.stdout + result.stderr


def test_skip_checksum_waives_verification_and_says_so(bundle):
    name, _digest, _tmp_path = bundle
    result = _run(release_with_sums(), name, sums=None, skip=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WARN: Skipping SHA256 verification (--skip-checksum)" in result.stdout


def test_the_download_stage_calls_the_verifier(bundle):
    """A verifier nothing invokes verifies nothing."""
    assert "cb_verify_bundle_checksum " in _extract("stage0_download_bundle")
