"""A default install must land on the newest release, not on a stale badge.

v1.0.0-rc.1 and v1.0.0-rc.2 were published before release.yml learned to pass
--prerelease (GOV-20), so both carry ``prerelease: false`` on GitHub and rc.2
still holds the "Latest release" badge. install.sh asked
``/releases/latest`` for its default, so ``curl | bash`` fetched the rc.2
bundle -- which reports its version as 1.0.0-rc.2, and which predates the
gh#104 PyInstaller fix, so every Proxmox connection died with
``No module named 'proxmoxer.backends'``.

The selection therefore may not trust that endpoint. cb_pick_release reads the
release list and picks the newest non-draft entry itself, so a mislabelled
older release cannot win.

install.sh runs ``main`` at import time, so the function is extracted and
eval'd in a clean bash subshell rather than sourced.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None, reason="cb_pick_release is a jq filter"
)


def _extract(name: str) -> str:
    """Pull one top-level function body out of install.sh by name."""
    body = re.search(
        rf"^{name}\(\) \{{\n.*?^\}}$", INSTALL_SH.read_text(), re.MULTILINE | re.DOTALL
    )
    assert body is not None, f"{name}() not found in install.sh"
    return body.group(0)


def pick(releases: list[dict]) -> dict | None:
    """Run the shipped cb_pick_release over a release list, newest first."""
    result = subprocess.run(
        ["bash", "-c", f'set -euo pipefail\n{_extract("cb_pick_release")}\ncb_pick_release'],
        input=json.dumps(releases),
        capture_output=True,
        text=True,
    )
    out = result.stdout.strip()
    return json.loads(out) if out else None


def release(tag: str, *, prerelease: bool = False, draft: bool = False) -> dict:
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "assets": []}


# The live list as the API returns it today: newest first, rc.2 mislabelled
# stable, and no release at all for the v1.0.0-rc.3 tag.
LIVE = [
    release("v1.0.0-rc.4", prerelease=True),
    release("v1.0.0-rc.2"),
    release("v1.0.0-rc.1"),
    release("v0.3.4"),
    release("v0.3.4", draft=True),
    release("v0.3.3"),
]


def test_picks_newest_even_though_an_older_release_is_flagged_stable():
    """The regression: rc.2 claims stable and holds the badge; rc.4 still wins.

    Asserted against the mislabelled list on purpose -- the fix must hold
    whether or not the GitHub release flags are ever repaired.
    """
    assert pick(LIVE)["tag_name"] == "v1.0.0-rc.4"


def test_never_falls_back_to_the_newest_stable_during_a_candidate_window():
    """Selecting `prerelease == false` here yields v0.3.4, a pre-1.0 build."""
    assert pick(LIVE)["tag_name"] != "v0.3.4"


def test_picks_the_stable_release_once_one_is_newest():
    releases = [release("v1.0.0"), *LIVE]
    assert pick(releases)["tag_name"] == "v1.0.0"


def test_skips_drafts():
    releases = [release("v9.9.9", draft=True), *LIVE]
    assert pick(releases)["tag_name"] == "v1.0.0-rc.4"


def test_draft_prerelease_is_also_skipped():
    releases = [release("v9.9.9", prerelease=True, draft=True), *LIVE]
    assert pick(releases)["tag_name"] == "v1.0.0-rc.4"


def test_no_installable_release_yields_nothing():
    assert pick([]) is None
    assert pick([release("v1.0.0", draft=True)]) is None


def test_api_error_object_yields_nothing_rather_than_garbage():
    """A rate-limit body is an object, not an array; the caller must see empty."""
    result = subprocess.run(
        ["bash", "-c", f'set -euo pipefail\n{_extract("cb_pick_release")}\ncb_pick_release'],
        input='{"message":"API rate limit exceeded"}',
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""


def test_default_path_does_not_consult_the_releases_latest_endpoint():
    """The badge endpoint is the root cause; no code may depend on it again.

    Comments are stripped first -- the block above cb_pick_release names the
    endpoint to explain why it is not used, and that prose must stay legal.
    """
    code = [
        line
        for line in INSTALL_SH.read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]
    offenders = [line for line in code if "/latest" in line]
    assert offenders == [], f"install.sh still reaches for the badge: {offenders}"
