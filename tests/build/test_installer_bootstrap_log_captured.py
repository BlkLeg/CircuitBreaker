"""The entire pre-flight phase must not be logged nowhere (M9).

``install.sh``'s ``main()`` used to declare ``LOG_FILE=""`` at file scope and
not assign it a real path until AFTER ``cb_phase_end preflight`` had already
run — ``_cb_log`` (``deploy/lib/ui.sh``) no-ops on an empty ``LOG_FILE``, so
``cb_ui_init``'s own "ui: mode=" line and every event ``stage0_bootstrap_
preflight`` logged during the "preflight" phase reached no file at all. The
line that finally set ``LOG_FILE`` then truncated ``/tmp/cb-bootstrap.log``
with ``>``, so even a second run through that code path could not recover the
missing records. A ``cb_fail`` during preflight printed "Full log:
/tmp/cb-bootstrap.log" for a file that did not exist yet, and
``cb_ui_log_tail`` silently returned nothing.

The fix: ``main()`` now sets and truncates ``LOG_FILE=/tmp/cb-bootstrap.log``
BEFORE calling ``cb_ui_init``, and the later re-truncation is gone — nothing
after that point overwrites the file, so the preflight phase's records
survive.

This test has two parts:

* a static order check on ``install.sh``'s ``main()`` — the assignment must
  precede ``cb_ui_init``, which must precede ``cb_phase_begin preflight`` —
  parsed rather than merely grepped for presence, so a regression that keeps
  the assignment but moves it back below ``cb_ui_init`` is still caught;
* a functional harness that sources the real ``deploy/lib/ui.sh``, replays
  that exact sequence (with a stub standing in for the actual OS/arch/tool
  checks ``stage0_bootstrap_preflight`` performs, since those require root
  and a real host), and asserts the resulting log file exists and contains
  records from the preflight phase specifically — not just that some file
  got written.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"
UI_SH = REPO_ROOT / "deploy" / "lib" / "ui.sh"


def _main_body() -> str:
    text = INSTALL_SH.read_text(encoding="utf-8")
    match = re.search(r"^main\(\) \{\n(.*?)^\}$", text, re.DOTALL | re.MULTILINE)
    assert match, "could not find main() in install.sh"
    return match.group(1)


def test_log_file_is_set_before_cb_ui_init_before_preflight_begins() -> None:
    """Parses the real order in install.sh's main(): the LOG_FILE assignment
    must come before cb_ui_init, which must come before the preflight phase
    opens. Catches a regression that re-adds the assignment but puts it back
    in the wrong place, not just one that deletes it."""
    body = _main_body()

    assign_matches = list(re.finditer(r'LOG_FILE="/tmp/cb-bootstrap\.log"', body))
    assert assign_matches, "main() never assigns LOG_FILE=/tmp/cb-bootstrap.log"

    init_matches = list(re.finditer(r"^\s*cb_ui_init\b", body, re.MULTILINE))
    assert init_matches, "main() never calls cb_ui_init"

    preflight_matches = list(re.finditer(r"cb_phase_begin\s+preflight\b", body))
    assert preflight_matches, 'main() never calls "cb_phase_begin preflight"'

    assert assign_matches[0].start() < init_matches[0].start(), (
        "LOG_FILE is assigned after cb_ui_init in main() — _cb_log no-ops on "
        "an empty LOG_FILE, so cb_ui_init's own 'ui: mode=' line would reach "
        "no file"
    )
    assert init_matches[0].start() < preflight_matches[0].start(), (
        "cb_ui_init runs after the preflight phase begins in main() — that "
        "reorders the mode-detection log line relative to the phase it is "
        "meant to precede"
    )

    # No re-truncation later in main(): only one assignment/truncation of
    # this path is allowed, or the preflight phase's own records (written
    # between that first assignment and cb_phase_end preflight) get wiped
    # out by a second one.
    assert len(assign_matches) == 1, (
        f"main() assigns LOG_FILE=/tmp/cb-bootstrap.log {len(assign_matches)} "
        "times — a second assignment re-truncates the file and destroys "
        "whatever the preflight phase already logged to it"
    )


def test_preflight_phase_is_captured_in_the_log_file() -> None:
    """Functional reproduction: replay main()'s real ordering (LOG_FILE set,
    then cb_ui_init, then the preflight phase) against the real ui.sh, with a
    stub in place of stage0_bootstrap_preflight (which needs root and a real
    host), and assert the resulting file exists and holds records from that
    phase specifically."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "cb-bootstrap.log"
        harness = f"""
set -euo pipefail
CB_UI_MODE=plain
source {UI_SH}
cb_ui_use_weights CB_PHASE_WEIGHTS_INSTALL >/dev/null

# Mirrors install.sh main(): assign and truncate LOG_FILE before cb_ui_init.
LOG_FILE="{log_path}"
echo "=== Bootstrap Log ===" > "$LOG_FILE"

cb_ui_init

cb_phase_begin preflight "Pre-flight checks"
# Stand-in for stage0_bootstrap_preflight's real OS/arch/tool checks.
cb_step "Detecting operating system"
cb_ok "debian detected"
cb_phase_end preflight
"""
        result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
        assert result.returncode == 0, (
            f"bootstrap log harness exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

        assert log_path.exists(), (
            "LOG_FILE was never created — the preflight phase logged nowhere, "
            "reproducing the M9 defect"
        )
        contents = log_path.read_text(encoding="utf-8")
        assert contents.strip() != "=== Bootstrap Log ===", (
            "the log file contains only its header — nothing from cb_ui_init "
            "or the preflight phase actually reached it"
        )
        assert "ui: mode=" in contents, (
            "cb_ui_init's mode-detection line is missing from the log"
        )
        assert "phase begin: preflight" in contents, (
            "the preflight phase's begin record is missing from the log"
        )
        assert "phase end: preflight" in contents, (
            "the preflight phase's end record is missing from the log"
        )
        assert "detail: Detecting operating system" in contents, (
            "a cb_step call made during the preflight phase never reached the log"
        )
