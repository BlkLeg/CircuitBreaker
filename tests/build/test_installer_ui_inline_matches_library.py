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

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"

# scripts/ is not a package, so load the sync script by path; it is the single
# source of truth for which libraries are inlined and between which markers.
_spec = importlib.util.spec_from_file_location(
    "sync_installer_ui", REPO_ROOT / "scripts" / "ci" / "sync_installer_ui.py"
)
assert _spec is not None and _spec.loader is not None
_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sync)
BLOCKS: list[tuple[Path, str, str]] = _sync.BLOCKS

_SYNC_COMMAND = ".venv/bin/python scripts/ci/sync_installer_ui.py"


def _block_re(begin: str, end: str) -> re.Pattern[str]:
    return re.compile(
        re.escape(begin) + r"\n(.*)^" + re.escape(end), re.DOTALL | re.MULTILINE
    )


_PARAMS = pytest.mark.parametrize(
    ("library", "begin", "end"), BLOCKS, ids=[lib.name for lib, _, _ in BLOCKS]
)


@_PARAMS
def test_the_inlining_markers_exist(library: Path, begin: str, end: str) -> None:
    """Guards the guard: if someone deletes the markers, the identity test
    below must not pass vacuously by finding nothing to compare."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert begin in text, (
        f"install.sh is missing the marker {begin!r} — the inlined "
        f"renderer block can no longer be located, so run '{_SYNC_COMMAND}' "
        "and restore the marker comments around it."
    )
    assert end in text, (
        f"install.sh is missing the marker {end!r} — the inlined "
        f"renderer block can no longer be located, so run '{_SYNC_COMMAND}' "
        "and restore the marker comments around it."
    )
    assert _block_re(begin, end).search(text), (
        "install.sh has both marker strings but not in the expected "
        f"'{begin} ... {end}' order/shape — the block between "
        f"them cannot be extracted. Run '{_SYNC_COMMAND}' to regenerate it."
    )


@_PARAMS
def test_the_inlined_block_matches_the_library_byte_for_byte(
    library: Path, begin: str, end: str
) -> None:
    installer_text = INSTALL_SH.read_text(encoding="utf-8")
    match = _block_re(begin, end).search(installer_text)
    assert match, (
        f"could not find the inlined {library.name} block in {INSTALL_SH} "
        f"— run '{_SYNC_COMMAND}' to regenerate it."
    )
    inlined = match.group(1)
    library_text = library.read_text(encoding="utf-8")
    assert inlined == library_text, (
        f"install.sh's inlined copy of {library.name} has drifted from the "
        f"library. Run '{_SYNC_COMMAND}' to resync it, then commit the "
        "result."
    )
