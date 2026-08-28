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
