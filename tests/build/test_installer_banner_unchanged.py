"""cb_logo is not to be touched.

The artwork was the one part of the installer explicitly excluded from this
redesign. It is pinned by content hash rather than by eye, because "I did not
mean to change it" is not a property a reviewer can check on a 20-line block of
backslashes.

To change the banner deliberately: update EXPECTED_SHA256 in the same commit,
and say in the message why.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "install.sh"

EXPECTED_SHA256 = "dc85b6b9501fbad91dac6a3988857365b772530967af2456e6dfc4857a5db36d"


def _logo_source() -> str:
    text = INSTALLER.read_text(encoding="utf-8")
    match = re.search(r"^cb_logo\(\) \{\n(.*?)^\}$", text, re.DOTALL | re.MULTILINE)
    assert match, "cb_logo() not found in install.sh"
    return match.group(1)


def test_the_banner_is_unchanged() -> None:
    digest = hashlib.sha256(_logo_source().encode("utf-8")).hexdigest()
    assert digest == EXPECTED_SHA256, (
        f"cb_logo() changed (sha256 {digest}).\n"
        "The ASCII art is explicitly out of scope for the installer redesign. "
        "If this change is deliberate, update EXPECTED_SHA256 in this file in "
        "the same commit and say why in the message."
    )
