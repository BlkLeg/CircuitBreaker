"""The installer's "taking longer than expected" message must not fire a few
seconds into every run (I4).

``_cb_update_eta`` (``deploy/lib/ui.sh``) had two compounding bugs:

* The overrun check ran BEFORE the ``pct < 5`` "estimating..." guard, so it
  could fire during the very first phase of a run, before any phase had
  finished and while the divisor behind any estimate was still noise.
* The budget it compared against was computed off TOTAL elapsed time —
  ``budget = elapsed * open_weight / 100`` — but early in a run ``elapsed`` is
  almost entirely the currently-open phase's own time. For ``preflight``
  (weight 2 of 100), that collapsed the condition to roughly
  ``open_elapsed > 2``: three seconds into *every* install or uninstall, on a
  real TTY, the first thing a user saw was the pessimistic message the design
  reserved for a genuinely slow mirror. ``preflight`` routinely takes longer
  than that on its own (OS detection, disk checks, a reachability probe;
  uninstall's preflight also blocks on a ``/dev/tty`` confirmation prompt).

The fix: move the overrun check after the ``pct < 5`` guard, budget off a
*projected total* run length (``elapsed * 100 / pct``) rather than raw
elapsed, and add an absolute 30-second floor so a low-weight phase's small
budget cannot trip the ratio alone on ordinary noise.

This test drives ``_cb_update_eta`` directly — one shell, no command
substitution, exactly how ``_cb_live_draw`` calls it — with synthetic epochs,
and is a sibling to ``test_installer_eta_monotonic.py`` rather than an edit to
it: that file's harness only ever exercises the numeric-clamp path with
``_CB_OPEN_PHASE`` empty, and must keep passing completely unedited.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_SH = REPO_ROOT / "deploy" / "lib" / "ui.sh"

# Drives _cb_update_eta directly against CB_PHASE_WEIGHTS_INSTALL, walking
# _CB_START_EPOCH/_CB_OPEN_START backwards to simulate elapsed time passing
# without an actual sleep — same technique test_installer_eta_monotonic.py
# uses. Each case sets _CB_DONE_WEIGHT directly to control overall pct
# without needing real completed phases.
HARNESS = f"""
set -euo pipefail
CB_UI_MODE=plain
source {UI_SH}
cb_ui_use_weights CB_PHASE_WEIGHTS_INSTALL >/dev/null

emit() {{
  local phase=$1 done_weight=$2 elapsed=$3 open_elapsed=$4
  _CB_OPEN_PHASE="$phase"
  _CB_DONE_WEIGHT="$done_weight"
  _CB_OPEN_FRACTION=0
  _CB_START_EPOCH=$(( NOW - elapsed ))
  _CB_OPEN_START=$(( NOW - open_elapsed ))
  _cb_update_eta
  printf 'CASE:%s\\n' "${{_CB_ETA_TEXT}}"
}}

NOW="$(date +%s)"

# preflight (weight 2), no progress logged yet (pct stays 0, well under the
# 5% "estimating..." floor) at 1s / 2s / 3s / 8s open_elapsed. This is the
# exact reproduction: before the fix, 3s and 8s both said "taking longer
# than expected". After the fix, every one of these must stay "estimating...".
emit preflight 0 1 1
emit preflight 0 2 2
emit preflight 0 3 3
emit preflight 0 8 8

# Real progress (pct=10, so the 5%% guard no longer applies), preflight open
# 35s -- projected_total = 40*100/10 = 400s, expected_phase = 400*2/100+1 =
# 9s, so 35s is both > 2x that budget (18s) AND past the 30s absolute floor.
# This MUST say "taking longer than expected".
emit preflight 10 40 35

# Same ratio overrun (open_elapsed=20s > 18s budget*2) but under the 30s
# absolute floor -- must NOT say it. Isolates the floor from the ratio.
emit preflight 10 40 20
"""


def _run_harness() -> list[str]:
    result = subprocess.run(["bash", "-c", HARNESS], capture_output=True, text=True)
    assert result.returncode == 0, (
        f"ETA overrun harness exited {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    lines = [line for line in result.stdout.strip().splitlines() if line.startswith("CASE:")]
    return [line[len("CASE:") :] for line in lines]


def test_early_preflight_never_says_taking_longer_than_expected() -> None:
    """The I4 reproduction: preflight at 1/2/3/8 open-elapsed seconds, no
    phase finished yet. Before the fix, 3s and 8s both regressed to "taking
    longer than expected". All four must now read "estimating..."."""
    cases = _run_harness()
    early = cases[:4]
    assert early == ["estimating..."] * 4, (
        f"preflight at 1/2/3/8s should all show 'estimating...' (pct is still "
        f"under the 5% floor), got: {early}"
    )


def test_genuine_overrun_past_budget_and_floor_does_say_it() -> None:
    """A phase that is both past 2x its projected budget AND past the 30s
    absolute floor must still report the overrun -- the fix must not have
    silenced the message entirely."""
    cases = _run_harness()
    assert cases[4] == "taking longer than expected", (
        f"a phase 35s into a 9s expected budget (with real progress logged) "
        f"should say 'taking longer than expected', got: {cases[4]!r}"
    )


def test_ratio_overrun_under_the_floor_does_not_say_it() -> None:
    """The same relative overrun, but the open phase has only run 20s -- under
    the 30s absolute floor -- must not trip the message. Isolates the floor
    from the ratio check."""
    cases = _run_harness()
    assert cases[5] != "taking longer than expected", (
        f"a phase only 20s into an overrun ratio should be held back by the "
        f"30s absolute floor, got: {cases[5]!r}"
    )
