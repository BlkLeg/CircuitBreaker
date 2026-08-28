# tests/build/test_fleet_make_target.py
"""verify-fleet must not silently test a stale artifact.

The tier's whole claim is "this candidate installs and boots". A target that
falls back to whatever .rpm happens to be in dist/ makes that claim about a file
whose provenance nobody checked -- which is the same defect class as the security
gate reporting a missing scanner as a clean scan (#106): a result that reads like
a pass and was never an observation.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


def _recipe(target: str) -> str:
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n|\n)*)", text, re.M)
    assert match, f"no {target} target in the Makefile"
    return match.group(1)


def test_verify_fleet_target_exists():
    _recipe("verify-fleet")


def test_verify_fleet_calls_dispatch_not_an_inlined_body():
    """P1: the gate body lives in scripts/ci, and make is a thin caller."""
    recipe = _recipe("verify-fleet")
    assert "fleet/dispatch.sh" in recipe
    assert "qemu-system" not in recipe, "the gate body belongs in dispatch.sh, not the Makefile"


def test_verify_fleet_requires_an_explicit_candidate():
    recipe = _recipe("verify-fleet")
    assert "CB_CANDIDATE" in recipe, (
        "verify-fleet must take the candidate package explicitly (CB_CANDIDATE=...) "
        "rather than globbing dist/ and testing whatever it finds"
    )


def test_verify_fleet_is_documented_in_help():
    text = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^verify-fleet:.*##", text, re.M), (
        "the target needs a ## description or it will not appear in `make help`"
    )


# ── Phase 3: the upgrade row's entry point ─────────────────────────────────


def test_verify_fleet_upgrade_target_exists():
    _recipe("verify-fleet-upgrade")


def test_verify_fleet_upgrade_requires_both_artifacts():
    """An upgrade needs something to upgrade FROM, and defaulting it would be the
    same defect as defaulting CB_CANDIDATE: a claim about a file whose provenance
    nobody checked."""
    recipe = _recipe("verify-fleet-upgrade")
    assert "CB_CANDIDATE)" in recipe, "the candidate must be explicit"
    assert "CB_CANDIDATE_PREVIOUS" in recipe, "the previous version must be explicit"


def test_verify_fleet_upgrade_dispatches_the_upgrade_row():
    recipe = _recipe("verify-fleet-upgrade")
    assert "fedora-rpm-amd64-upgrade" in recipe, (
        "the target must dispatch the mode: upgrade row, not the install row"
    )
    assert "fleet/dispatch.sh" in recipe


def test_verify_fleet_upgrade_warns_that_the_versions_must_differ():
    """dnf exits zero on an upgrade to the same NEVRA, so a mistyped path here
    produces a passing run that upgraded nothing. The target says so where the
    operator will read it."""
    recipe = _recipe("verify-fleet-upgrade")
    assert "no-op" in recipe.lower() or "lower version" in recipe.lower()


def test_both_fleet_targets_are_phony():
    """Neither produces a file of its own name, and a stray file called
    `verify-fleet` in the repo root would silently disable the gate."""
    text = MAKEFILE.read_text(encoding="utf-8")
    phony = " ".join(re.findall(r"^\.PHONY:(.*)$", text, re.M))
    for target in ("verify-fleet", "verify-fleet-upgrade"):
        assert re.search(rf"\b{re.escape(target)}\b", phony), f"{target} is not .PHONY"
