"""CAP_NET_RAW reaches the services ambiently; the binary carries no file caps.

`setcap cap_net_raw+ep` on /opt/circuitbreaker/bin/circuit-breaker did three
things, none of which was granting a privilege the units did not already have
through systemd's AmbientCapabilities:

1. It made every exec of the binary privilege-gaining, so the kernel marked the
   process non-dumpable and /proc/<pid>/exe became unreadable *to its own user*.
   PyInstaller's --onefile child validates its parent by reading exactly that:

       [PYI-NNNN:ERROR] Security validation failure: could not access /proc
       entry to determine the executable path for originating onefile parent
       process!

   That killed all five circuitbreaker-worker@ units, and made --selftest fail
   for every unprivileged caller — so `cb doctor` and `cb diag bundle` reported
   a healthy install as a binary that cannot load its application.

   Verified on hardware, without this binary: /usr/bin/mtr-packet carries the
   same cap_net_raw=ep, and `readlink /proc/<its pid>/exe` returns EACCES to
   its own user while an uncapped process in the same shell reads fine.

2. Exec'ing a file that carries capabilities CLEARS the ambient set, so the
   AmbientCapabilities systemd had just configured were discarded at exec.
   services/discovery_probes.py::_has_ambient_net_raw() reads CapAmb from
   /proc/self/status and therefore saw nothing. That module's own docstring
   states the rule: "Ambient caps propagate to nmap subprocesses, but file caps
   on the Python binary do not." The file capability was silently defeating the
   mechanism discovery depends on.

3. It left a capability-carrying binary on disk for any local user to exec.

nmap keeps its own file capability — that is what covers an nmap invocation
outside these units, and _nmap_os_capable() falls back to checking it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = ROOT / "deploy" / "systemd"
SETUP = ROOT / "deploy" / "setup.sh"
JOURNEY = ROOT / "scripts" / "ci" / "installer-journey.sh"

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


def test_the_installer_never_grants_file_capabilities_to_the_binary():
    setup = SETUP.read_text(encoding="utf-8")
    granting = [
        line.strip()
        for line in setup.splitlines()
        if "setcap" in line
        and BINARY in line
        and not line.lstrip().startswith("#")
        and "setcap -r" not in line
    ]
    assert not granting, (
        "deploy/setup.sh grants a file capability to the application binary:\n  "
        + "\n  ".join(granting)
        + "\n\nThat makes every exec privilege-gaining — the process becomes "
        "non-dumpable, PyInstaller's onefile child cannot read /proc/<ppid>/exe, "
        "and the ambient set systemd configured is cleared. Grant NET_RAW through "
        "AmbientCapabilities in the units instead."
    )


def test_the_installer_actively_removes_a_stale_file_capability():
    """Upgrades run over installs that were setcap'd, so not-granting is not
    enough — the old capability has to come off."""
    setup = SETUP.read_text(encoding="utf-8")
    assert f"setcap -r {BINARY}" in setup, (
        "deploy/setup.sh must run `setcap -r` on the binary, or an upgrade over "
        "an install from before this change keeps the capability and its workers "
        "stay dead"
    )


def test_nmap_keeps_its_own_file_capability():
    """The one file capability that is correct: it is what lets an nmap run
    outside the units do raw scans, and _nmap_os_capable() checks for it."""
    setup = SETUP.read_text(encoding="utf-8")
    assert "setcap cap_net_raw+eip" in setup and "nmap" in setup, (
        "nmap's file capability was removed along with the binary's; active host "
        "discovery degrades to TCP-connect scans without it"
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
        "with no file capability on the binary, AmbientCapabilities is the only "
        "way these units get raw sockets — and the only form that propagates into "
        "the nmap children discovery spawns:\n  " + "\n  ".join(offenders)
    )


def test_the_workers_and_the_backend_agree_on_the_set():
    """Different sets would mean a worker silently losing a probe capability the
    backend has, which shows up as an empty scan rather than an error."""
    sets: dict[str, list[str]] = {}
    for unit in _units_running_the_binary():
        declared = _AMBIENT.findall(unit.read_text(encoding="utf-8"))
        sets[unit.name] = declared[0].split() if declared else []
    distinct = {tuple(sorted(v)) for v in sets.values()}
    assert len(distinct) == 1, (
        "units running the same binary declare different ambient capabilities: "
        + "; ".join(f"{k}={' '.join(v)}" for k, v in sorted(sets.items()))
    )


def test_the_journey_proves_selftest_works_unprivileged():
    """The symptom operators hit. cb doctor and cb diag bundle both run
    --selftest, and both get run by ordinary users."""
    journey = JOURNEY.read_text(encoding="utf-8")
    # The exact pairing, not its two halves: `runuser -u breaker` already
    # appears in the journey for wait-for-services.sh, and `--selftest` already
    # appears for the privileged run, so checking for either alone passes
    # against the version that had neither of the properties this pins.
    assert re.search(
        r"runuser\s+-u\s+breaker\s+--\s+/opt/circuitbreaker/bin/circuit-breaker\s+--selftest",
        journey,
    ), (
        "the installer journey must run --selftest AS breaker. That is the check "
        "that would have caught the file capability — cb doctor and cb diag "
        "bundle both run it, and both get run by ordinary users."
    )
    # The old assertion demanded the opposite and so enforced the defect.
    assert not re.search(
        r"getcap\s+/opt/circuitbreaker/bin/circuit-breaker\s*\|\s*grep\s+-q\s+'?cap_net_raw",
        journey,
    ), (
        "the journey still requires a file capability on the binary; that is the "
        "assertion that kept the defect in place"
    )
    assert 'BIN_CAPS="$(getcap /opt/circuitbreaker/bin/circuit-breaker' in journey, (
        "the journey must assert the installed binary carries NO file capability"
    )
