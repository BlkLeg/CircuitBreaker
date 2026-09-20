"""One switch, three modes, and the log independent of all of them.

The old helpers re-decided "am I a TTY / should I log this" at each call site,
which is how output modes drift apart the first time someone adds a step. These
assertions run the real library in a subshell and read what it produced.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UI = REPO_ROOT / "deploy" / "lib" / "ui.sh"

ANSI = re.compile(r"\033\[")

SCRIPT = """
set -euo pipefail
LOG_FILE="$1"; : > "$LOG_FILE"
source "{ui}"
cb_ui_init
cb_phase_begin preflight "Pre-flight checks"
cb_step "a quiet detail"
cb_warn "a loud warning"
cb_phase_end preflight
cb_ui_teardown
"""


def _run(tmp_path: Path, env: dict[str, str]) -> tuple[str, str]:
    log = tmp_path / "install.log"
    script = tmp_path / "drive.sh"
    script.write_text(SCRIPT.format(ui=UI))
    completed = subprocess.run(
        ["bash", str(script), str(log)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "TERM": "dumb", **env},
        check=True,
    )
    return completed.stdout, log.read_text(encoding="utf-8")


def test_plain_mode_emits_no_ansi(tmp_path: Path) -> None:
    stdout, _ = _run(tmp_path, {})
    assert not ANSI.search(stdout), (
        "plain mode emitted ANSI escapes. This output goes to CI logs, "
        "cloud-init consoles and `ssh host 'bash install.sh'` — none of which "
        "render them."
    )


def test_details_reach_the_log_in_every_mode(tmp_path: Path) -> None:
    for env in ({}, {"CB_VERBOSE": "true"}):
        _, log = _run(tmp_path, env)
        assert "a quiet detail" in log, f"detail lost from the log with env={env}"


def test_details_stay_off_the_screen_unless_verbose(tmp_path: Path) -> None:
    stdout, _ = _run(tmp_path, {})
    assert "a quiet detail" not in stdout


def test_verbose_puts_details_on_the_screen(tmp_path: Path) -> None:
    stdout, _ = _run(tmp_path, {"CB_VERBOSE": "true"})
    assert "a quiet detail" in stdout


def test_warnings_are_visible_in_every_mode(tmp_path: Path) -> None:
    """A warning the quiet mode swallowed would be a regression."""
    for env in ({}, {"CB_VERBOSE": "true"}, {"CI": "true"}, {"NO_COLOR": "1"}):
        stdout, log = _run(tmp_path, env)
        assert "a loud warning" in stdout, f"warning lost from the screen with env={env}"
        assert "a loud warning" in log, f"warning lost from the log with env={env}"
