"""An installer that stops must say that it stopped, and where.

install.sh runs under `set -euo pipefail`, so any unchecked failure ends the run
on the spot. cb_fail only reports the failures somebody anticipated; everything
else used to reach an EXIT trap whose one job was to erase the progress bar. The
operator got a clean prompt after "▸ System dependencies" and nothing else — no
error, no exit code, no pointer to the log. The dpkg conffile prompt that ended
a re-run on Ubuntu (see test_installer_unattended_contract.py) was diagnosable
only because the operator knew to go and read install.log.

These tests drive the real cb_fail and exit hooks — extracted from the shipped
install.sh, sourced with the real deploy/lib/ui.sh — against a stand-in stage
file that fails the way deploy/setup.sh does: an unchecked command inside a
function, in a sourced file, while a phase is open.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "install.sh"
UI = REPO_ROOT / "deploy" / "lib" / "ui.sh"

_EXIT_HOOKS = ("cb_run_diagnostics", "cb_fail", "_cb_note_err", "_cb_on_exit", "cb_arm_exit_report")

_STAGE = """\
apt_like() {{ return 100; }}
stage2_dependencies() {{
  if ! grep -q absent /dev/null; then :; fi
  apt_like install -y -q pgbouncer >> "$LOG_FILE" 2>&1
  echo NOT_REACHED
}}
stage_fails_on_purpose() {{
  cb_fail "Anticipated failure" "Do the documented thing"
}}
stage_succeeds() {{
  echo STAGE_DONE
}}
stage_interrupted() {{
  kill -INT $$
  sleep 5
}}
"""

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

{hooks}

cb_arm_exit_report
source "{stage}"
cb_phase_begin deps "System dependencies"
"$2"
cb_phase_end deps
"""


def _extract_function(name: str, text: str) -> str:
    match = re.search(rf"^{re.escape(name)}\(\)\s*\{{.*?^\}}$", text, re.DOTALL | re.MULTILINE)
    assert match, f"install.sh no longer defines {name}()"
    return match.group(0)


def _run(tmp_path: Path, stage_function: str) -> subprocess.CompletedProcess[str]:
    installer_text = INSTALLER.read_text(encoding="utf-8")
    hooks = "\n\n".join(_extract_function(name, installer_text) for name in _EXIT_HOOKS)
    stage = tmp_path / "setup.sh"
    stage.write_text(_STAGE.format(), encoding="utf-8")
    script = tmp_path / "drive.sh"
    script.write_text(_HARNESS.format(ui=UI, hooks=hooks, stage=stage), encoding="utf-8")
    return subprocess.run(
        ["bash", str(script), str(tmp_path / "install.log"), stage_function],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "TERM": "dumb"},
        timeout=30,
    )


def test_an_unchecked_failure_is_reported_instead_of_ending_silently(tmp_path: Path) -> None:
    run = _run(tmp_path, "stage2_dependencies")
    out = run.stdout
    assert "NOT_REACHED" not in out, "the stand-in stage did not fail where it was meant to"
    assert "stopped unexpectedly" in out, (
        "an unchecked failure under `set -e` ended the installer without saying "
        f"so — the operator sees a bare prompt.\n--- output ---\n{out}"
    )
    assert "exit 100" in out, f"the report does not give the exit status\n{out}"
    assert "System dependencies" in out, f"the report does not name the open phase\n{out}"


def test_the_report_names_the_file_line_function_and_source_text(tmp_path: Path) -> None:
    """BASH_COMMAND alone names the last simple command bash ran, which for a
    failing function call is that function's `return` — the call site's own
    text is what an operator (and the issue they file) needs."""
    out = _run(tmp_path, "stage2_dependencies").stdout
    assert re.search(r"setup\.sh:4 in stage2_dependencies\(\)", out), (
        f"the report does not locate the failure as setup.sh:4 in stage2_dependencies()\n{out}"
    )
    assert "apt_like install -y -q pgbouncer" in out, (
        f"the report does not show the failing source line\n{out}"
    )


def test_the_report_carries_the_log_tail_and_diagnostics(tmp_path: Path) -> None:
    """Same evidence cb_fail gives an anticipated failure: the unexpected ones
    are the ones nobody armed a hint for, so they need it more."""
    out = _run(tmp_path, "stage2_dependencies").stdout
    assert "MARKER_LOG_CONTENT" in out, f"no install-log tail in the report\n{out}"
    assert "MARKER_DIAGNOSTIC_OUTPUT" in out, f"armed diagnostics did not run\n{out}"
    assert "Full log:" in out, f"the report does not name the full log\n{out}"


def test_the_failing_exit_status_is_preserved(tmp_path: Path) -> None:
    """Provisioning (Proxmox LXC, cloud-init, Ansible) branches on the exit
    status; reporting the failure must not flatten it to 1."""
    assert _run(tmp_path, "stage2_dependencies").returncode == 100


def test_an_anticipated_failure_is_reported_exactly_once(tmp_path: Path) -> None:
    run = _run(tmp_path, "stage_fails_on_purpose")
    assert run.returncode == 1
    assert run.stdout.count("ERROR:") == 1, (
        "cb_fail's own report was followed by a second one from the exit hook\n"
        f"--- output ---\n{run.stdout}"
    )
    assert "stopped unexpectedly" not in run.stdout


def test_a_successful_run_prints_no_report(tmp_path: Path) -> None:
    run = _run(tmp_path, "stage_succeeds")
    assert run.returncode == 0, run.stdout + run.stderr
    assert "STAGE_DONE" in run.stdout
    assert "ERROR:" not in run.stdout


def test_an_interrupt_is_named_without_a_diagnostics_dump(tmp_path: Path) -> None:
    """Ctrl-C is the operator leaving on purpose: say it was interrupted and
    where the log is, and do not make them wait on journalctl on the way out."""
    run = _run(tmp_path, "stage_interrupted")
    assert run.returncode == 130, run.stdout + run.stderr
    assert "interrupted" in run.stdout, f"the interrupt was not named\n{run.stdout}"
    assert "MARKER_DIAGNOSTIC_OUTPUT" not in run.stdout
    assert "Full log:" in run.stdout


def test_main_arms_the_report_before_the_first_phase() -> None:
    """cb_ui_init installs its own tty-only EXIT trap; the report must be armed
    after it (a later `trap ... EXIT` replaces an earlier one) and before
    anything that can fail."""
    main_body = _extract_function("main", INSTALLER.read_text(encoding="utf-8"))
    init_at = main_body.find("cb_ui_init")
    arm_at = main_body.find("cb_arm_exit_report")
    phase_at = main_body.find("cb_phase_begin")
    assert -1 not in (init_at, arm_at, phase_at), "main() no longer calls cb_ui_init, cb_arm_exit_report and cb_phase_begin"
    assert init_at < arm_at < phase_at, (
        f"main() must arm the exit report after cb_ui_init and before the first phase "
        f"(cb_ui_init@{init_at}, cb_arm_exit_report@{arm_at}, cb_phase_begin@{phase_at})"
    )
