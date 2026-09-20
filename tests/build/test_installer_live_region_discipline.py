"""Guard for the "blind two-line rewind" live-region bug (I3).

``_cb_live_clear`` (``deploy/lib/ui.sh``) always rewinds the cursor up two
lines and clears them, on the assumption that those two lines are still its
own bar/timer from the last redraw. Nothing enforces that assumption — a
terminal has no read-back, so the renderer cannot tell "my own last draw"
from foreign output that landed after it (see the comment on
``_cb_live_clear`` itself for why there is no general fix for that inside the
renderer). Any raw ``echo``/``printf`` that runs while the live region is
"on" gets eaten by the next redraw.

The fix is call-site discipline, not a smarter renderer:

* ``cb_header`` (``install.sh``) and ``stage10_final_output``
  (``deploy/setup.sh``) must call ``cb_ui_teardown`` before they print
  anything of their own.
* ``uninstall.sh``'s trailing "Circuit Breaker has been uninstalled" banner
  must do the same, exactly like every interactive prompt earlier in that
  file already does via ``_cb_phase cb_ui_teardown``.
* ``run_upgrade`` (``deploy/setup.sh``) must close its "start" phase with
  ``cb_phase_end start`` — which re-arms the live region on its way out —
  *before* calling ``stage10_final_output``, never after. Reversed, the
  banner's own success text was printed while "start" was still open, and
  ``cb_phase_end``'s later ``_cb_live_clear`` ate its last two lines.

This test parses ``install.sh``, ``deploy/setup.sh`` and ``uninstall.sh``
statically — no pty, no subprocess — and checks each of those orderings
directly, so a regression in any one of the three files fails here rather
than only under a live TTY someone happened to be watching.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"
SETUP_SH = REPO_ROOT / "deploy" / "setup.sh"
UNINSTALL_SH = REPO_ROOT / "uninstall.sh"

# The exact guarded call every call site is expected to use: safe even if
# ui.sh was never sourced (cb_ui_teardown then simply does not exist).
_TEARDOWN_CALL_RE = re.compile(r"declare -f cb_ui_teardown\b[^\n]*&&\s*cb_ui_teardown\b")

# A top-level `name() { ... }` function definition, body captured non-greedily
# up to the first line that is exactly a lone closing brace. Same pattern
# test_installer_banner_unchanged.py already relies on for cb_logo().
_FUNC_BODY_RE_TEMPLATE = r"^{name}\(\) \{{\n(.*?)^\}}$"


def _function_body(text: str, name: str) -> str:
    """Return the body of a top-level bash function, or fail loudly."""
    pattern = _FUNC_BODY_RE_TEMPLATE.format(name=re.escape(name))
    match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    assert match, f"could not find a top-level function {name}() in the given source"
    return match.group(1)


def test_cb_header_tears_down_before_its_first_output() -> None:
    """cb_header must call cb_ui_teardown before `clear` — the first output
    it produces — not after."""
    body = _function_body(INSTALL_SH.read_text(encoding="utf-8"), "cb_header")
    teardown_match = _TEARDOWN_CALL_RE.search(body)
    assert teardown_match, "cb_header does not call cb_ui_teardown at all"
    clear_at = body.index("clear 2>/dev/null")
    assert teardown_match.start() < clear_at, (
        "cb_header calls cb_ui_teardown, but not before `clear` — the live "
        "region must be torn down before the first output this function "
        "produces, not after (the previous redraw would otherwise eat "
        "whatever `clear` leaves behind it)"
    )


def test_stage10_final_output_tears_down_before_its_first_output() -> None:
    """stage10_final_output is reachable from more than one path (fresh
    install and upgrade); it must tear down defensively at its own start
    rather than trust every caller to have done it first."""
    body = _function_body(SETUP_SH.read_text(encoding="utf-8"), "stage10_final_output")
    teardown_match = _TEARDOWN_CALL_RE.search(body)
    assert teardown_match, "stage10_final_output does not call cb_ui_teardown at all"
    section_at = body.index('cb_section "Circuit Breaker is running!"')
    assert teardown_match.start() < section_at, (
        "stage10_final_output calls cb_ui_teardown, but not before its own "
        "first output — it must tear down at the very start of the function"
    )


def test_run_upgrade_ends_the_start_phase_before_the_final_banner() -> None:
    """cb_phase_end re-arms the live region (it ends with a redraw), so
    stage10_final_output must run AFTER cb_phase_end start closes the phase,
    never before."""
    body = _function_body(SETUP_SH.read_text(encoding="utf-8"), "run_upgrade")
    phase_end_matches = list(re.finditer(r"cb_phase_end\s+start\b", body))
    assert phase_end_matches, 'run_upgrade never calls "cb_phase_end start"'
    final_output_matches = list(re.finditer(r"^\s*stage10_final_output\b", body, re.MULTILINE))
    assert final_output_matches, "run_upgrade never calls stage10_final_output"
    # Both call sites are unique within run_upgrade; compare their positions
    # in the source directly rather than only asserting both are present —
    # presence alone is exactly what let the reversed order ship unnoticed.
    assert phase_end_matches[-1].start() < final_output_matches[-1].start(), (
        'run_upgrade calls stage10_final_output before "cb_phase_end start" '
        "closes the phase. The live region is still open at that point, so "
        "the phase's own closing redraw eats the banner's last two lines — "
        "this is the exact I3 upgrade-path bug."
    )


def test_uninstall_tears_down_before_its_trailing_banner() -> None:
    """uninstall.sh prints nine raw `echo -e` lines after its last phase ends
    (the "Circuit Breaker has been uninstalled" block). It must tear the live
    region down first, exactly like every interactive prompt earlier in the
    same file already does via `_cb_phase cb_ui_teardown`.

    Several earlier sections (Docker image removal, TLS/Caddy cleanup, native
    binary cleanup, macOS cleanup) already call `_cb_phase cb_ui_teardown`
    before their own interactive prompts — but every one of those sections is
    conditional, so none of those calls is guaranteed to run. This anchors on
    "Removed cb command.", the last action in the file's final *unconditional*
    section, and requires the teardown call to sit strictly between that
    anchor and the banner — i.e. in code that always runs — rather than
    anywhere earlier in the file, which an unconditional-call regression could
    satisfy vacuously via one of those conditional sections instead.
    """
    text = UNINSTALL_SH.read_text(encoding="utf-8")
    banner_at = text.index("Circuit Breaker has been uninstalled.")
    anchor_at = text.index('Show 0 "Removed cb command."')
    assert anchor_at < banner_at, (
        "the 'Removed cb command.' anchor does not precede the closing "
        "banner — the parser's assumptions about this file's layout no "
        "longer hold"
    )
    teardown_between = [
        m
        for m in re.finditer(r"_cb_phase\s+cb_ui_teardown\b", text)
        if anchor_at < m.start() < banner_at
    ]
    assert teardown_between, (
        "uninstall.sh does not call `_cb_phase cb_ui_teardown` in its final "
        "unconditional section, between 'Removed cb command.' and the "
        "trailing 'Circuit Breaker has been uninstalled' banner — the live "
        "region is still armed there and would eat the banner's first lines. "
        "(Teardown calls inside the earlier conditional cleanup sections do "
        "not count: none of them is guaranteed to run.)"
    )


def test_the_parser_found_what_it_expected() -> None:
    """Guards the guards above: if an extraction regex silently stopped
    matching (a rename, a reformat), the assertions it feeds would pass
    vacuously on empty or missing input. Pin non-trivial sizes/counts so
    that failure mode cannot pass unnoticed."""
    header_body = _function_body(INSTALL_SH.read_text(encoding="utf-8"), "cb_header")
    assert len(header_body.splitlines()) > 10, "cb_header body parsed suspiciously short"

    setup_text = SETUP_SH.read_text(encoding="utf-8")

    stage10_body = _function_body(setup_text, "stage10_final_output")
    assert len(stage10_body.splitlines()) > 20, "stage10_final_output body parsed suspiciously short"

    run_upgrade_body = _function_body(setup_text, "run_upgrade")
    assert len(run_upgrade_body.splitlines()) > 50, "run_upgrade body parsed suspiciously short"
    assert run_upgrade_body.count("cb_phase_begin") >= 4, "run_upgrade should open at least 4 phases"
    assert run_upgrade_body.count("cb_phase_end") >= 4, "run_upgrade should close at least 4 phases"

    uninstall_text = UNINSTALL_SH.read_text(encoding="utf-8")
    assert uninstall_text.count("_cb_phase cb_ui_teardown") >= 5, (
        "uninstall.sh should have several existing cb_ui_teardown call sites "
        "(one per interactive prompt) plus the new one this defect adds"
    )
