"""install.sh's inlined renderer must stay byte-identical to deploy/lib/ui.sh.

install.sh is served raw from `main` — pages.yml does a bare `cp` and the
documented install command is `curl -fsSL .../main/install.sh | sudo bash` —
so it cannot `source deploy/lib/ui.sh` at runtime; a host running that command
never cloned the repo and has no `deploy/` directory to source from. It
carries an inlined copy between two marker comments instead, and
`deploy/setup.sh`/`uninstall.sh` use the real library from the installed
bundle. That is a dependency pinned in two places — CLAUDE.md's rule for that
shape is explicit, and `test_playwright_image_matches_package.py` is the
precedent: the guard goes in, not only the fix.

`scripts/ci/sync_installer_ui.py` is the write side of this pair. This is the
read side: it extracts the block between the markers in install.sh and
asserts it equals deploy/lib/ui.sh exactly, byte for byte.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"
UI_SH = REPO_ROOT / "deploy" / "lib" / "ui.sh"

BEGIN_MARKER = (
    "# --- BEGIN INLINED deploy/lib/ui.sh "
    "— regenerate with scripts/ci/sync_installer_ui.py ---"
)
END_MARKER = "# --- END INLINED deploy/lib/ui.sh ---"

_BLOCK_RE = re.compile(
    re.escape(BEGIN_MARKER) + r"\n(.*)^" + re.escape(END_MARKER),
    re.DOTALL | re.MULTILINE,
)

_SYNC_COMMAND = ".venv/bin/python scripts/ci/sync_installer_ui.py"


def test_the_inlining_markers_exist() -> None:
    """Guards the guard: if someone deletes the markers, the identity test
    below must not pass vacuously by finding nothing to compare."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert BEGIN_MARKER in text, (
        f"install.sh is missing the marker {BEGIN_MARKER!r} — the inlined "
        f"renderer block can no longer be located, so run '{_SYNC_COMMAND}' "
        "and restore the marker comments around it."
    )
    assert END_MARKER in text, (
        f"install.sh is missing the marker {END_MARKER!r} — the inlined "
        f"renderer block can no longer be located, so run '{_SYNC_COMMAND}' "
        "and restore the marker comments around it."
    )
    assert _BLOCK_RE.search(text), (
        "install.sh has both marker strings but not in the expected "
        f"'{BEGIN_MARKER} ... {END_MARKER}' order/shape — the block between "
        f"them cannot be extracted. Run '{_SYNC_COMMAND}' to regenerate it."
    )


def test_the_inlined_block_matches_the_library_byte_for_byte() -> None:
    installer_text = INSTALL_SH.read_text(encoding="utf-8")
    match = _BLOCK_RE.search(installer_text)
    assert match, (
        f"could not find the inlined deploy/lib/ui.sh block in {INSTALL_SH} "
        f"— run '{_SYNC_COMMAND}' to regenerate it."
    )
    inlined = match.group(1)
    library = UI_SH.read_text(encoding="utf-8")
    assert inlined == library, (
        "install.sh's inlined copy of deploy/lib/ui.sh has drifted from the "
        f"library. Run '{_SYNC_COMMAND}' to resync it, then commit the "
        "result."
    )
