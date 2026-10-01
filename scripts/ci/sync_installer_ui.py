#!/usr/bin/env python3
"""Keep the inlined copies of deploy/lib/ libraries byte-identical to the source.

install.sh is served raw from `main` — pages.yml does a bare `cp` and the
documented install command is `curl -fsSL .../main/install.sh | sudo bash` —
so it cannot `source deploy/lib/ui.sh` at runtime without breaking every
curl|bash install on a host that never cloned the repo. It carries an inlined
copy between two marker comments instead, and `deploy/setup.sh`/`uninstall.sh`
use the real library from the installed bundle. cb-proxmox-deploy.sh is run
the same way (`bash -c "$(curl -fsSL .../main/cb-proxmox-deploy.sh)"`) and
inlines deploy/lib/bundle-signature.sh so it can verify a release bundle on
the Proxmox host. That is a pair pinned in two places, and CLAUDE.md's rule
for that shape is explicit: the guard belongs in the tree, not only the fix.

This script is that guard's write side: for each entry in BLOCKS it replaces
everything between the markers in the target file with the current contents
of the library. `tests/build/test_installer_ui_inline_matches_library.py` is
the read side, run in CI; `--check` here is the same comparison for local use.

Usage:
    scripts/ci/sync_installer_ui.py            # rewrite every target in place
    scripts/ci/sync_installer_ui.py --check    # report drift, exit 1, no write
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"
PROXMOX_SH = REPO_ROOT / "cb-proxmox-deploy.sh"


class Block(NamedTuple):
    """One library inlined into one target file between two marker lines."""

    target: Path
    library: Path
    begin: str
    end: str


_UI_BEGIN = "# --- BEGIN INLINED deploy/lib/ui.sh — regenerate with scripts/ci/sync_installer_ui.py ---"
_UI_END = "# --- END INLINED deploy/lib/ui.sh ---"
_SIG_BEGIN = (
    "# --- BEGIN INLINED deploy/lib/bundle-signature.sh — regenerate with "
    "scripts/ci/sync_installer_ui.py ---"
)
_SIG_END = "# --- END INLINED deploy/lib/bundle-signature.sh ---"

BLOCKS: list[Block] = [
    Block(INSTALL_SH, REPO_ROOT / "deploy" / "lib" / "ui.sh", _UI_BEGIN, _UI_END),
    Block(
        INSTALL_SH,
        REPO_ROOT / "deploy" / "lib" / "bundle-signature.sh",
        _SIG_BEGIN,
        _SIG_END,
    ),
    Block(
        PROXMOX_SH,
        REPO_ROOT / "deploy" / "lib" / "bundle-signature.sh",
        _SIG_BEGIN,
        _SIG_END,
    ),
]

# Aliases for the first block, kept for anything that still uses the old names.
UI_SH, BEGIN_MARKER, END_MARKER = BLOCKS[0].library, BLOCKS[0].begin, BLOCKS[0].end


def block_regex(begin: str, end: str) -> re.Pattern[str]:
    """Return the regex that captures the text between one BEGIN/END marker pair."""
    return re.compile(
        re.escape(begin) + r"\n(.*)^" + re.escape(end),
        re.DOTALL | re.MULTILINE,
    )


class MarkersNotFoundError(RuntimeError):
    """Raised when a target file does not contain both inlining markers."""


def read_library(library: Path = UI_SH) -> str:
    """Return the current contents of a library file, unmodified."""
    return library.read_text(encoding="utf-8")


def current_inlined_block(
    installer_text: str,
    begin: str = BEGIN_MARKER,
    end: str = END_MARKER,
    target: Path = INSTALL_SH,
) -> str:
    """Return the text between a BEGIN/END marker pair in a target file's text.

    Raises MarkersNotFoundError if either marker is missing, so a caller can
    never silently treat "no markers" as "empty block, already in sync".
    """
    match = block_regex(begin, end).search(installer_text)
    if not match:
        raise MarkersNotFoundError(
            f"could not find both '{begin}' and '{end}' in {target}"
        )
    return match.group(1)


def render_installer(
    installer_text: str,
    library_text: str,
    begin: str = BEGIN_MARKER,
    end: str = END_MARKER,
    target: Path = INSTALL_SH,
) -> str:
    """Return a target file's text with one inlined block replaced by library_text.

    Splices by index rather than `re.sub(..., replacement)`: re.sub treats
    backslashes in a replacement string as backreferences, and a shell
    library is full of them (`\\n`-in-strings, escaped characters in the
    banner art). Raises MarkersNotFoundError if the markers are missing.
    """
    match = block_regex(begin, end).search(installer_text)
    if not match:
        raise MarkersNotFoundError(
            f"could not find both '{begin}' and '{end}' in {target}"
        )
    start, stop = match.span(1)
    return installer_text[:start] + library_text + installer_text[stop:]


def check(
    installer_text: str,
    library_text: str,
    begin: str = BEGIN_MARKER,
    end: str = END_MARKER,
    target: Path = INSTALL_SH,
) -> bool:
    """Return True when a target's inlined block matches the library exactly."""
    return current_inlined_block(installer_text, begin, end, target) == library_text


def _relative(path: Path) -> Path:
    """Return path relative to the repo root when it lies inside it."""
    try:
        return path.relative_to(REPO_ROOT)
    except ValueError:
        return path


def _targets() -> list[Path]:
    """Return each distinct target in BLOCKS, in first-seen order."""
    seen: list[Path] = []
    for block in BLOCKS:
        if block.target not in seen:
            seen.append(block.target)
    return seen


def main(argv: list[str] | None = None) -> int:
    """Entry point: sync (default) or report drift (--check) and return an exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit 1 instead of writing any target",
    )
    args = parser.parse_args(argv)

    try:
        if args.check:
            drifted = False
            for block in BLOCKS:
                text = block.target.read_text(encoding="utf-8")
                target = _relative(block.target)
                name = _relative(block.library)
                if check(
                    text,
                    read_library(block.library),
                    block.begin,
                    block.end,
                    block.target,
                ):
                    print(f"{target} is in sync with {name}")
                else:
                    drifted = True
                    print(
                        f"{target} has drifted from {name} — run "
                        "'scripts/ci/sync_installer_ui.py' to fix.",
                        file=sys.stderr,
                    )
            return 1 if drifted else 0

        # Render every target before writing any, so a missing marker in one
        # leaves all of them untouched.
        rendered: list[tuple[Path, str, str]] = []
        for target_path in _targets():
            original = target_path.read_text(encoding="utf-8")
            updated = original
            for block in BLOCKS:
                if block.target == target_path:
                    updated = render_installer(
                        updated,
                        read_library(block.library),
                        block.begin,
                        block.end,
                        target_path,
                    )
            rendered.append((target_path, original, updated))
        for target_path, original, updated in rendered:
            if updated != original:
                target_path.write_text(updated, encoding="utf-8")
                print(f"updated {_relative(target_path)}")
            else:
                print(f"{_relative(target_path)} already in sync")
        return 0
    except MarkersNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
