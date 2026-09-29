"""A `scripts/ci/*.py` script a job runs without `actions/setup-python` must
run on that job's runner Python, not the dev venv's.

quarantine-notice (composed-e2e.yml) shipped `datetime.UTC` — added in Python
3.11 — and failed on its first real execution: the job has no
`actions/setup-python` step, so it runs ubuntu-22.04's system `python3`,
which is 3.10. `make verify`/`make verify-full` never caught it because the
dev venv is 3.12. This is that guard, generalised: it is about the class of
mistake, not just `datetime.UTC`, which is why the forbidden set below also
carries a 3.11 and two 3.12 names nothing in this tree currently uses.

The rule, mechanically: for every job in every `.github/workflows/*.yml` file
that has no `actions/setup-python` step, every `scripts/ci/*.py` script its
`run:` blocks invoke must not import or reference a stdlib name newer than
the runner baseline (Python 3.10 — what `ubuntu-22.04` ships as `python3`).

The rule is checked twice, on purpose:

  * `FORBIDDEN_STDLIB_SYMBOLS` below is a stdlib-only `ast` scan. It needs no
    tooling, so it cannot fail open, but it only knows the names it is seeded
    with — and a list of "names newer than 3.10" that a human maintains is a
    list that goes stale.
  * `vermin` computes the minimum Python version a source file actually
    requires, across every version-gated name it knows. That is the check that
    stays complete without anyone maintaining it. It is a declared dev
    dependency and this module fails rather than skips when it is absent,
    because a gate that passes because its tool is missing is not a gate
    (ADR 0005, P2).

Neither subsumes the other: the `ast` scan survives a broken environment, and
vermin survives a maintainer forgetting to add a name.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
CI_SCRIPTS_DIR = REPO_ROOT / "scripts" / "ci"

# Baseline: Python 3.10, because that is the system `python3` on the
# `ubuntu-22.04` runner label this repo's workflows use, and nothing here
# arranges for a job without `actions/setup-python` to get anything newer.
#
# Seeded with the name that actually broke (datetime.UTC, 3.11) plus three
# more recent-stdlib names that nothing in this tree uses today. Their job is
# to keep this a rule about "stdlib name newer than the runner", not a
# one-entry list that only remembers this incident.
FORBIDDEN_STDLIB_SYMBOLS: dict[str, dict[str, str]] = {
    "datetime": {"UTC": "3.11"},
    "asyncio": {"TaskGroup": "3.11"},
    "typing": {"override": "3.12"},
    "itertools": {"batched": "3.12"},
}

# Matches a `scripts/ci/*.py` path invoked by a `python`/`python3` call inside
# a `run:` block — not a bare mention of the path in a comment or a `paths:`
# trigger filter, which `_scripts_invoked_by` never looks at in the first
# place since it only reads `steps[].run` text.
_SCRIPT_INVOCATION = re.compile(
    r"\bpython3?\b(?:\s+-\S+)*\s+([\w./-]*scripts/ci/[\w./-]+\.py)"
)


def _workflow_jobs() -> dict[str, dict[str, object]]:
    """Every `.github/workflows/*.yml` file's `jobs:` mapping, keyed by filename.

    A file with no `jobs:` (there is none today, but a malformed or empty
    workflow should not crash the scan) contributes an empty mapping.
    """
    yaml = pytest.importorskip(
        "yaml", reason="PyYAML parses the workflow files; it arrives with the backend dev extra"
    )
    jobs_by_file: dict[str, dict[str, object]] = {}
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        jobs = document.get("jobs")
        jobs_by_file[path.name] = jobs if isinstance(jobs, dict) else {}
    return jobs_by_file


def _has_setup_python(job: dict[str, object]) -> bool:
    """Whether any step of *job* is `actions/setup-python` (any pinned version)."""
    steps = job.get("steps") if isinstance(job, dict) else None
    if not isinstance(steps, list):
        return False
    for step in steps:
        if not isinstance(step, dict):
            continue
        uses = step.get("uses")
        if isinstance(uses, str) and uses.startswith("actions/setup-python"):
            return True
    return False


def _scripts_invoked_by(job: dict[str, object]) -> set[str]:
    """Every `scripts/ci/*.py` path a `run:` step of *job* invokes with python."""
    steps = job.get("steps") if isinstance(job, dict) else None
    if not isinstance(steps, list):
        return set()
    found: set[str] = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        run = step.get("run")
        if not isinstance(run, str):
            continue
        for match in _SCRIPT_INVOCATION.finditer(run):
            found.add(match.group(1))
    return found


def jobs_running_ci_scripts_without_setup_python() -> list[tuple[str, str, str]]:
    """(workflow file, job id, `scripts/ci/*.py` path) for every job that
    invokes a `scripts/ci/*.py` script and has no `actions/setup-python` step."""
    findings: list[tuple[str, str, str]] = []
    for filename, jobs in _workflow_jobs().items():
        for job_id, job in jobs.items():
            if not isinstance(job, dict) or _has_setup_python(job):
                continue
            for script in sorted(_scripts_invoked_by(job)):
                findings.append((filename, job_id, script))
    return sorted(findings)


def forbidden_symbols_used(path: Path) -> list[tuple[int, str, str]]:
    """`(lineno, "module.name", added_in)` for every forbidden stdlib symbol
    *path* imports or references.

    Two shapes are caught: `from datetime import UTC` (an `ImportFrom`), and
    `import datetime` followed by `datetime.UTC` (an `Import` binding a local
    name to the module, then an `Attribute` access through that name —
    including `import datetime as dt; dt.UTC`). A plain `datetime.timezone.utc`
    is not flagged: `timezone` and `utc` are not in the forbidden set for the
    `datetime` module, only `UTC` is.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    # Pass 1: which local names are bound to a forbidden-set module, via a
    # plain `import`. Done as its own pass because `ast.walk` is
    # breadth-first (see tests/build/_ast_helpers.py), so a usage nested
    # inside a function could otherwise be visited before the top-level
    # `import` statement that names it.
    module_local_names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_STDLIB_SYMBOLS:
                    module_local_names[alias.asname or alias.name] = alias.name

    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_STDLIB_SYMBOLS:
            symbols = FORBIDDEN_STDLIB_SYMBOLS[node.module]
            for alias in node.names:
                if alias.name in symbols:
                    found.append(
                        (node.lineno, f"{node.module}.{alias.name}", symbols[alias.name])
                    )
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in module_local_names
        ):
            module = module_local_names[node.value.id]
            symbols = FORBIDDEN_STDLIB_SYMBOLS[module]
            if node.attr in symbols:
                found.append((node.lineno, f"{module}.{node.attr}", symbols[node.attr]))
    return sorted(set(found))


def test_forbidden_symbol_is_caught_via_from_import(tmp_path: Path) -> None:
    script = tmp_path / "sample.py"
    script.write_text("from datetime import UTC\n\nprint(UTC)\n", encoding="utf-8")
    hits = forbidden_symbols_used(script)
    assert hits == [(1, "datetime.UTC", "3.11")]


def test_forbidden_symbol_is_caught_via_module_attribute(tmp_path: Path) -> None:
    script = tmp_path / "sample.py"
    script.write_text(
        "import datetime as dt\n\nprint(dt.UTC)\n", encoding="utf-8"
    )
    hits = forbidden_symbols_used(script)
    assert hits == [(3, "datetime.UTC", "3.11")]


def test_portable_datetime_usage_is_not_flagged(tmp_path: Path) -> None:
    """The fix this guard exists to require — `datetime.timezone.utc` — must
    not itself trip the guard."""
    script = tmp_path / "sample.py"
    script.write_text(
        "from datetime import datetime, timezone\n\nprint(datetime.now(timezone.utc))\n",
        encoding="utf-8",
    )
    assert forbidden_symbols_used(script) == []


def test_the_scripts_ci_directory_exists() -> None:
    """A sanity check the rest of this module depends on: if `scripts/ci/`
    moves, every finding below would silently report zero jobs at risk."""
    assert CI_SCRIPTS_DIR.is_dir()


def test_ci_scripts_run_without_setup_python_stay_on_the_runner_baseline() -> None:
    """The real guard: every `scripts/ci/*.py` script that some job invokes
    without an `actions/setup-python` step must be parseable as staying on
    the Python 3.10 baseline.

    A failure here names the job, the script and the offending symbol so the
    fix is obvious: either make the script portable (drop the newer-than-3.10
    name), or give that job an `actions/setup-python` step.
    """
    problems: list[str] = []
    for filename, job_id, script_rel in jobs_running_ci_scripts_without_setup_python():
        script_path = REPO_ROOT / script_rel
        if not script_path.is_file():
            # A script the workflow names but the tree does not have is a
            # different defect (test_workflow_wiring_resolves.py's territory,
            # not this guard's); skip rather than crash the scan on it.
            continue
        for _lineno, symbol, added_in in forbidden_symbols_used(script_path):
            problems.append(
                f"{filename}:{job_id} invokes {script_rel} without "
                f"actions/setup-python, and {script_rel} uses {symbol} "
                f"(added in Python {added_in}). {filename}:{job_id} runs on "
                "ubuntu-22.04's system python3, which is 3.10. Either make "
                f"{script_rel} portable (drop the {added_in}-only name), or "
                f"add actions/setup-python to the {job_id} job."
            )
    assert not problems, "\n".join(sorted(problems))


# ── The same rule, via vermin ────────────────────────────────────────────────

# Passed to vermin as `-t=3.10-`: "the minimum version this file requires must
# be 3.10 or lower". Same baseline as the ast scan above, named once.
RUNNER_BASELINE = "3.10"


def _vermin_binary() -> Path:
    """The `vermin` console script beside the interpreter running these tests.

    `python -m vermin` does not work — the distribution ships a package with no
    `__main__` — so the console script is the entry point, and it lives in the
    same `bin/` as the `pytest` that is executing this.
    """
    candidate = Path(sys.executable).parent / "vermin"
    assert candidate.is_file(), (
        f"vermin not found at {candidate}. It is declared in "
        "apps/backend/pyproject.toml's [dev] extra for this guard; rebuild the "
        "dev environment with `make install`. This asserts rather than skips "
        "deliberately: a gate that passes because its tool is missing is not a "
        "gate (ADR 0005, P2)."
    )
    return candidate


def vermin_baseline_report(path: Path) -> tuple[int, str]:
    """`(exit status, report)` from vermin checking *path* against the baseline.

    A non-zero status means the file requires a Python newer than the runner
    provides; the report names the offending construct and the version that
    introduced it.
    """
    result = subprocess.run(
        [
            str(_vermin_binary()),
            f"-t={RUNNER_BASELINE}-",
            "--no-tips",
            "--violations",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    return result.returncode, f"{result.stdout}{result.stderr}".strip()


def test_vermin_flags_a_name_newer_than_the_runner_baseline(tmp_path: Path) -> None:
    """Non-vacuity: vermin must actually reject the construct that broke
    quarantine-notice, or the guard below proves nothing."""
    sample = tmp_path / "sample.py"
    sample.write_text("from datetime import UTC\n\nprint(UTC)\n", encoding="utf-8")
    status, report = vermin_baseline_report(sample)
    assert status != 0, f"vermin accepted datetime.UTC at {RUNNER_BASELINE}:\n{report}"
    assert "3.11" in report, report


def test_vermin_accepts_the_portable_form(tmp_path: Path) -> None:
    """And it must accept the fix, or the guard would forbid its own remedy."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from datetime import datetime, timezone\n\n"
        "print(datetime.now(timezone.utc))\n",
        encoding="utf-8",
    )
    status, report = vermin_baseline_report(sample)
    assert status == 0, report


def test_vermin_catches_what_the_seeded_list_would_miss(tmp_path: Path) -> None:
    """The reason vermin is here at all: a 3.11+ name that
    FORBIDDEN_STDLIB_SYMBOLS does not carry is still caught.

    `tomllib` is a real example — scripts/validate_security_suppressions.py
    uses it, and its job pins 3.12 precisely because of that — and it is
    deliberately absent from the seeded set.
    """
    assert "tomllib" not in FORBIDDEN_STDLIB_SYMBOLS
    sample = tmp_path / "sample.py"
    sample.write_text("import tomllib\n\nprint(tomllib)\n", encoding="utf-8")
    assert forbidden_symbols_used(sample) == []
    status, report = vermin_baseline_report(sample)
    assert status != 0, f"vermin accepted tomllib at {RUNNER_BASELINE}:\n{report}"


def test_ci_scripts_without_setup_python_pass_vermin() -> None:
    """The comprehensive form of the guard above.

    Same scope — jobs with no `actions/setup-python` — but the verdict comes
    from vermin's version database rather than a hand-seeded list, so a name
    nobody thought to forbid is caught too.
    """
    problems: list[str] = []
    for filename, job_id, script_rel in jobs_running_ci_scripts_without_setup_python():
        script_path = REPO_ROOT / script_rel
        if not script_path.is_file():
            continue
        status, report = vermin_baseline_report(script_path)
        if status != 0:
            problems.append(
                f"{filename}:{job_id} invokes {script_rel} without "
                f"actions/setup-python, so it runs on ubuntu-22.04's system "
                f"python3 ({RUNNER_BASELINE}), but vermin reports:\n"
                f"{report}\n"
                f"Either make {script_rel} portable, or add "
                f"actions/setup-python to the {job_id} job."
            )
    assert not problems, "\n\n".join(sorted(problems))
