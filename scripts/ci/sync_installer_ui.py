#!/usr/bin/env python3
"""Keep install.sh's inlined renderer byte-identical to deploy/lib/ui.sh.

install.sh is served raw from `main` — pages.yml does a bare `cp` and the
documented install command is `curl -fsSL .../main/install.sh | sudo bash` —
so it cannot `source deploy/lib/ui.sh` at runtime without breaking every
curl|bash install on a host that never cloned the repo. It carries an inlined
copy between two marker comments instead, and `deploy/setup.sh`/`uninstall.sh`
use the real library from the installed bundle. That is a pair pinned in two
places, and CLAUDE.md's rule for that shape is explicit: the guard belongs in
the tree, not only the fix.

This script is that guard's write side: it replaces everything between the
markers in install.sh with the current contents of deploy/lib/ui.sh.
`tests/build/test_installer_ui_inline_matches_library.py` is the read side,
run in CI; `--check` here is the same comparison for local use.

Usage:
    scripts/ci/sync_installer_ui.py            # rewrite install.sh in place
    scripts/ci/sync_installer_ui.py --check    # report drift, exit 1, no write
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"
UI_SH = REPO_ROOT / "deploy" / "lib" / "ui.sh"

BEGIN_MARKER = "# --- BEGIN INLINED deploy/lib/ui.sh — regenerate with scripts/ci/sync_installer_ui.py ---"
END_MARKER = "# --- END INLINED deploy/lib/ui.sh ---"

_BLOCK_RE = re.compile(
    re.escape(BEGIN_MARKER) + r"\n(.*)^" + re.escape(END_MARKER),
    re.DOTALL | re.MULTILINE,
)


class MarkersNotFoundError(RuntimeError):
    """Raised when install.sh does not contain both inlining markers."""


def read_library() -> str:
    """Return the current contents of deploy/lib/ui.sh, unmodified."""
    return UI_SH.read_text(encoding="utf-8")


def current_inlined_block(installer_text: str) -> str:
    """Return the text between the BEGIN/END markers in install.sh.

    Raises MarkersNotFoundError if either marker is missing, so a caller can
    never silently treat "no markers" as "empty block, already in sync".
    """
    match = _BLOCK_RE.search(installer_text)
    if not match:
        raise MarkersNotFoundError(
            f"could not find both '{BEGIN_MARKER}' and '{END_MARKER}' in {INSTALL_SH}"
        )
    return match.group(1)


def render_installer(installer_text: str, library_text: str) -> str:
    """Return install.sh's text with the inlined block replaced by library_text.

    Splices by index rather than `re.sub(..., replacement)`: re.sub treats
    backslashes in a replacement string as backreferences, and a shell
    library is full of them (`\\n`-in-strings, escaped characters in the
    banner art). Raises MarkersNotFoundError if the markers are missing.
    """
    match = _BLOCK_RE.search(installer_text)
    if not match:
        raise MarkersNotFoundError(
            f"could not find both '{BEGIN_MARKER}' and '{END_MARKER}' in {INSTALL_SH}"
        )
    start, end = match.span(1)
    return installer_text[:start] + library_text + installer_text[end:]


def check(installer_text: str, library_text: str) -> bool:
    """Return True when install.sh's inlined block matches the library exactly."""
    return current_inlined_block(installer_text) == library_text


def main(argv: list[str] | None = None) -> int:
    """Entry point: sync (default) or report drift (--check) and return an exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit 1 instead of writing install.sh",
    )
    args = parser.parse_args(argv)

    library_text = read_library()
    installer_text = INSTALL_SH.read_text(encoding="utf-8")

    try:
        if args.check:
            if check(installer_text, library_text):
                print(f"{INSTALL_SH.relative_to(REPO_ROOT)} is in sync with {UI_SH.relative_to(REPO_ROOT)}")
                return 0
            print(
                f"{INSTALL_SH.relative_to(REPO_ROOT)} has drifted from "
                f"{UI_SH.relative_to(REPO_ROOT)} — run "
                "'scripts/ci/sync_installer_ui.py' to fix.",
                file=sys.stderr,
            )
            return 1

        updated_text = render_installer(installer_text, library_text)
        if updated_text != installer_text:
            INSTALL_SH.write_text(updated_text, encoding="utf-8")
            print(f"updated {INSTALL_SH.relative_to(REPO_ROOT)}")
        else:
            print(f"{INSTALL_SH.relative_to(REPO_ROOT)} already in sync")
        return 0
    except MarkersNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
