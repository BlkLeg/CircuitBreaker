# tests/build/test_fleet_dispatch_contract.py
"""Collect before destroy, destroy always, and fail on empty evidence.

P7 in the design is a direct response to a real artifact: the composed-E2E
diagnostics upload contained a `docker ps` header and nothing else, and nobody
noticed because an empty evidence directory is indistinguishable from a passing
run that had nothing to say. So the tier fails when its evidence is empty.

The destroy ordering is the other half. A trap that destroys the VM on failure is
the obvious way to guarantee cleanup and the fastest way to throw away every
diagnostic that would have explained the failure.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DISPATCH = REPO_ROOT / "scripts" / "ci" / "fleet" / "dispatch.sh"


def test_dispatch_exists_and_is_executable():
    assert DISPATCH.is_file(), f"{DISPATCH} is missing"
    assert DISPATCH.stat().st_mode & 0o111


def test_dispatch_destroys_on_every_exit_path():
    text = DISPATCH.read_text(encoding="utf-8")
    assert "trap " in text, "destroy must run from a trap, not only on the happy path"
    assert "EXIT" in text


def test_dispatch_collects_before_it_destroys():
    """Ordering is the whole point: a trap that destroys first is a trap that
    guarantees you cannot debug the failure it just cleaned up after."""
    text = DISPATCH.read_text(encoding="utf-8")
    collect = text.index("fleet::collect")
    destroy = text.index("fleet::destroy")
    assert collect < destroy, (
        "fleet::collect must be defined and invoked before fleet::destroy in the "
        "cleanup path"
    )


def test_dispatch_fails_when_evidence_is_empty():
    text = DISPATCH.read_text(encoding="utf-8")
    assert "evidence" in text.lower()
    assert "empty" in text.lower(), (
        "P7: an empty evidence directory must fail the tier, not pass quietly"
    )


def test_dispatch_writes_evidence_to_the_flat_layout():
    """artifacts/diagnostics/tier3-<row>/, not artifacts/tier3/<row>/. Section 4
    records why the per-tier subtree was corrected before implementation."""
    text = DISPATCH.read_text(encoding="utf-8")
    # The root comes from cb::evidence_dir (which is artifacts/), so what this
    # script decides -- and what must be checked -- is the part below it.
    assert "diagnostics/tier3-" in text
    assert "artifacts/tier3/" not in text

FLEET_SCRIPTS = ["provision.sh", "dispatch.sh"]


def test_fleet_scripts_record_failures_rather_than_swallowing_them():
    """The same rule the tier scripts carry, for the same reason.

    `|| true` in a collector or a teardown is how a leaked VM, an evidence copy
    that never happened, or a kill that failed becomes invisible. dispatch.sh in
    particular destroys VMs and copies evidence -- the two operations whose
    silent failure costs the most, since one leaks a machine and the other
    deletes the account of a failure. cb::skipped exists for the informational
    case and says so out loud.
    """
    fleet_dir = REPO_ROOT / "scripts" / "ci" / "fleet"
    for name in FLEET_SCRIPTS:
        for lineno, line in enumerate(
            (fleet_dir / name).read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "|| true" not in stripped, (
                f"{name}:{lineno}: `|| true` hides a failure in teardown or "
                f"collection. Use an explicit branch, or cb::skipped for the "
                f"informational case:\n    {stripped}"
            )
