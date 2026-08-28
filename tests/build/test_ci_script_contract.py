"""Phase 1 of ADR 0005: the contract every scripts/ci gate script must satisfy.

These are the rules that make `make verify` trustworthy. A gate that can pass
because a tool is missing is not a gate (design P2/R4), and a gate body that
lives in workflow YAML can only ever run in CI (P1).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "scripts" / "ci"
COMMON = CI_DIR / "lib" / "common.sh"


def _bash(snippet: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", snippet], capture_output=True, text=True, cwd=REPO_ROOT
    )


def test_common_lib_exists():
    assert COMMON.is_file(), f"{COMMON} is missing"


def test_require_tool_fails_closed_on_a_missing_tool():
    """P2: 'the scanner was not installed' must never be spelled the same as
    'the scanner found nothing'."""
    result = _bash(
        f'source "{COMMON}"; cb::require_tool definitely-not-a-real-tool-xyz; echo REACHED'
    )
    assert result.returncode == 127, result.stderr
    assert "REACHED" not in result.stdout
    assert "definitely-not-a-real-tool-xyz" in result.stderr


def test_require_tool_passes_for_a_present_tool():
    result = _bash(f'source "{COMMON}"; cb::require_tool bash; echo REACHED')
    assert result.returncode == 0, result.stderr
    assert "REACHED" in result.stdout


def test_skipped_marker_is_unmistakable():
    """R4: an informational step that did not run says so."""
    result = _bash(f'source "{COMMON}"; cb::skipped ESLint "no node_modules"')
    assert result.returncode == 0, result.stderr
    assert "SKIPPED" in result.stdout
    assert "no node_modules" in result.stdout


def test_repo_root_resolves_to_this_repo():
    result = _bash(f'source "{COMMON}"; printf "%s" "$CB_REPO_ROOT"')
    assert Path(result.stdout).resolve() == REPO_ROOT


def test_evidence_dir_creates_flat_layout(tmp_path):
    """cb::evidence_dir must create a flat layout with junit/ and logs/
    subdirectories, matching the structure that ci.yml and dev-ci.yml write."""
    tmp_evidence_root = tmp_path / "evidence"
    result = _bash(
        f'export CB_EVIDENCE_ROOT="{tmp_evidence_root}"; source "{COMMON}"; '
        f'dir=$(cb::evidence_dir); printf "%s" "$dir"'
    )
    assert result.returncode == 0, result.stderr

    # Verify the path ends in "evidence"
    echoed_dir = result.stdout
    assert echoed_dir.endswith("evidence"), f"Expected path to end in 'evidence', got {echoed_dir}"

    # Verify junit/ and logs/ subdirectories exist
    echoed_path = Path(echoed_dir)
    assert (echoed_path / "junit").is_dir(), f"junit/ directory not created at {echoed_path / 'junit'}"
    assert (echoed_path / "logs").is_dir(), f"logs/ directory not created at {echoed_path / 'logs'}"


TIER_SCRIPTS = ["tier0-static.sh", "tier1-unit.sh", "tier3-artifact.sh"]


def test_tier_scripts_exist_and_are_executable():
    for name in TIER_SCRIPTS:
        script = CI_DIR / name
        assert script.is_file(), f"{script} is missing"
        assert script.stat().st_mode & 0o111, f"{script} is not executable"


def test_tier_scripts_use_strict_bash():
    for name in TIER_SCRIPTS:
        text = (CI_DIR / name).read_text(encoding="utf-8")
        assert text.startswith("#!/usr/bin/env bash\n"), name
        assert "set -euo pipefail" in text, name


def test_tier_scripts_do_not_swallow_gate_failures():
    """No `|| true` in a tier script. No exemption, including for diagnostics.

    An earlier version of this test allowed `|| true` on a line annotated
    `# diagnostics:`, so Tier 3's evidence collectors could not abort a run they
    were trying to explain. That was the convenient fix rather than the correct
    one, twice over. It made an absolute rule self-declared -- the next author
    who wants a failing gate to stop failing writes the same six characters --
    and `|| true` still discards the one fact worth keeping: that the collector
    itself failed. An evidence directory missing a journal, with nothing saying
    why, is the same ambiguity as a scanner that did not run reading like a clean
    scan (#106).

    The replacement is a `capture` helper: it never aborts the run and it records
    every failed collection into collection-errors.log. Strictly more information
    than `|| true`, and no hole in the rule.
    """
    for name in TIER_SCRIPTS:
        for lineno, line in enumerate(
            (CI_DIR / name).read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "|| true" not in stripped, (
                f"{name}:{lineno}: `|| true` swallows a failure. For evidence "
                f"collection use the capture helper, which cannot abort the run "
                f"and records what failed:\n    {stripped}"
            )


def test_tier3_records_failed_evidence_collection_rather_than_hiding_it():
    """P2/R4: a collector that failed must not look like one that found nothing."""
    text = (CI_DIR / "tier3-artifact.sh").read_text(encoding="utf-8")
    assert "capture()" in text, "tier3 must define the capture helper"
    assert "collection-errors.log" in text, (
        "a failed collection must be recorded, not discarded"
    )


# (gate name, substring that must appear in tier0-static.sh, why its absence
# is a silent gate loss rather than a cosmetic diff). The contract suite locks
# the script's *shape* (strict bash, no `|| true`, executable) but, before
# this test, nothing locked its *contents* — deleting a gate from the middle
# of the file still passed every other test in this suite, because a step
# that no longer exists as a named GitHub Actions step is just a missing line
# in one file rather than a missing item in the job UI.
TIER0_LOAD_BEARING_GATES = [
    (
        "Alembic single-head check",
        "len(heads) == 1",
        "a forked/diverged migration history would go undetected",
    ),
    (
        "repo-policy suite",
        "pytest tests/build",
        "GOV/SRV policy tests (tracked-file policy, CLI parity, restart probes, "
        "release channel, etc.) would no longer run anywhere",
    ),
    (
        "Ruff",
        "bin/ruff\" check src/app",
        "backend lint violations would no longer fail the gate",
    ),
    (
        "Mypy",
        "bin/mypy\" src/app",
        "backend type errors would no longer fail the gate",
    ),
    (
        "release-control ledger validator",
        "validate_v1_release_control.py",
        "the 1.0.0 requirement ledger could drift from the specs unnoticed",
    ),
    (
        "ESLint",
        "npm run lint",
        "frontend lint violations would no longer fail the gate",
    ),
]


def test_tier0_static_still_contains_its_six_gates():
    """Before this test, deleting the release-control ledger check, the
    Alembic check, `pytest tests/build`, or `npm run lint` from
    tier0-static.sh passed the whole test_ci_script_contract.py suite and
    silently stopped a gate running — the exact failure mode P1/P2 exist to
    prevent, just moved from workflow YAML into a shell script."""
    text = (CI_DIR / "tier0-static.sh").read_text(encoding="utf-8")
    for gate_name, needle, consequence in TIER0_LOAD_BEARING_GATES:
        assert needle in text, (
            f"tier0-static.sh no longer invokes the '{gate_name}' gate "
            f"(expected to find {needle!r}); {consequence}"
        )


@pytest.mark.parametrize("workflow_name", ["dev-ci.yml", "ci.yml"])
def test_workflow_calls_the_tier0_script_rather_than_inlining_it(workflow_name):
    """P1: a gate defined in YAML can only ever run in CI.

    Both workflows are checked, not just dev-ci.yml: ci.yml gates main and
    dev-ci.yml gates dev, and this repo's own history (the pre-migration
    ci.yml lint job) is a case of exactly one of the two being migrated while
    the other silently kept an inlined, hand-copied twin.
    """
    workflow = (REPO_ROOT / ".github/workflows" / workflow_name).read_text(encoding="utf-8")
    assert "scripts/ci/tier0-static.sh" in workflow
    assert "ruff check src/app" not in workflow, (
        "ruff is a tier-0 gate; its command belongs in tier0-static.sh, not in the workflow"
    )
    assert "mypy src/app" not in workflow, (
        "mypy is a tier-0 gate; its command belongs in tier0-static.sh, not in the workflow"
    )


def test_pre_push_hook_runs_the_full_gate():
    """The hook existed and ran `make lint` — a fraction of the gate. ADR 0005
    makes the pre-push slot the T0+T1 gate."""
    hook = (REPO_ROOT / ".husky" / "pre-push").read_text(encoding="utf-8")
    assert "make verify" in hook, hook


def test_use_go_bin_adds_the_go_install_prefix_to_path(tmp_path):
    """`go install` writes to `go env GOBIN`, or `go env GOPATH`/bin when GOBIN
    is unset. Neither is on PATH by default, so a gate that asks
    `command -v govulncheck` without resolving this first rejects a correct
    install and tells the developer to redo it — which changes nothing."""
    gopath = tmp_path / "gopath"
    (gopath / "bin").mkdir(parents=True)
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    go = stub_dir / "go"
    go.write_text(
        "#!/usr/bin/env bash\n"
        'case "$1 $2" in\n'
        '  "env GOBIN") echo "" ;;\n'
        f'  "env GOPATH") echo "{gopath}" ;;\n'
        "esac\n"
    )
    go.chmod(0o755)
    result = _bash(
        f'export PATH="{stub_dir}:$PATH"; source "{COMMON}"; '
        'cb::use_go_bin; printf "%s" "$PATH"'
    )
    assert result.returncode == 0, result.stderr
    assert str(gopath / "bin") in result.stdout


def test_use_go_bin_prefers_an_explicit_gobin(tmp_path):
    gobin = tmp_path / "explicit"
    gobin.mkdir()
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    go = stub_dir / "go"
    go.write_text(
        "#!/usr/bin/env bash\n"
        'case "$1 $2" in\n'
        f'  "env GOBIN") echo "{gobin}" ;;\n'
        '  "env GOPATH") echo "/nonexistent" ;;\n'
        "esac\n"
    )
    go.chmod(0o755)
    result = _bash(
        f'export PATH="{stub_dir}:$PATH"; source "{COMMON}"; '
        'cb::use_go_bin; printf "%s" "$PATH"'
    )
    assert result.returncode == 0, result.stderr
    assert str(gobin) in result.stdout
    assert "/nonexistent" not in result.stdout


def test_use_go_bin_is_a_no_op_without_a_go_toolchain():
    """No toolchain, nothing to resolve — and it must not abort the caller, so
    that `cb::require_tool go` is what reports the real problem."""
    result = _bash(f'PATH=""; source "{COMMON}"; cb::use_go_bin; echo REACHED')
    assert result.returncode == 0, result.stderr
    assert "REACHED" in result.stdout


def test_tier1_resolves_go_binaries_before_demanding_them():
    """The govulncheck preflight guards section 10 of security_scan.sh, which
    bootstraps govulncheck itself when `go` is present. A preflight stricter
    than the gate it guards blocks `make verify` on a working install."""
    text = (CI_DIR / "tier1-unit.sh").read_text(encoding="utf-8")
    assert "cb::use_go_bin" in text, "tier1 must resolve the Go install prefix"
    assert text.index("cb::use_go_bin") < text.index("cb::require_tool govulncheck"), (
        "cb::use_go_bin must run before anything asks whether govulncheck exists"
    )


def test_tier1_requires_the_go_toolchain_itself():
    """govulncheck shells out to `go list` at runtime: without `go` on PATH it
    fails with the misleading `no go.mod file` rather than naming the real
    cause. `go` is the actual precondition, so the gate states it."""
    text = (CI_DIR / "tier1-unit.sh").read_text(encoding="utf-8")
    assert "cb::require_tool go " in text


def test_tier3_is_self_contained_because_it_runs_in_a_guest():
    """tier0 and tier1 source lib/common.sh; tier3 cannot.

    It executes inside an ephemeral VM where this repository does not exist --
    only the script and the candidate package are copied in. Sourcing the shared
    library would fail at runtime, in the guest, several minutes into a slow
    tier. That constraint is also what keeps it identical across every matrix row
    (P1): a script with no repo to reach into cannot grow distro-specific
    branches by accident.
    """
    text = (CI_DIR / "tier3-artifact.sh").read_text(encoding="utf-8")
    assert "lib/common.sh" not in text, (
        "tier3-artifact.sh runs in a guest without the repo; it must not source "
        "the shared library"
    )
    assert "cb::" not in text, "the cb:: helpers are not available in the guest"


def test_tier3_waits_for_readyz_not_just_livez():
    """The whole point of this tier (design section 11) is that the service
    *starts*. /livez only proves the process is alive; a package that installs,
    launches and can never reach its database passes a liveness check and fails
    every user."""
    text = (CI_DIR / "tier3-artifact.sh").read_text(encoding="utf-8")
    assert "/livez" in text
    assert "/readyz" in text


def test_tier3_leaves_its_evidence_readable_to_the_collector():
    """Evidence written as root must be fetchable by the unprivileged collector.

    tier3-artifact.sh runs under sudo in the guest; dispatch.sh collects over scp
    as the `fedora` user. The first real run copied /etc/circuit-breaker's env
    file into the evidence directory, and `cp` as root reproduces its 0600 mode --
    so scp hit one unreadable file, returned non-zero, and the whole collection
    was reported as failed even though most of it had transferred. P7 says the
    tier fails when evidence is empty; it should not be one chmod away from
    reporting that falsely.
    """
    text = (CI_DIR / "tier3-artifact.sh").read_text(encoding="utf-8")
    assert "chmod -R a+rX" in text, (
        "tier3 must make its evidence world-readable so the collector can fetch "
        "it; files copied from 0600 sources are otherwise root-only"
    )
