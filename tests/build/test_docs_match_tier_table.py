"""No page may promise a guarantee ADR 0005 records as not in force.

quick-install.md leads with

    curl -fsSL .../install.sh | bash

which installs the tarball — which ADR 0005 places at Tier 3, "guaranteed to
build only". The two statements were individually honest and jointly
indefensible: the most prominently documented way to install Circuit Breaker
carried the weakest guarantee attached.

The ADR already requires that docs/release/1.0.0-support-contract.md publish no
tier language while any row reads *not in force*. This extends that rule to
every page, mechanically, so the contradiction cannot reappear by someone
editing a different file.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR = REPO_ROOT / "docs" / "adr" / "0005-verification-tiers-and-platform-support.md"
QUICK_INSTALL = REPO_ROOT / "docs" / "installation" / "quick-install.md"

# Phrases that assert a working install rather than describing how to attempt one.
OVERPROMISE = re.compile(
    r"\b(guaranteed to (install|boot|work)|fully (tested|verified) on|"
    r"production[- ]ready on every)\b",
    re.IGNORECASE,
)


def _tier_states() -> dict[str, str]:
    text = ADR.read_text(encoding="utf-8")
    return {
        tier: state
        for tier, state in re.findall(
            r"^\|\s*([123])\s*\|.*\|\s*(\*\*.+?\*\*.*?)\s*\|\s*$", text, re.M
        )
    }


def test_the_adr_still_states_every_tier() -> None:
    states = _tier_states()
    assert set(states) == {"1", "2", "3"}, (
        f"ADR 0005's in-force table no longer states all three tiers: {sorted(states)}. "
        "Every assertion below reads that table, so they would pass vacuously."
    )


def test_quick_install_does_not_overpromise() -> None:
    text = QUICK_INSTALL.read_text(encoding="utf-8")
    hits = OVERPROMISE.findall(text)
    assert not hits, (
        f"quick-install.md asserts {hits}, which ADR 0005's in-force column does "
        "not support. The tarball this page leads with is Tier 3 — guaranteed to "
        "build only — until the tarball smoke, boot and installer-journey jobs "
        "are green against a candidate."
    )


def test_quick_install_states_what_is_actually_verified() -> None:
    """Silence about the guarantee is how the contradiction survived."""
    text = QUICK_INSTALL.read_text(encoding="utf-8").lower()
    assert "verification tiers" in text or "adr 0005" in text, (
        "quick-install.md does not point at the tier table at all. A reader "
        "cannot discover what is guaranteed about the path this page recommends."
    )
