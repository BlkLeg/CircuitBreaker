#!/usr/bin/env python3
"""Keep install.sh's inlined libraries byte-identical to deploy/lib/.

install.sh is served raw from `main` — pages.yml does a bare `cp` and the
documented install command is `curl -fsSL .../main/install.sh | sudo bash` —
so it cannot `source deploy/lib/ui.sh` at runtime without breaking every
curl|bash install on a host that never cloned the repo. It carries an inlined
copy between two marker comments instead, and `deploy/setup.sh`/`uninstall.sh`
use the real library from the installed bundle. That is a pair pinned in two
places, and CLAUDE.md's rule for that shape is explicit: the guard belongs in
the tree, not only the fix.

This script is that guard's write side: it replaces everything between the
markers in install.sh with the current contents of each library in BLOCKS
(deploy/lib/ui.sh and deploy/lib/bundle-signature.sh).
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

BLOCKS: list[tuple[Path, str, str]] = [
    (
        REPO_ROOT / "deploy" / "lib" / "ui.sh",
        "# --- BEGIN INLINED deploy/lib/ui.sh — regenerate with scripts/ci/sync_installer_ui.py ---",
        "# --- END INLINED deploy/lib/ui.sh ---",
    ),
    (
        REPO_ROOT / "deploy" / "lib" / "bundle-signature.sh",
        "# --- BEGIN INLINED deploy/lib/bundle-signature.sh — regenerate with scripts/ci/sync_installer_ui.py ---",
        "# --- END INLINED deploy/lib/bundle-signature.sh ---",
    ),
]

# Aliases for the first block, kept for anything that still uses the old names.
UI_SH, BEGIN_MARKER, END_MARKER = BLOCKS[0]


def block_regex(begin: str, end: str) -> re.Pattern[str]:
    """Return the regex that captures the text between one BEGIN/END marker pair."""
    return re.compile(
        re.escape(begin) + r"\n(.*)^" + re.escape(end),
        re.DOTALL | re.MULTILINE,
    )


_BLOCK_RE = block_regex(BEGIN_MARKER, END_MARKER)


class MarkersNotFoundError(RuntimeError):
    """Raised when install.sh does not contain both inlining markers."""


def read_library(library: Path = UI_SH) -> str:
    """Return the current contents of a library file, unmodified."""
    return library.read_text(encoding="utf-8")


def current_inlined_block(
    installer_text: str, begin: str = BEGIN_MARKER, end: str = END_MARKER
) -> str:
    """Return the text between a BEGIN/END marker pair in install.sh.

    Raises MarkersNotFoundError if either marker is missing, so a caller can
    never silently treat "no markers" as "empty block, already in sync".
    """
    match = block_regex(begin, end).search(installer_text)
    if not match:
        raise MarkersNotFoundError(
            f"could not find both '{begin}' and '{end}' in {INSTALL_SH}"
        )
    return match.group(1)


def render_installer(
    installer_text: str,
    library_text: str,
    begin: str = BEGIN_MARKER,
    end: str = END_MARKER,
) -> str:
    """Return install.sh's text with one inlined block replaced by library_text.

    Splices by index rather than `re.sub(..., replacement)`: re.sub treats
    backslashes in a replacement string as backreferences, and a shell
    library is full of them (`\\n`-in-strings, escaped characters in the
    banner art). Raises MarkersNotFoundError if the markers are missing.
    """
    match = block_regex(begin, end).search(installer_text)
    if not match:
        raise MarkersNotFoundError(
            f"could not find both '{begin}' and '{end}' in {INSTALL_SH}"
        )
    start, stop = match.span(1)
    return installer_text[:start] + library_text + installer_text[stop:]


def check(
    installer_text: str,
    library_text: str,
    begin: str = BEGIN_MARKER,
    end: str = END_MARKER,
) -> bool:
    """Return True when install.sh's inlined block matches the library exactly."""
    return current_inlined_block(installer_text, begin, end) == library_text


def main(argv: list[str] | None = None) -> int:
    """Entry point: sync (default) or report drift (--check) and return an exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit 1 instead of writing install.sh",
    )
    args = parser.parse_args(argv)

    installer_text = INSTALL_SH.read_text(encoding="utf-8")
    installer = INSTALL_SH.relative_to(REPO_ROOT)

    try:
        if args.check:
            drifted = False
            for library, begin, end in BLOCKS:
                name = library.relative_to(REPO_ROOT)
                if check(installer_text, read_library(library), begin, end):
                    print(f"{installer} is in sync with {name}")
                else:
                    drifted = True
                    print(
                        f"{installer} has drifted from {name} — run "
                        "'scripts/ci/sync_installer_ui.py' to fix.",
                        file=sys.stderr,
                    )
            return 1 if drifted else 0

        updated_text = installer_text
        for library, begin, end in BLOCKS:
            updated_text = render_installer(
                updated_text, read_library(library), begin, end
            )
        if updated_text != installer_text:
            INSTALL_SH.write_text(updated_text, encoding="utf-8")
            print(f"updated {installer}")
        else:
            print(f"{installer} already in sync")
        return 0
    except MarkersNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
