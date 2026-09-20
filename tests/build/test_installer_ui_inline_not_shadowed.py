"""install.sh must not redefine, below the inlined block, a function the
inlined deploy/lib/ui.sh block already defines.

This is the incident this guards against. install.sh carries an inlined copy
of deploy/lib/ui.sh between marker comments, and
test_installer_ui_inline_matches_library.py pins that copy byte-for-byte
against the source library. The redesigned renderer shipped inside that
block, was reviewed, and matched the library exactly — and never ran. Four
one-line functions (`cb_step`, `cb_ok`, `cb_warn`, `cb_section`) were defined
a second time about 150 lines further down the file, with the old loud
`echo`-based bodies from before the renderer redesign. Bash keeps only the
last definition of a function name, so those four stale one-liners silently
won every time, and the quiet, log-writing renderer the block defines was
dead code that no test caught, because every existing guard checks the
*contents* of the marker block, not what the rest of the file does with the
names the block defines.

This test parses the function names the marker block defines and asserts
none of them is defined again anywhere after the block ends. It cannot
prevent someone from reintroducing the bug under a new function name, but it
makes the exact failure mode that already happened here — silently
shadowing an inlined function with a stale later definition of the same
name — impossible to reintroduce unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"

BEGIN_MARKER = (
    "# --- BEGIN INLINED deploy/lib/ui.sh "
    "— regenerate with scripts/ci/sync_installer_ui.py ---"
)
END_MARKER = "# --- END INLINED deploy/lib/ui.sh ---"

# A bash function definition at the start of a line: `name() {`, with or
# without whitespace before the brace, and whether the body starts on the
# same line (a one-liner like `cb_step() { cb_detail "$1"; }`) or on the
# next one. Matches only top-level (column 0) definitions, which is how
# every function in both the inlined block and the rest of install.sh is
# written.
_FUNC_DEF_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{", re.MULTILINE)


def _split_install_sh() -> tuple[str, str]:
    """Return (marker block contents, everything after the end marker)."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    begin_at = text.index(BEGIN_MARKER)
    end_at = text.index(END_MARKER, begin_at)
    block = text[begin_at + len(BEGIN_MARKER) : end_at]
    after = text[end_at + len(END_MARKER) :]
    return block, after


def test_the_marker_block_defines_a_non_trivial_number_of_functions() -> None:
    """Guards the guard: if the parser regressed and stopped matching real
    function definitions, the shadowing test below must not pass vacuously
    by having no names to check."""
    block, _after = _split_install_sh()
    names = _FUNC_DEF_RE.findall(block)
    assert len(names) >= 10, (
        "expected the inlined deploy/lib/ui.sh block in install.sh to define "
        f"at least 10 functions, found {len(names)}: {sorted(set(names))!r}. "
        "Either the marker block is missing content or the function-name "
        "parser above no longer matches how install.sh defines functions."
    )


def test_no_inlined_function_is_redefined_after_the_block() -> None:
    """The bug: install.sh redefined cb_step/cb_ok/cb_warn/cb_section after
    the inlined block, and bash's last-definition-wins semantics meant those
    stale echo-only bodies ran instead of the block's quiet, log-writing
    ones. Any function name the block defines must not appear as a
    top-level definition anywhere later in the file."""
    block, after = _split_install_sh()
    inlined_names = set(_FUNC_DEF_RE.findall(block))
    redefined_after = sorted(
        name for name in inlined_names if re.search(
            r"^" + re.escape(name) + r"\s*\(\)\s*\{", after, re.MULTILINE
        )
    )
    assert not redefined_after, (
        "install.sh redefines these function(s) after the inlined "
        f"deploy/lib/ui.sh block: {redefined_after!r}. Bash keeps only the "
        "last definition, so these later bodies silently shadow the ones "
        "the inlined block defines — this is exactly how the installer "
        "redesign shipped, reviewed clean, and never ran. Delete the later "
        "definition(s); the inlined block already provides them."
    )
