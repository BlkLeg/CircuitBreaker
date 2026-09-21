"""Every unit that runs the setcap'd binary must declare AmbientCapabilities.

/opt/circuitbreaker/bin/circuit-breaker carries cap_net_raw=ep, applied by
stage6_apply_binary. Exec'ing a file whose capabilities are not already in the
process's permitted set is a privilege-gaining exec: the kernel marks the
process non-dumpable, and /proc/<pid>/exe becomes unreadable even to the user
running it.

PyInstaller's --onefile child validates its parent by reading exactly that
path, so it dies at startup:

    [PYI-NNNN:ERROR] Security validation failure: could not access /proc entry
    to determine the executable path for originating onefile parent process!

Verified on real hardware, independently of this binary: /usr/bin/mtr-packet
carries the same cap_net_raw=ep, and `readlink /proc/<its pid>/exe` returns
EACCES to its own user while an uncapped process in the same shell reads fine.

circuitbreaker-backend.service always declared AmbientCapabilities, which puts
CAP_NET_RAW in the permitted set *before* the exec, so the exec grants nothing
new and the process stays dumpable. circuitbreaker-worker@.service did not — so
all five workers exited at startup while /readyz, migrations and bootstrap all
passed, because nothing foreground depends on them.

This test pins the pairing: a unit that execs the capability-carrying binary
declares the capabilities, or it cannot start.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = ROOT / "deploy" / "systemd"
SETUP = ROOT / "deploy" / "setup.sh"

BINARY = "/opt/circuitbreaker/bin/circuit-breaker"

_EXEC_START = re.compile(r"^ExecStart=(\S+)", re.MULTILINE)
_AMBIENT = re.compile(r"^AmbientCapabilities=(.+)$", re.MULTILINE)


def _units_running_the_binary() -> list[Path]:
    units = [
        unit
        for unit in sorted(p for p in UNITS_DIR.iterdir() if p.is_file())
        if any(cmd == BINARY for cmd in _EXEC_START.findall(unit.read_text(encoding="utf-8")))
    ]
    assert units, f"no unit ExecStarts {BINARY}; did the path change?"
    return units


def test_the_binary_still_carries_file_capabilities():
    """The premise. If setcap is ever dropped, this test's whole class of
    failure goes away and the requirement below can be revisited."""
    setup = SETUP.read_text(encoding="utf-8")
    assert f"setcap cap_net_raw+ep {BINARY}" in setup, (
        "deploy/setup.sh no longer applies cap_net_raw to the binary. If that was "
        "deliberate, the AmbientCapabilities requirement below exists only for the "
        "raw sockets themselves — re-read this test before relaxing it."
    )


def test_every_unit_running_the_binary_declares_ambient_capabilities():
    offenders: list[str] = []
    for unit in _units_running_the_binary():
        declared = _AMBIENT.findall(unit.read_text(encoding="utf-8"))
        if not declared:
            offenders.append(f"{unit.name}: no AmbientCapabilities")
        elif "CAP_NET_RAW" not in declared[0]:
            offenders.append(f"{unit.name}: AmbientCapabilities={declared[0]} lacks CAP_NET_RAW")

    assert not offenders, (
        "these units exec a binary carrying cap_net_raw=ep without already holding "
        "CAP_NET_RAW, which makes the exec privilege-gaining, the process "
        "non-dumpable and /proc/<pid>/exe unreadable — so PyInstaller's onefile "
        "child cannot validate its parent and the unit dies at startup:\n  "
        + "\n  ".join(offenders)
    )


def test_the_workers_and_the_backend_agree_on_the_set():
    """Different sets would mean a worker silently losing a probe capability the
    backend has, which shows up as an empty scan rather than an error."""
    sets = {}
    for unit in _units_running_the_binary():
        declared = _AMBIENT.findall(unit.read_text(encoding="utf-8"))
        # Absence is the test above's failure, not this one's; recorded rather
        # than raised so a missing line does not mask the comparison.
        sets[unit.name] = declared[0].split() if declared else []
    distinct = {tuple(sorted(v)) for v in sets.values()}
    assert len(distinct) == 1, (
        "units running the same binary declare different ambient capabilities: "
        + "; ".join(f"{k}={' '.join(v)}" for k, v in sorted(sets.items()))
    )
