"""REL-20: runs are deterministic, and their evidence survives the run.

The acceptance criterion is blunt — "any failed release job is diagnosable from
retained artifacts alone" — and it has one failure mode: the evidence exists
while the job is running and is gone by the time anyone looks. Two habits cause
it. An upload step without ``if: always()`` runs only when the job succeeded,
which is exactly backwards; and ``actions/upload-artifact`` skips dotfiles by
default, so a coverage data file named ``.coverage.backend-3`` uploads as an
empty directory unless ``include-hidden-files`` is set.

Determinism is checked alongside it because retained evidence from a run that
cannot be repeated is a description, not a reproduction. The seeds are pinned
in the workflow ``env`` and copied into a per-job run manifest; the backend
shard assignment comes from ``tests/build/backend_shard.py``, whose count the
GitHub matrix has to repeat as a literal — a matrix cannot be computed at
runtime — so the two are held together here.

What is deliberately not asserted: which jobs exist, how many steps they have,
or the exact artifact names. Those change. What must not change is that a job
which runs tests keeps its results, its logs, its coverage, its seed and its
container state whether it passed or failed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github/workflows"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.build.backend_shard import CI_SHARD_TOTAL  # noqa: E402

# The workflows that run test suites. security.yml, codeql.yml, docs.yml and
# pages.yml are scanners and publishers, not test runners, and are covered by
# their own gates.
TEST_WORKFLOWS = ("ci.yml", "dev-ci.yml")

# Jobs that execute a suite, and therefore owe evidence. Keyed by workflow so a
# job renamed in one file cannot silently drop the requirement in the other.
EVIDENCE_OWING_JOBS = {
    "ci.yml": ("lint", "backend-tests", "fresh-install-migrations", "test", "browser-e2e"),
    "dev-ci.yml": ("lint", "backend-tests", "fresh-install-migrations", "test"),
}


def _load(name: str) -> dict:
    yaml = pytest.importorskip(
        "yaml", reason="PyYAML parses the workflow files; it arrives with the backend dev extra"
    )
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _uploads(job: dict) -> list[dict]:
    return [
        step
        for step in job.get("steps") or []
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    ]


def _retained_paths(workflow: dict) -> str:
    return "\n".join(
        str(step.get("with", {}).get("path", ""))
        for job in workflow["jobs"].values()
        for step in _uploads(job)
    )


# ── determinism ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", TEST_WORKFLOWS)
def test_the_seeds_are_pinned_at_the_workflow_level(name: str):
    """PYTHONHASHSEED unset means CPython salts str hashing per process, so two
    runs of the same commit can order things differently for no visible reason.
    Pinning it at the workflow level rather than per job is what stops a new
    job from being added without it."""
    env = _load(name).get("env") or {}
    assert str(env.get("PYTHONHASHSEED", "")) == "0", (
        f"{name} does not pin PYTHONHASHSEED; test ordering and any "
        f"set-of-strings iteration become run-dependent"
    )
    assert env.get("CB_TEST_SEED"), f"{name} declares no CB_TEST_SEED"


@pytest.mark.parametrize("name", TEST_WORKFLOWS)
def test_the_seed_is_fixed_rather_than_derived_from_the_run(name: str):
    """A seed that changes every run is recorded, not fixed. Recording it makes
    a failure reproducible only for whoever reads that run's log; fixing it
    makes two runs of the same commit comparable, which is what REL-20 asks
    for. `${{ github.run_id }}` is the specific mistake this catches."""
    seed = str((_load(name).get("env") or {}).get("CB_TEST_SEED", ""))
    assert "${{" not in seed, f"{name}: CB_TEST_SEED={seed!r} is derived per run, not fixed"


def test_the_composed_journey_seed_is_fixed_too():
    workflow = _load("e2e.yml")
    seeds = [
        str(value)
        for job in workflow["jobs"].values()
        for step in job.get("steps") or []
        for key, value in (step.get("env") or {}).items()
        if key == "CB_E2E_SEED"
    ]
    assert seeds, "e2e.yml sets no CB_E2E_SEED"
    assert all("${{" not in seed for seed in seeds), (
        f"e2e.yml derives CB_E2E_SEED per run: {seeds}"
    )


@pytest.mark.parametrize("name", TEST_WORKFLOWS)
def test_the_backend_matrix_matches_the_shard_module(name: str):
    """A GitHub matrix cannot be computed at runtime, so the count is written
    twice. This is the join: a shard added to the matrix without teaching
    backend_shard.py about it would run a quarter of the suite twice and skip
    another quarter entirely."""
    job = _load(name)["jobs"]["backend-tests"]
    shards = job["strategy"]["matrix"]["shard"]
    assert shards == list(range(1, CI_SHARD_TOTAL + 1)), (
        f"{name}: backend matrix is {shards}, but backend_shard.CI_SHARD_TOTAL "
        f"is {CI_SHARD_TOTAL}. Change both, or the split stops being a partition."
    )
    assert job["strategy"].get("fail-fast") is False, (
        f"{name}: a red backend shard would cancel its siblings and destroy the "
        f"evidence needed to tell a shard-local failure from a suite-wide one"
    )


@pytest.mark.parametrize("name", TEST_WORKFLOWS)
def test_the_shard_selection_comes_from_the_tested_module(name: str):
    """Not from an inline snippet. The assignment has properties worth testing
    — exact partition, stability under a different hash seed — and an inline
    copy in YAML has none of them tested."""
    steps = "".join(
        str(step.get("run", "")) for step in _load(name)["jobs"]["backend-tests"]["steps"]
    )
    assert "tests/build/backend_shard.py" in steps, (
        f"{name}: the backend shard is selected by something other than the "
        f"module tests/build/test_backend_shard.py holds to its invariants"
    )


# ── retention ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", TEST_WORKFLOWS)
def test_every_test_job_retains_something_on_failure(name: str):
    workflow = _load(name)
    missing = []
    for job_name in EVIDENCE_OWING_JOBS[name]:
        assert job_name in workflow["jobs"], f"{name} has no job {job_name!r}"
        always = [
            step
            for step in _uploads(workflow["jobs"][job_name])
            if str(step.get("if", "")).strip() in {"always()", "${{ always() }}"}
        ]
        if not always:
            missing.append(job_name)
    assert not missing, (
        f"{name}: {missing} upload no artifact with `if: always()`. An upload "
        f"without it runs only when the job passed, which keeps evidence "
        f"exactly when it is not needed."
    )


@pytest.mark.parametrize("name", TEST_WORKFLOWS)
def test_the_coverage_data_files_are_not_dropped_as_dotfiles(name: str):
    """actions/upload-artifact excludes hidden files by default, and coverage's
    data file is `.coverage.backend-N`. Without include-hidden-files the
    combine job downloads empty directories and the ratchet measures nothing —
    a green gate over no data, which is worse than a red one."""
    job = _load(name)["jobs"]["backend-tests"]
    uploads = _uploads(job)
    assert uploads, f"{name}: backend-tests uploads nothing"
    hidden_ok = [
        step for step in uploads if step.get("with", {}).get("include-hidden-files") is True
    ]
    assert hidden_ok, (
        f"{name}: no backend-tests upload sets include-hidden-files, so the "
        f"coverage data files would be silently dropped"
    )


def test_every_named_artifact_class_is_retained_somewhere():
    """REL-20 names them: JUnit, coverage, logs, traces, screenshots, seeds and
    container diagnostics. Traces, screenshots and video are what
    playwright.config.ts writes into test-results/ on failure, so retaining
    that directory is how those three are kept; the seed is in the run
    manifest each job writes."""
    retained = _retained_paths(_load("ci.yml")) + _retained_paths(_load("e2e.yml"))
    steps = "\n".join(
        str(step.get("run", ""))
        for workflow in ("ci.yml", "e2e.yml")
        for job in _load(workflow)["jobs"].values()
        for step in job.get("steps") or []
    )
    haystack = retained + "\n" + steps
    for artifact_class, needle in (
        ("JUnit", "junit"),
        ("coverage", "coverage"),
        ("logs", "logs/"),
        ("traces/screenshots/video", "test-results/"),
        ("seeds", "run-manifest"),
        ("container diagnostics", "diagnostics"),
    ):
        assert needle in haystack, (
            f"no workflow step or retained path mentions {needle!r}, so the "
            f"{artifact_class} artifact class is not retained"
        )


@pytest.mark.parametrize("name", TEST_WORKFLOWS)
def test_retention_is_long_enough_to_be_useful(name: str):
    """A one-day retention on test evidence expires before most reviews start.

    Scoped to the jobs that owe evidence. Short retention is right elsewhere
    and is left alone: dev-ci's `build-native` keeps throwaway dev packages for
    three days, and release.yml's per-architecture image digest lives for one —
    it is consumed by the very next job and is meaningless afterwards.
    """
    workflow = _load(name)
    short = []
    for job_name in (*EVIDENCE_OWING_JOBS[name], "backend-coverage"):
        for step in _uploads(workflow["jobs"][job_name]):
            days = step.get("with", {}).get("retention-days")
            if days is not None and int(days) < 7:
                short.append(f"{job_name}/{step.get('name')}={days}d")
    assert not short, f"{name}: test evidence expires too soon: {short}"
