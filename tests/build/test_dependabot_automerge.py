"""Dependabot auto-merge merges only what it is meant to.

.github/workflows/dependabot-automerge.yml queues `gh pr merge --auto` for
patch and minor Dependabot updates into `dev`. Each property pinned here is one
whose loss would merge code nobody reviewed: a major bump (which needs a
migration), an update into `main` (which moves only through a dev→main PR), or
a PR someone other than Dependabot opened.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "dependabot-automerge.yml"


def _workflow() -> dict[Any, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _job() -> dict[str, Any]:
    return _workflow()["jobs"]["automerge"]


def _steps_that_run(pattern: str) -> list[dict[str, Any]]:
    return [
        step for step in _job()["steps"] if re.search(pattern, str(step.get("run", "")))
    ]


def test_only_dependabot_prs_from_this_repository_are_considered() -> None:
    condition = _job()["if"]
    assert "github.event.pull_request.user.login == 'dependabot[bot]'" in condition
    assert (
        "github.event.pull_request.head.repo.full_name == github.repository"
        in condition
    )


def test_it_runs_on_pull_request_not_pull_request_target() -> None:
    triggers = _workflow().get("on") or _workflow()[True]
    assert set(triggers) == {"pull_request"}, triggers


def test_the_merge_is_queued_only_for_patch_or_minor_into_dev() -> None:
    merging = _steps_that_run(r"gh pr merge")
    assert len(merging) == 1, "exactly one step may merge"
    condition = merging[0]["if"]
    assert "github.event.pull_request.base.ref == 'dev'" in condition
    assert "semver-major" not in condition
    assert set(re.findall(r"semver-\w+", condition)) == {"semver-patch", "semver-minor"}


def test_the_merge_is_queued_not_forced() -> None:
    run = _steps_that_run(r"gh pr merge")[0]["run"]
    assert "--auto" in run, "without --auto the merge would skip the required checks"
    assert "--admin" not in run
    # The rulesets allow merge, squash and rebase; the repo merges with merge commits.
    assert "--merge" in run


def test_majors_are_flagged_never_merged() -> None:
    flagging = [s for s in _job()["steps"] if "semver-major" in str(s.get("if", ""))]
    assert flagging, "a major update must be flagged for a human"
    for step in flagging:
        assert "gh pr merge" not in step.get("run", "")


def test_untrusted_values_reach_the_shell_only_through_env() -> None:
    for step in _job()["steps"]:
        assert "${{" not in str(step.get("run", "")), step.get("name")


def test_permissions_are_granted_per_job_only() -> None:
    assert _workflow()["permissions"] == {}
    assert _job()["permissions"] == {"contents": "write", "pull-requests": "write"}


def test_gh_calls_name_a_repository_when_the_job_does_not_check_out() -> None:
    """Every `gh` call resolves a repository, since this job has no checkout.

    `gh` infers the repository from the git remote. This job runs
    `dependabot/fetch-metadata` and nothing else, so there is no checkout and no
    remote: `gh label create` without `--repo` exits 1 with "fatal: not a git
    repository", and `set -e` takes the whole step down before the label, the
    `gh pr edit` or the comment happens. Runs 36326829559 and its two siblings
    failed that way on 2026-09-27, so every major Dependabot PR sat unlabelled
    and uncommented while the step looked as though it had run.

    A call that names the pull request by full URL resolves without a remote,
    which is why those need no `--repo`. Anything else must pass one.
    """
    job = _job()
    if any("actions/checkout" in str(step.get("uses", "")) for step in job["steps"]):
        return  # a checkout gives gh its remote back; the guard is moot
    for step in job["steps"]:
        run = str(step.get("run", ""))
        starts = [match.start() for match in re.finditer(r"\bgh\s+[a-z]", run)]
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(run)
            call = run[start:end].strip()
            assert "--repo" in call or "PR_URL" in call, (
                f"{step.get('name')}: this gh call names no repository and the job "
                f"does not check out, so it will die with 'not a git repository':\n{call}"
            )
