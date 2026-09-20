"""The installer's live ETA must never show a bigger number than it already
showed.

``_cb_render_eta`` (in ``deploy/lib/ui.sh``) computed a clamped, monotone
remaining-time estimate and wrote the clamp state — ``_CB_LAST_ETA`` — as its
last line, but every caller invoked it as ``$(_cb_render_eta)``. Command
substitution always runs in a subshell, so that assignment died with the
subshell the instant it exited: the parent shell's ``_CB_LAST_ETA`` never
moved off its initial ``-1``, the "never grows" clamp always compared against
that sentinel, and the estimate grew without bound on a stalled phase (e.g.
frozen at 20% progress: 60s elapsed -> ~4m remaining, 120s -> ~8m, 240s ->
~16m, 480s -> ~32m — each a clean doubling, because nothing was ever clamped).

The fix split the function: ``_cb_update_eta`` computes the estimate and
writes ``_CB_ETA_TEXT``/``_CB_LAST_ETA`` directly, called on its own line (no
substitution, no subshell) from ``_cb_live_draw`` before the bar text is
captured; ``_cb_render_eta`` is now a pure printer of ``_CB_ETA_TEXT``, safe to
call from inside ``$(...)`` because it writes nothing.

This test drives ``_cb_update_eta`` the same way production code does — direct
calls in one shell, never wrapped in a command substitution — and asserts the
printed remaining-time sequence is non-increasing, both when progress stalls
(the exact reproduction above) and when progress climbs normally.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_SH = REPO_ROOT / "deploy" / "lib" / "ui.sh"

# Drives _cb_update_eta directly, in one shell, across several simulated
# moments in time -- exactly how _cb_live_draw calls it. _CB_START_EPOCH is
# walked backwards to simulate elapsed time passing without an actual sleep,
# and _CB_OPEN_PHASE is left empty throughout so the "taking longer than
# expected" branch (which needs an open phase) never fires and every case
# below exercises the numeric clamp.
HARNESS = f"""
set -euo pipefail
CB_UI_MODE=plain
source {UI_SH}

emit() {{
  _cb_update_eta
  printf 'ETA:%s\\n' "${{_CB_ETA_TEXT}}"
}}

NOW="$(date +%s)"

# Case 1: progress frozen at 20%, elapsed climbing -- the stall that exposed
# the bug. A displayed estimate must never grow, so this must go flat, not
# double every step the way the unfixed code did.
_CB_DONE_WEIGHT=20
_CB_OPEN_PHASE=""
_CB_LAST_ETA=-1
for elapsed in 60 120 240 480; do
  _CB_START_EPOCH=$(( NOW - elapsed ))
  emit
done

echo "---"

# Case 2: progress and elapsed both climbing normally. The raw (unclamped)
# math already trends down here, so this catches a clamp that runs backwards
# as readily as one that never runs at all.
_CB_LAST_ETA=-1
_CB_OPEN_PHASE=""
for pair in "10:10" "20:20" "40:30" "80:40"; do
  pct="${{pair%%:*}}"
  elapsed="${{pair##*:}}"
  _CB_DONE_WEIGHT="$pct"
  _CB_START_EPOCH=$(( NOW - elapsed ))
  emit
done
"""

_ETA_RE = re.compile(r"^ETA:~(?:(\d+)m )?(\d+)s remaining$")


def _eta_seconds(line: str) -> int:
    match = _ETA_RE.match(line)
    assert match, f"unexpected ETA line, not a numeric estimate: {line!r}"
    minutes, seconds = match.groups()
    return (int(minutes) * 60 if minutes else 0) + int(seconds)


def _run_harness() -> tuple[list[int], list[int]]:
    result = subprocess.run(
        ["bash", "-c", HARNESS],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ETA harness exited {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    stall_block, climb_block = result.stdout.strip().split("---")
    stall = [_eta_seconds(line) for line in stall_block.strip().splitlines()]
    climb = [_eta_seconds(line) for line in climb_block.strip().splitlines()]
    return stall, climb


def _assert_non_increasing(sequence: list[int], label: str) -> None:
    for prev, cur in zip(sequence, sequence[1:]):
        assert cur <= prev, (
            f"{label} ETA sequence is not monotone non-increasing: {sequence}. "
            f"A displayed estimate must never grow; it grew from {prev}s to "
            f"{cur}s here."
        )


def test_eta_does_not_grow_while_a_phase_is_stalled():
    """The exact reproduction: progress frozen, elapsed climbing. Before the
    fix this doubled every step (240 -> 480 -> 960 -> 1920); it must now go
    flat at the first clamp."""
    stall, _climb = _run_harness()
    assert len(stall) == 4, f"expected 4 stalled-progress samples, got {stall}"
    _assert_non_increasing(stall, "stalled-progress")


def test_eta_does_not_grow_while_progress_climbs_normally():
    """Progress and elapsed both increasing is the common case, not just the
    stall -- the clamp must hold here too."""
    _stall, climb = _run_harness()
    assert len(climb) == 4, f"expected 4 climbing-progress samples, got {climb}"
    _assert_non_increasing(climb, "climbing-progress")
