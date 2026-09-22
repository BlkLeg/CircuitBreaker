"""No two units may declare the same RuntimeDirectory, and every enabled worker
must be asserted running.

systemd does not refcount RuntimeDirectory across units. It creates the
directory when a unit starts and removes it when that unit stops — even if
other units declaring the same directory are still running. Verified directly
rather than read off the documentation: two units declaring
RuntimeDirectory=cbtest, start both, stop one, and the directory is gone while
the other is still active.

circuitbreaker-backend.service, circuitbreaker-worker@.service and
cb-helperd.service all declared RuntimeDirectory=circuitbreaker. That directory
holds the vault key the backend reads at every start and the socket
cb-helperd binds for helper_client.py, so any one worker exiting deleted both
out from under the other two. They also declared *different* modes — 0750
breaker for the backend and workers, 0755 root for the helper — so the owner
and mode of a shared directory depended on which unit happened to start first.
A root-owned 0755 directory silently fails the backend's vault.env write, which
`|| true` and `EnvironmentFile=-` both swallow.

/usr/lib/tmpfiles.d/circuitbreaker.conf owns it now. These tests keep it that
way, and keep the journey honest about workers: with the directory fixed, Arch
would otherwise have gone green with all five workers dead, because nothing in
the journey looked at them.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = ROOT / "deploy" / "systemd"
SETUP = ROOT / "deploy" / "setup.sh"
JOURNEY = ROOT / "scripts" / "ci" / "installer-journey.sh"
TMPFILES = ROOT / "deploy" / "misc" / "circuitbreaker.tmpfiles.conf"
UNINSTALL = ROOT / "uninstall.sh"

_RUNTIME_DIR = re.compile(r"^RuntimeDirectory=(.+)$", re.MULTILINE)


def _declared_runtime_dirs() -> dict[str, list[str]]:
    """directory -> the units declaring it."""
    owners: dict[str, list[str]] = defaultdict(list)
    for unit in sorted(p for p in UNITS_DIR.iterdir() if p.is_file()):
        for match in _RUNTIME_DIR.finditer(unit.read_text(encoding="utf-8")):
            # RuntimeDirectory= takes a space-separated list.
            for directory in match.group(1).split():
                owners[directory].append(unit.name)
    return owners


def test_no_runtime_directory_is_declared_by_more_than_one_unit():
    shared = {d: units for d, units in _declared_runtime_dirs().items() if len(units) > 1}
    assert not shared, (
        "systemd removes a RuntimeDirectory when ANY declaring unit stops, even "
        "while the others run — so these units delete each other's runtime state:\n  "
        + "\n  ".join(f"/run/{d}: {', '.join(units)}" for d, units in sorted(shared.items()))
        + "\n\nGive each unit its own directory, or create the shared one from "
        "deploy/misc/circuitbreaker.tmpfiles.conf and declare it in none of them."
    )


def test_the_shared_runtime_directory_is_owned_by_tmpfiles():
    assert TMPFILES.is_file(), f"{TMPFILES} is missing"
    body = [
        line
        for line in TMPFILES.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert body == ["d /run/circuitbreaker 0750 breaker breaker -"], (
        "the tmpfiles entry must create /run/circuitbreaker as breaker:breaker "
        f"0750 — the mode the backend's ExecStartPre needs to write vault.env; got {body}"
    )
    setup = SETUP.read_text(encoding="utf-8")
    assert "circuitbreaker.tmpfiles.conf" in setup, "deploy/setup.sh never installs the tmpfiles entry"
    assert "/usr/lib/tmpfiles.d/circuitbreaker.conf" in UNINSTALL.read_text(encoding="utf-8"), (
        "uninstall.sh must remove the tmpfiles entry, or an uninstalled product "
        "keeps recreating /run/circuitbreaker at every boot"
    )


def test_none_of_the_three_sharing_units_declares_it_again():
    for name in (
        "circuitbreaker-backend.service",
        "circuitbreaker-worker@.service",
        "cb-helperd.service",
    ):
        text = (UNITS_DIR / name).read_text(encoding="utf-8")
        assert "RuntimeDirectory=circuitbreaker\n" not in text, (
            f"{name} declares RuntimeDirectory=circuitbreaker again; stopping it "
            "would delete the other two units' runtime state"
        )


def _enabled_workers() -> set[str]:
    """Worker instances deploy/setup.sh enables.

    setup.sh builds the enable and start lists from the single `CB_WORKER_TYPES`
    array (see `tests/build/test_worker_set_matches_runtime.py`, which pins
    that array to `app.workers.main.WORKER_MODULES`), rather than repeating the
    worker names as quoted literals at each call site — the shape that let
    `integration` and `monitor_probe_dispatch` go unenabled on every native
    install despite being enabled everywhere else.
    """
    text = SETUP.read_text(encoding="utf-8")
    block = re.search(r"CB_WORKER_TYPES=\((.*?)\)", text, re.DOTALL)
    assert block, "deploy/setup.sh no longer defines CB_WORKER_TYPES"
    return {f"circuitbreaker-worker@{name}" for name in block.group(1).split()}


def _asserted_workers() -> set[str]:
    text = JOURNEY.read_text(encoding="utf-8")
    block = re.search(r"CB_WORKER_UNITS=\((.*?)\)", text, re.DOTALL)
    assert block, "installer-journey.sh no longer defines CB_WORKER_UNITS"
    return set(re.findall(r"circuitbreaker-worker@[a-z_]+", block.group(1)))


def test_the_journey_asserts_every_worker_the_installer_enables():
    """A worker nothing checks is a worker that can die silently — the API stays
    healthy with the whole background tier dead."""
    enabled, asserted = _enabled_workers(), _asserted_workers()
    assert enabled, "found no worker instances enabled in deploy/setup.sh; did the call shape change?"
    assert enabled == asserted, (
        "the installer journey and deploy/setup.sh disagree about the workers.\n"
        f"  enabled but never asserted running: {sorted(enabled - asserted) or 'none'}\n"
        f"  asserted but never enabled:         {sorted(asserted - enabled) or 'none'}"
    )


def test_the_journey_checks_workers_are_active_not_merely_enabled():
    text = JOURNEY.read_text(encoding="utf-8")
    assert re.search(r'is-active --quiet "\$unit".*\n?.*CB_WORKER_UNITS|CB_WORKER_UNITS.*?is-active', text, re.DOTALL), (
        "the journey must assert the workers are running; `enabled` is what they "
        "already were on Arch while all five were dead"
    )
