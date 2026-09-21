"""On failure the quiet screen must get LONGER, in a fixed order, and say
where the rest of the evidence lives.

cb_fail is the one moment the install's normally-quiet output is wrong to stay
quiet: it tears the live progress bar down first (a redrawing bar interleaved
with diagnostics is unreadable), then shows the ledger and log tail the quiet
mode withheld, and only then runs the armed diagnostics — in that order,
because the ledger and log tail are the most likely place the actual cause is
written and an operator should not have to scroll past a diagnostics dump to
find them. It closes by naming the full log path and the `--verbose` re-run
explicitly, because an operator should never have to know to go and find
either.

Where the ordering IS observable on screen (ledger, log tail, diagnostics all
print unconditionally, even in plain/non-tty mode) these tests drive the real
cb_fail — extracted from the shipped install.sh, not reimplemented — in a real
shell and read the real, ordered output. `cb_ui_teardown`'s only effect is a
terminal escape sequence that a non-tty run never emits, so its position
relative to the others is not something a plain-mode run can observe; that one
relationship is checked by reading cb_fail's source instead.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "install.sh"
UI = REPO_ROOT / "deploy" / "lib" / "ui.sh"


def _extract_function(name: str, text: str) -> str:
    match = re.search(rf"^{re.escape(name)}\(\)\s*\{{.*?^\}}$", text, re.DOTALL | re.MULTILINE)
    assert match, f"install.sh no longer defines {name}()"
    return match.group(0)


def _cb_fail_source() -> str:
    return _extract_function("cb_fail", INSTALLER.read_text(encoding="utf-8"))


def test_cb_fail_source_tears_down_the_live_region_before_anything_else() -> None:
    """cb_ui_teardown's only visible effect (`\\033[?25h`, showing the cursor
    again) never reaches a non-tty run, so this one relationship in the
    ordering is checked by reading cb_fail's body rather than by driving it."""
    body = _cb_fail_source()
    teardown_at = body.find("cb_ui_teardown")
    ledger_at = body.find("cb_ui_ledger")
    log_tail_at = body.find("cb_ui_log_tail")
    diagnostics_at = body.find("cb_run_diagnostics")
    for name, position in (
        ("cb_ui_teardown", teardown_at),
        ("cb_ui_ledger", ledger_at),
        ("cb_ui_log_tail", log_tail_at),
        ("cb_run_diagnostics", diagnostics_at),
    ):
        assert position != -1, f"cb_fail() no longer calls {name}"
    assert teardown_at < ledger_at < log_tail_at < diagnostics_at, (
        "cb_fail() must tear the live region down, then show the ledger, then "
        "the log tail, and only then run diagnostics — a redrawing bar "
        f"interleaved with any of that is unreadable. Found: teardown@{teardown_at}, "
        f"ledger@{ledger_at}, log_tail@{log_tail_at}, diagnostics@{diagnostics_at}"
    )


def test_cb_fail_names_the_full_log_and_the_verbose_rerun() -> None:
    body = _cb_fail_source()
    assert "Full log:" in body, (
        "cb_fail() no longer names 'Full log:' — an operator should never have "
        "to know to go and find it."
    )
    assert "--verbose" in body, (
        "cb_fail() no longer names the --verbose re-run as a next step."
    )


# ---------------------------------------------------------------------------
# Behaviour: drive the real cb_fail (extracted from the shipped install.sh,
# sourced together with the real deploy/lib/ui.sh) and read the real output.
# ---------------------------------------------------------------------------

_HARNESS = """
set -euo pipefail
RED='' YELLOW='' BOLD='' DIM='' RESET='' CYAN=''
LOG_FILE="$1"
: > "$LOG_FILE"
echo "MARKER_LOG_CONTENT" >> "$LOG_FILE"

source "{ui}"
cb_ui_init

CB_STAGE_HINTS=()
CB_STAGE_DIAGS=("Fake diagnostic::echo MARKER_DIAGNOSTIC_OUTPUT")
CB_DIAG_LINES=50
_CB_DIAG_RUNNING=false

{run_diagnostics}

{cb_fail}

cb_phase_begin preflight "Pre-flight checks"
cb_phase_end preflight

cb_fail "boom" "try again" || true
"""


def _run_cb_fail(tmp_path: Path) -> tuple[str, int]:
    installer_text = INSTALLER.read_text(encoding="utf-8")
    run_diagnostics = _extract_function("cb_run_diagnostics", installer_text)
    cb_fail = _extract_function("cb_fail", installer_text)

    script = tmp_path / "drive.sh"
    script.write_text(
        _HARNESS.format(ui=UI, run_diagnostics=run_diagnostics, cb_fail=cb_fail)
    )
    log = tmp_path / "install.log"
    completed = subprocess.run(
        ["bash", str(script), str(log)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "TERM": "dumb"},
    )
    return completed.stdout, completed.returncode


def test_cb_fail_exits_nonzero(tmp_path: Path) -> None:
    _stdout, returncode = _run_cb_fail(tmp_path)
    assert returncode == 1, "cb_fail must exit non-zero so the installer stops"


def test_cb_fail_shows_the_ledger_before_the_log_tail_before_diagnostics(
    tmp_path: Path,
) -> None:
    stdout, _ = _run_cb_fail(tmp_path)
    ledger_at = stdout.find("Install progress")
    log_tail_at = stdout.find("Last 30 lines of the install log")
    diagnostics_at = stdout.find("Diagnostics")
    for label, position in (
        ("the ledger ('Install progress')", ledger_at),
        ("the log tail ('Last 30 lines...')", log_tail_at),
        ("diagnostics ('Diagnostics')", diagnostics_at),
    ):
        assert position != -1, f"cb_fail's real output never showed {label}"
    assert ledger_at < log_tail_at < diagnostics_at, (
        "cb_fail printed the ledger, log tail and diagnostics out of order: "
        f"ledger@{ledger_at}, log_tail@{log_tail_at}, diagnostics@{diagnostics_at}\n"
        f"--- full output ---\n{stdout}"
    )


def test_cb_fail_shows_the_completed_phase_in_the_ledger(tmp_path: Path) -> None:
    """The ledger is the context the quiet screen withheld -- it must reflect
    the phase that actually ran, not a canned line."""
    stdout, _ = _run_cb_fail(tmp_path)
    assert "Pre-flight checks" in stdout, (
        "cb_fail's ledger did not show the completed 'Pre-flight checks' phase"
    )


def test_cb_fail_shows_the_real_log_content(tmp_path: Path) -> None:
    """The log tail must come from the actual $LOG_FILE, not a hardcoded
    example -- this is the subprocess output the quiet mode hid."""
    stdout, _ = _run_cb_fail(tmp_path)
    assert "MARKER_LOG_CONTENT" in stdout, (
        "cb_fail's log tail did not include content actually written to LOG_FILE"
    )


def test_cb_fail_runs_the_armed_diagnostics(tmp_path: Path) -> None:
    stdout, _ = _run_cb_fail(tmp_path)
    assert "MARKER_DIAGNOSTIC_OUTPUT" in stdout, (
        "cb_fail did not run the armed CB_STAGE_DIAGS diagnostic"
    )


def test_cb_fail_names_the_full_log_path_and_verbose_rerun_on_screen(
    tmp_path: Path,
) -> None:
    stdout, _ = _run_cb_fail(tmp_path)
    assert "Full log:" in stdout
    assert re.search(r"--verbose", stdout), "the --verbose re-run was not shown on screen"
