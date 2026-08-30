"""Version parity is a claim about the candidate, not about the fixture.

The upgrade row installs a real released package as N-1, boots it, upgrades to
the candidate and rolls back. Its first execution stopped here:

    shipped=0.3.4 reported=unknown
    ::error::binary reports 'unknown' but the shipped VERSION says '0.3.4'

The published v0.3.4 binary answers `--version` with `unknown`. That was a real
defect and it is already fixed -- 0.4.0 reports its version correctly. But the
row failed on it, and that is the wrong outcome for three reasons:

1. It is not the claim the row makes. The row proves that upgrading from N-1
   preserves data and that the documented rollback works. The old release's
   self-reporting is a property of the old release.
2. Nothing in the upgrade contract depends on it. `VERSION_AT_START` is read
   from the shipped VERSION file, not from `--version`, and every later
   assertion compares against that.
3. It makes the tier unable to do its job. A hard gate on the fixture means
   upgrades can only be tested from a historically perfect release -- and
   upgrading from an imperfect one is exactly the case that needs proving.

So the parity check stays fatal where the claim is the candidate's
(`candidate`, `upgraded`) and is recorded rather than fatal where the subject is
the old release (`previous`, `rolledback`). The mismatch is still written to
the evidence directory either way; what changes is whether it stops the row.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TIER3 = REPO_ROOT / "scripts/ci/tier3-artifact.sh"

CANDIDATE_SUBJECTS = ("candidate", "upgraded")
OLD_RELEASE_SUBJECTS = ("previous", "rolledback")


def _calls() -> list[tuple[str, str]]:
    """(label-expression, severity) for every parity call site."""
    out = []
    for line in TIER3.read_text("utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("t3::assert_version_matches"):
            parts = stripped.split()[1:]
            label = parts[0].strip('"')
            severity = parts[1].strip('"') if len(parts) > 1 else "fatal"
            out.append((label, severity))
    return out


def test_the_parity_check_takes_a_severity():
    body = TIER3.read_text("utf-8")
    assert re.search(r"t3::assert_version_matches\(\)\s*\{[^}]*severity", body, re.S), (
        "assert_version_matches must accept a severity so the fixture and the "
        "candidate can be held to different standards"
    )


def test_every_parity_call_site_declares_its_subject():
    calls = _calls()
    assert calls, "tier3-artifact.sh makes no version parity assertions"
    for label, severity in calls:
        assert severity in {"fatal", "tolerate", "$START_SEVERITY"}, (
            f"parity call for {label!r} has an unrecognised severity {severity!r}"
        )


def test_the_old_release_does_not_fail_the_row():
    """A defect in the N-1 fixture is evidence, not a reason to stop."""
    for label, severity in _calls():
        if label in OLD_RELEASE_SUBJECTS:
            assert severity != "fatal", (
                f"the parity check for {label!r} is fatal, so the row cannot run "
                f"from any released package whose --version was ever wrong -- "
                f"which is what stopped its first execution"
            )


def test_the_candidate_is_still_held_to_it():
    """The waiver must not leak onto the artifact actually under test."""
    seen = set()
    for label, severity in _calls():
        if label in CANDIDATE_SUBJECTS:
            seen.add(label)
            assert severity == "fatal", (
                f"the parity check for {label!r} must stay fatal -- it is the "
                f"candidate's own claim about itself"
            )
    assert "upgraded" in seen, "no parity assertion covers the upgraded candidate"
