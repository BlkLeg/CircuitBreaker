"""The Dependabot lockfile sync must leave a PR that can actually merge.

`.github/workflows/dependabot-lockfile-sync.yml` regenerates
`apps/backend/requirements.txt` and pushes it with GITHUB_TOKEN. A GITHUB_TOKEN
push triggers no `push`/`pull_request` workflow, so without a follow-up
dispatch the new head SHA never receives the 21 required checks and the PR is
permanently unmergeable. These tests pin that follow-up, and the security
properties the workflow already had, since `pull_request_target` hands the job
a writable token:

* the actor guard (only Dependabot, only on `dependabot/*` branches);
* every script executed comes from the BASE commit, never the PR head;
* every `${{ }}` ref reaches the shell through `env:`, never inline.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "dependabot-lockfile-sync.yml"
DISPATCH_SCRIPT = "scripts/ci/dispatch_required_checks.sh"


def _document() -> dict[Any, Any]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _steps() -> list[dict[str, Any]]:
    return list(_document()["jobs"]["sync"]["steps"])


def _step(name_fragment: str) -> dict[str, Any]:
    matches = [step for step in _steps() if name_fragment in str(step.get("name", ""))]
    assert len(matches) == 1, f"expected one step named like {name_fragment!r}"
    return matches[0]


def test_fires_for_prs_into_dev_and_main() -> None:
    document = _document()
    trigger = document.get("on", document.get(True))["pull_request_target"]
    assert set(trigger["branches"]) == {"dev", "main"}
    assert trigger["paths"] == ["apps/backend/poetry.lock"]


def test_actor_guard_is_intact() -> None:
    condition = str(_document()["jobs"]["sync"]["if"])
    assert "github.actor == 'dependabot[bot]'" in condition
    assert "startsWith(github.head_ref, 'dependabot/')" in condition


def test_token_can_dispatch_workflows_and_nothing_more() -> None:
    assert _document()["permissions"] == {"contents": "write", "actions": "write"}


def test_every_executed_script_is_restored_from_the_base_commit() -> None:
    restore = _step("from the base commit")
    run = str(restore["run"])
    assert restore["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert 'git restore --source="$BASE_SHA"' in run
    for path in (
        "scripts/gen_requirements.py",
        DISPATCH_SCRIPT,
        "scripts/ci/lib/common.sh",
    ):
        assert path in run, f"{path} is executed but not restored from the base commit"
    steps = _steps()
    restore_index = steps.index(restore)
    for index, step in enumerate(steps):
        run_text = str(step.get("run", ""))
        if "gen_requirements.py" in run_text or DISPATCH_SCRIPT in run_text:
            assert index >= restore_index, f"{step.get('name')} runs before the restore"


def test_dispatch_follows_a_push_and_only_a_push() -> None:
    push = _step("Push the result")
    dispatch = _step("Dispatch the required checks")
    steps = _steps()
    assert steps.index(dispatch) > steps.index(push)
    assert push["id"] == "push"
    assert 'echo "pushed=true" >> "$GITHUB_OUTPUT"' in push["run"]
    assert dispatch["if"] == "steps.push.outputs.pushed == 'true'"
    assert dispatch["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert dispatch["env"]["HEAD_REF"] == "${{ github.event.pull_request.head.ref }}"
    assert dispatch["env"]["BASE_REF"] == "${{ github.event.pull_request.base.ref }}"
    assert dispatch["run"] == f'bash {DISPATCH_SCRIPT} "$HEAD_REF" "$BASE_REF"'


def test_no_expression_is_interpolated_into_a_shell_body() -> None:
    for step in _steps():
        run = str(step.get("run", ""))
        assert not re.search(r"\$\{\{", run), (
            f"step {step.get('name')!r} interpolates an expression into run:; "
            "pass it through env: and quote it"
        )
