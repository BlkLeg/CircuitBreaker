"""A Tier 3 row must be able to say which artifact it is talking about.

ADR 0005 Phase 3, F8. The Makefile already refuses to test "whatever .rpm
happened to be lying in dist/" by requiring an explicit CB_CANDIDATE. But an
explicitly named *locally built* package is still not the artifact a user
installs, and the two are not interchangeable: a PyInstaller bundle inherits the
glibc floor of its build host. A package built on Fedora 44 (glibc 2.43) demands
GLIBC_2.38 and cannot run on Debian 12 at all, while the release job builds on
ubuntu-22.04 (2.35), which every supported distro clears.

That was not a hypothetical -- it is how the debian-deb-amd64 row failed, with
`Failed to load Python shared library libpython3.14.so.1.0: version GLIBC_2.38
not found`, against a package whose released equivalent works fine.

So a green row against a local build evidences *a* package, not *the* package.
The fix is not to ban local builds -- they are how anyone develops -- but to make
the difference legible in the artifact itself and refuse to bank evidence on the
wrong one. build-info.json travels inside the package, so the claim is read from
the thing under test rather than from the directory it was found in.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_native_release.py"
NFPM = REPO_ROOT / "nfpm.yaml"
TIER3 = REPO_ROOT / "scripts" / "ci" / "tier3-artifact.sh"
BUNDLE_INFO = REPO_ROOT / "dist" / "native" / "bundle" / "share" / "build-info.json"


def test_the_build_records_its_provenance():
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "build-info.json" in text, (
        "build_native_release.py must emit a build-info.json into the bundle; "
        "without it nothing downstream can tell a CI artifact from a local one"
    )
    for field in ("built_by", "glibc", "python"):
        assert re.search(rf'"{field}"', text), f"build-info.json omits {field!r}"


def test_the_package_ships_the_provenance():
    """Read from the artifact, not from the directory it was found in."""
    text = NFPM.read_text(encoding="utf-8")
    assert "build-info.json" in text, (
        "nfpm.yaml does not ship share/build-info.json, so the tier cannot read "
        "the candidate's provenance on the guest"
    )


def test_the_tier_records_and_gates_on_provenance():
    text = TIER3.read_text(encoding="utf-8")
    assert "build-info.json" in text, "the tier does not read the candidate's provenance"
    assert "CB_ALLOW_LOCAL_CANDIDATE" in text, (
        "the tier has no explicit escape hatch for a local candidate, so either "
        "it banks evidence on unreleasable artifacts or developers cannot run it"
    )


def test_the_emitted_provenance_is_well_formed():
    """Checks the real file when a build has run, rather than only the source."""
    if not BUNDLE_INFO.is_file():
        import pytest

        pytest.skip("no built bundle in dist/native — run `make build` first")
    info = json.loads(BUNDLE_INFO.read_text(encoding="utf-8"))
    assert info.get("built_by") in {"ci", "local"}, info
    assert re.match(r"^\d+\.\d+", str(info.get("glibc", ""))), (
        f"glibc floor is not a version: {info.get('glibc')!r}"
    )
    assert info.get("version"), info


def test_the_local_candidate_flag_reaches_the_guest():
    """ssh carries no environment and sudo resets it, so a flag set on the host
    would look effective and change nothing in the VM -- the row would refuse a
    local candidate whatever the operator set. A silently ignored flag is worse
    than no flag."""
    dispatch = (REPO_ROOT / "scripts" / "ci" / "fleet" / "dispatch.sh").read_text(encoding="utf-8")
    assert "CB_ALLOW_LOCAL_CANDIDATE" in dispatch, (
        "dispatch.sh never forwards CB_ALLOW_LOCAL_CANDIDATE into the guest"
    )
    call = re.search(r"^.*tier3-artifact\.sh /opt/cb-tier3.*$", dispatch, re.M)
    assert call and "GUEST_ENV" in call.group(0), (
        f"the flag is read but not passed on the invocation line:\n  {call.group(0) if call else '(no call found)'}"
    )
