"""One dispatch, one human approval — and the approval has to be real.

release.yml's candidate channel can go straight on to promote in the same run
(inputs.promote, default true). What stops that from being an unattended
publish is `environment: release` on the promote job, with a required
reviewer. GitHub's failure mode here is silent: a job that names an
environment which does not exist gets one created on the fly, unprotected,
and proceeds. So these tests pin three things together — the environment on
promote, an assertion upstream of promote that the environment has a
required-reviewers rule, and that promote cannot run unless promote-verify
succeeded — plus the post-release follow-up wiring.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
RELEASE = WORKFLOWS / "release.yml"
FOLLOWUP = WORKFLOWS / "release-followup.yml"
MAKEFILE = ROOT / "Makefile"

GUARD_JOB = "release-environment-guard"


def _load(path: Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{path.name} did not parse to a mapping"
    return document


def _triggers(document: dict) -> dict:
    raw = document.get("on", document.get(True))
    return raw if isinstance(raw, dict) else {}


def _needs(job: dict) -> set[str]:
    needs = job.get("needs")
    if isinstance(needs, str):
        return {needs}
    return set(needs or [])


def _upstream(jobs: dict, name: str) -> set[str]:
    seen: set[str] = set()
    pending = list(_needs(jobs[name]))
    while pending:
        job = pending.pop()
        if job not in seen:
            seen.add(job)
            pending.extend(_needs(jobs[job]))
    return seen


def _runs(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


def _condition(job: dict) -> str:
    return " ".join(str(job.get("if", "")).split())


JOBS = _load(RELEASE)["jobs"]


def test_the_promote_input_is_a_boolean_defaulting_to_true() -> None:
    inputs = _triggers(_load(RELEASE))["workflow_dispatch"]["inputs"]
    promote = inputs["promote"]
    assert promote["type"] == "boolean"
    assert promote["default"] is True


def _environment_name(job: dict[str, Any]) -> str | None:
    environment = job.get("environment")
    return environment.get("name") if isinstance(environment, dict) else environment


def test_promote_declares_the_release_environment() -> None:
    environment = JOBS["promote"].get("environment")
    name = _environment_name(JOBS["promote"])
    assert name == "release", (
        "the promote job must run behind `environment: release`; that environment's "
        "required reviewer is the only human approval between a candidate and a "
        f"published release. Found: {environment!r}"
    )


def test_only_promote_uses_the_release_environment() -> None:
    """Approving must mean approving the publish, not some earlier step."""
    others = sorted(
        name
        for name, job in JOBS.items()
        if name != "promote" and _environment_name(job) == "release"
    )
    assert not others, f"jobs other than promote declare the release environment: {others}"


def test_an_upstream_job_asserts_the_environment_requires_a_reviewer() -> None:
    """A missing environment is auto-created unprotected; something must refuse."""
    assert GUARD_JOB in JOBS, f"release.yml has no {GUARD_JOB!r} job"
    assert GUARD_JOB in _upstream(JOBS, "promote"), (
        f"{GUARD_JOB} is not upstream of promote, so promote can start without "
        "the reviewer rule having been checked"
    )
    run = _runs(JOBS[GUARD_JOB])
    assert re.search(
        r"gh api \"?repos/\$\{GITHUB_REPOSITORY\}/environments/release\"?", run
    )
    assert "protection_rules" in run and '"required_reviewers"' in run
    assert "::error::" in run and "exit 1" in run
    permissions = JOBS[GUARD_JOB].get("permissions") or {}
    assert permissions.get("actions") in {"read", "write"}, (
        "GET /repos/{owner}/{repo}/environments/{name} needs the Actions read "
        f"permission; the guard job grants {permissions!r}"
    )


def test_the_guard_runs_whenever_a_promote_can() -> None:
    condition = _condition(JOBS[GUARD_JOB])
    assert "inputs.channel == 'stable'" in condition
    assert "inputs.promote == true" in condition
    verify = _condition(JOBS["promote-verify"])
    assert f"needs.{GUARD_JOB}.result == 'success'" in verify


def test_promote_cannot_run_unless_promote_verify_succeeded() -> None:
    promote = JOBS["promote"]
    assert "promote-verify" in _needs(promote)
    condition = _condition(promote)
    assert "needs.promote-verify.result == 'success'" in condition
    assert "always()" not in condition, (
        "always() would let promote run after promote-verify failed"
    )
    assert "!failure()" in condition


def test_a_candidate_only_promotes_after_its_draft_was_staged() -> None:
    verify = JOBS["promote-verify"]
    assert "release" in _needs(verify)
    condition = _condition(verify)
    assert "needs.release.result == 'success'" in condition
    assert "inputs.promote == true" in condition
    assert "inputs.channel == 'stable'" in condition
    assert "!cancelled()" in condition and "!failure()" in condition


def test_no_release_job_runs_regardless_of_upstream_failure() -> None:
    offenders = sorted(
        name for name, job in JOBS.items() if "always()" in _condition(job)
    )
    assert not offenders, f"jobs that run even after an upstream failure: {offenders}"


def test_publication_follow_ups_depend_on_promote_succeeding() -> None:
    condition = _condition(JOBS["post-publish"])
    assert "needs.promote.result == 'success'" in condition


def test_make_targets_choose_whether_a_candidate_promotes() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")

    def recipe(target: str) -> str:
        match = re.search(
            rf"^{re.escape(target)}:.*?(?=^\S|\Z)", text, re.MULTILINE | re.DOTALL
        )
        assert match, f"Makefile has no {target} target"
        return match.group(0)

    assert "-f channel=candidate -f promote=true" in recipe("release-candidate")
    assert "-f channel=candidate -f promote=false" in recipe("release-stage-only")
    assert "-f channel=stable" in recipe("release-promote")


def test_post_publish_dispatches_the_release_followup_on_dev() -> None:
    run = _runs(JOBS["post-publish"])
    assert re.search(
        r'gh workflow run release-followup\.yml --ref dev -f version="\$\{VERSION\}"',
        run,
    ), (
        "post-publish must dispatch release-followup.yml on dev with the released version"
    )
    assert (JOBS["post-publish"].get("permissions") or {}).get("actions") == "write"


def test_the_followup_workflow_takes_a_required_version_input() -> None:
    assert FOLLOWUP.exists(), "release-followup.yml is missing"
    triggers = _triggers(_load(FOLLOWUP))
    assert set(triggers) == {"workflow_dispatch"}, (
        f"release-followup.yml must be dispatch-only; triggers are {sorted(triggers)}"
    )
    version = triggers["workflow_dispatch"]["inputs"]["version"]
    assert version["required"] is True


def test_the_followup_job_has_what_it_needs_and_nothing_is_interpolated_into_shell() -> (
    None
):
    jobs = _load(FOLLOWUP)["jobs"]
    assert len(jobs) == 1
    job = next(iter(jobs.values()))
    assert job["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "actions": "write",
    }
    checkout = [
        s
        for s in job["steps"]
        if str(s.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkout and checkout[0]["with"]["ref"] == "dev"

    run = _runs(job)
    assert "${{" not in run, "every ${{ }} must reach the shell through env:"
    assert "scripts/post_release_bump.py open-next" in run
    assert "scripts/post_release_bump.py stale-drafts" in run
    assert "scripts/check_version_parity.py --write" in run
    assert 'bash scripts/ci/dispatch_required_checks.sh "${BRANCH}"' in run
    assert "gh pr create" in run and "--base dev" in run
    assert "chore/post-release-v${RELEASED}" in run
    assert "--force" not in run and "push -f" not in run, (
        "a re-run must continue the follow-up branch, never force-push over it"
    )


@pytest.mark.parametrize("target", ["release-candidate", "release-stage-only", "release-promote"])
def test_make_release_targets_refuse_to_dispatch_off_main(target: str, tmp_path: Path) -> None:
    """The Stage job signs bundles only from main; a dispatch from dev would
    build an unsigned draft. Fake git says the branch is dev; fake gh logs."""
    log = tmp_path / "calls.log"
    for tool, body in (
        ("git", f'echo "git $*" >> "{log}"\n[ "$1" = rev-parse ] && echo dev\nexit 0\n'),
        ("gh", f'echo "gh $*" >> "{log}"\nexit 0\n'),
    ):
        exe = tmp_path / tool
        exe.write_text("#!/bin/sh\n" + body)
        exe.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    r = subprocess.run(["make", "--no-print-directory", "-f", str(MAKEFILE), target],
                       cwd=MAKEFILE.parent, capture_output=True, text=True, env=env, check=False)
    assert r.returncode != 0
    assert f"make {target} dispatches only from main" in r.stdout
    assert "Current branch: dev" in r.stdout
    calls = log.read_text() if log.exists() else ""
    assert "gh " not in calls and "git fetch" not in calls, calls
