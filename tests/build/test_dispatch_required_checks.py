"""scripts/ci/dispatch_required_checks.sh puts every required check on a branch.

A commit pushed with GITHUB_TOKEN triggers no `push`/`pull_request` workflow,
so the rulesets' 21 required checks never appear on it and the PR can never
merge. The script dispatches the workflows instead. Its whole value is that
the set it dispatches is complete, so that is what these tests pin:

* the script is run for real, against a stub `gh` that records its calls, so
  the workflows asserted on are the ones it actually dispatches rather than a
  list copied out of its source;
* every required check name must be produced by a job in one of those
  workflows, with matrix names expanded the way GitHub expands them;
* every dispatched workflow must accept `workflow_dispatch`, and no job that
  produces a required check may carry a job-level `if:` that keys on the
  event without allowing `workflow_dispatch` — such a job would be skipped,
  and a skipped required check blocks the merge just like a missing one.
"""

from __future__ import annotations

import itertools
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.build.required_checks import REQUIRED_CHECKS

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "dispatch_required_checks.sh"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

_FAKE_GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_GH_LOG"
if [ -n "${FAKE_GH_FAIL:-}" ] && [ "$3" = "$FAKE_GH_FAIL" ]; then
    echo "HTTP 422: Workflow does not have 'workflow_dispatch' trigger" >&2
    exit 1
fi
exit 0
"""


def _run_script(
    tmp_path: Path, *args: str, fail: str | None = None
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    """Run the script with a recording `gh` stub first on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(_FAKE_GH, encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "gh.log"
    log.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["FAKE_GH_LOG"] = str(log)
    if fail is not None:
        env["FAKE_GH_FAIL"] = fail
    else:
        env.pop("FAKE_GH_FAIL", None)
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    calls = [line.split(" ") for line in log.read_text(encoding="utf-8").splitlines()]
    return result, calls


def _dispatched_workflows(tmp_path: Path, *args: str) -> list[str]:
    """The workflow files the script dispatches for these arguments."""
    result, calls = _run_script(tmp_path, *args)
    assert result.returncode == 0, result.stderr
    workflows: list[str] = []
    for call in calls:
        assert call[:2] == ["workflow", "run"], f"unexpected gh call: {call}"
        assert call[3:] == ["--ref", args[0]], f"dispatch not pinned to the branch: {call}"
        workflows.append(call[2])
    return workflows


def _load(workflow: str) -> dict[Any, Any]:
    document = yaml.safe_load((WORKFLOW_DIR / workflow).read_text(encoding="utf-8"))
    assert isinstance(document, dict), workflow
    return document


def _triggers(document: dict[Any, Any]) -> dict[str, Any]:
    # yaml 1.1 parses a bare `on:` key as the boolean True.
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict), "workflow triggers are not a mapping"
    return triggers


def _expand_job_names(job: dict[str, Any], job_id: str) -> list[str]:
    """Check-run names one job produces, with `matrix.*`/`strategy.job-total` expanded.

    Only the plain `key: [values]` matrix shape is understood; anything else
    fails loudly rather than being guessed at, because a wrong expansion here
    would make the completeness assertion pass for the wrong reason.
    """
    name = str(job.get("name", job_id))
    matrix = (job.get("strategy") or {}).get("matrix")
    if not matrix:
        return [name]
    assert isinstance(matrix, dict) and all(
        isinstance(values, list) for values in matrix.values()
    ), f"job {job_id}: unsupported matrix shape {matrix!r}"
    keys = list(matrix)
    combos = list(itertools.product(*(matrix[key] for key in keys)))
    names: list[str] = []
    for combo in combos:
        expanded = re.sub(r"\$\{\{\s*strategy\.job-total\s*\}\}", str(len(combos)), name)
        for key, value in zip(keys, combo):
            expanded = re.sub(
                r"\$\{\{\s*matrix\." + re.escape(key) + r"\s*\}\}", str(value), expanded
            )
        assert "${{" not in expanded, f"job {job_id}: unexpanded expression in {expanded!r}"
        names.append(expanded)
    return names


def _producers(workflows: list[str]) -> dict[str, tuple[str, str, dict[str, Any]]]:
    """check name -> (workflow, job id, job) for every job in these workflows."""
    produced: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for workflow in workflows:
        for job_id, job in (_load(workflow).get("jobs") or {}).items():
            for check in _expand_job_names(job, job_id):
                produced.setdefault(check, (workflow, job_id, job))
    return produced


def test_the_required_list_has_the_twenty_one_ruleset_checks() -> None:
    assert len(REQUIRED_CHECKS) == 21
    assert len(set(REQUIRED_CHECKS)) == 21, "duplicate name in REQUIRED_CHECKS"


def test_script_is_strict_bash_and_executable() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert SCRIPT.stat().st_mode & 0o111, "script is not executable"


@pytest.mark.parametrize("base_args", [(), ("dev",), ("main",)])
def test_every_required_check_is_produced_by_a_dispatched_workflow(
    tmp_path: Path, base_args: tuple[str, ...]
) -> None:
    workflows = _dispatched_workflows(tmp_path, "dependabot/pip/example", *base_args)
    assert workflows, "the script dispatched nothing"
    produced = _producers(workflows)
    missing = [check for check in REQUIRED_CHECKS if check not in produced]
    assert not missing, (
        f"required checks no dispatched workflow produces ({workflows}): {missing}"
    )


@pytest.mark.parametrize("base", ["dev", "main"])
def test_every_dispatched_workflow_accepts_workflow_dispatch(tmp_path: Path, base: str) -> None:
    for workflow in _dispatched_workflows(tmp_path, "feature/x", base):
        assert "workflow_dispatch" in _triggers(_load(workflow)), (
            f"{workflow} is dispatched by {SCRIPT.name} but has no workflow_dispatch "
            "trigger; `gh workflow run` fails with HTTP 422"
        )


def _job_chain(workflow: str, job_id: str) -> list[tuple[str, dict[str, Any]]]:
    """The job and every job it transitively `needs`."""
    jobs = _load(workflow)["jobs"]
    seen: list[str] = []
    stack = [job_id]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.append(current)
        needs = jobs[current].get("needs") or []
        stack.extend([needs] if isinstance(needs, str) else needs)
    return [(name, jobs[name]) for name in seen]


@pytest.mark.parametrize("base", ["dev", "main"])
def test_no_required_job_is_skipped_on_workflow_dispatch(tmp_path: Path, base: str) -> None:
    """A job-level `if:` naming the event must admit workflow_dispatch.

    Walks `needs` too: a required job downstream of a job skipped on dispatch
    is itself skipped.
    """
    produced = _producers(_dispatched_workflows(tmp_path, "feature/x", base))
    offenders: list[str] = []
    for check in REQUIRED_CHECKS:
        workflow, job_id, _ = produced[check]
        for chain_id, job in _job_chain(workflow, job_id):
            condition = str(job.get("if", ""))
            if "github.event_name" in condition and "workflow_dispatch" not in condition:
                offenders.append(f"{check} <- {workflow}:{chain_id} if: {condition}")
    assert not offenders, f"required jobs that would be skipped on dispatch: {offenders}"


def test_a_failed_dispatch_fails_the_script_and_names_the_workflow(tmp_path: Path) -> None:
    result, calls = _run_script(tmp_path, "feature/x", "dev", fail="security.yml")
    assert result.returncode != 0
    assert "security.yml" in result.stderr
    # The remaining dispatches were still attempted, so one run reports all failures.
    assert [call[2] for call in calls] == ["dev-ci.yml", "security.yml", "codeql.yml"]


@pytest.mark.parametrize(
    "args",
    [(), ("",), ("feature/x", "release"), ("--ref",), ("a", "dev", "extra")],
)
def test_bad_arguments_are_rejected_before_any_dispatch(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    result, calls = _run_script(tmp_path, *args)
    assert result.returncode != 0
    assert calls == [], f"dispatched despite bad arguments {args!r}: {calls}"
