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


def test_post_ga_a_newer_candidate_still_wins_KNOWN_LIMITATION():
    """Pins today's behaviour and names the gap; it is not an endorsement.

    `cb_pick_release` takes the newest non-draft release, candidates included.
    That is right for the pre-GA window, and the caller warns loudly when the
    winner is a candidate. It is permanent, though, not pre-GA only: once
    v1.0.0 is stable, publishing v1.0.1-rc.1 makes that candidate the newest
    release and a default `curl | bash` fetches it.

    "Prefer the newest stable, fall back to a candidate only when no stable
    exists" is NOT the fix -- v0.3.4 is a published stable release, so that rule
    selects a pre-1.0 build from July for every install today: strictly worse,
    and the exact "user silently gets an ancient build" failure that started
    this work. See test_never_falls_back_to_the_newest_stable_during_a_candidate_window.

    The real fix is the signed update manifest, which publishes ordered
    per-channel release lists and turns "the newest stable" into a list lookup
    rather than a semver comparator written in bash. Deliberately not
    hand-rolled here.
    """
    releases = [
        release("v1.0.1-rc.1", prerelease=True),
        release("v1.0.0"),
        release("v1.0.0-rc.4", prerelease=True),
        release("v0.3.4"),
    ]
    assert pick(releases)["tag_name"] == "v1.0.1-rc.1"


def test_the_candidate_warning_does_not_claim_no_stable_release_exists():
    """The warning fires whenever the winner is a candidate, which after GA
    happens with a stable release published. It must not say otherwise."""
    source = INSTALL_SH.read_text()
    assert "No stable release yet" not in source
    assert "Installing release candidate" in source


def _strip_v(tag: str) -> str:
    """Run install.sh's own tag -> CB_VERSION conversion, as shipped."""
    line = next(
        ln.strip()
        for ln in INSTALL_SH.read_text().splitlines()
        if ln.strip().startswith('CB_VERSION="${CB_VERSION')
    )
    result = subprocess.run(
        ["bash", "-c", f'set -euo pipefail\nCB_VERSION={json.dumps(tag)}\n{line}\nprintf %s "$CB_VERSION"'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("v1.0.0", "1.0.0"),
        ("v1.0.0-rc.4", "1.0.0-rc.4"),
        ("1.0.0", "1.0.0"),
        # PREEXISTING-3: `tr -d v` deleted every v in the tag, not the leading
        # one, so any tag with a v elsewhere came out mangled.
        ("v1.0.0-preview.1", "1.0.0-preview.1"),
        ("v2.0.0-dev.1", "2.0.0-dev.1"),
    ],
)
def test_only_the_leading_v_is_stripped_from_the_tag(tag, expected):
    assert _strip_v(tag) == expected
