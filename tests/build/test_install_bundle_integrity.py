"""The installer must actually verify the bundle it is about to run as root.

install.sh fetched ``${tarball_url}.sha256`` and verified against that. No
release has ever published such an asset: release.yml builds one
``SHA256SUMS`` for the whole release (``find . -maxdepth 1 -type f !
-name SHA256SUMS -exec sha256sum {} + > SHA256SUMS``) and uploads it with the
rest of ``dist/release/``. So the fetch 404'd on every install.

The skip was silent: the verification lived in an ``elif curl ...`` with no
``else``, so a failed download of the checksum file skipped the whole check.

Pinned here: the asset name install.sh fetches, checked against release.yml
rather than hard-coded, because name drift between the workflow and the
installer is the drift that killed this check. The fail-closed behaviour itself
lives in test_install_bundle_verification.py.

install.sh runs ``main`` at import time, so the functions under test are
extracted and eval'd in a clean bash subshell rather than sourced -- the same
approach test_install_release_selection.py uses for cb_pick_release.
"""

from __future__ import annotations

import re
import shutil
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
    source = _extract("stage0_download_bundle")
    names = re.findall(r'cb_fetch_release_asset "\$release_json" (SHA256SUMS)\b(?!\.)', source)
    assert names, f"stage0_download_bundle fetches no SHA256SUMS asset:\n{source}"
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
# Behaviour (fails closed, the --ignore-missing trap, the .asc line, the
# --skip-checksum warning) moved to test_install_bundle_verification.py, which
# runs cb_check_bundle row by row. Here: the wiring only.
# --------------------------------------------------------------------------


def test_the_download_stage_calls_the_verifier():
    """A verifier nothing invokes verifies nothing."""
    stage = _extract("stage0_download_bundle")
    assert stage.count("cb_check_bundle ") == 2, "both the local and the download branch must verify"
