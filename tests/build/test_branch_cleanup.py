"""scripts/ci/branch_cleanup.py deletes only merged, idle, unreviewed branches.

Deleting a branch is the one irreversible thing the weekly cleanup does, so the
selection rules are tested against a frozen snapshot of real-shaped API
payloads (tests/fixtures/branch-cleanup-repo.json) through the script's own
parsers, with no network. The workflow wiring is checked statically.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "branch_cleanup.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "branch-cleanup-repo.json"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "branch-cleanup.yml"
MIN_AGE = timedelta(days=14)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("branch_cleanup", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules.
    sys.modules["branch_cleanup"] = module
    spec.loader.exec_module(module)
    return module


bc = _load_module()
DATA: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
NOW = bc.parse_timestamp(DATA["now"])


class FixtureClient:
    """A GitHubClient answering from the fixture, recording every call."""

    def __init__(
        self,
        moved: dict[str, str] | None = None,
        fail_delete: set[str] | None = None,
        fail_head: set[str] | None = None,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.deleted: list[str] = []
        self._moved = moved or {}
        self._fail_delete = fail_delete or set()
        self._fail_head = fail_head or set()
        self._head_reads: dict[str, int] = {}

    def list_branches(self) -> list[str]:
        self.calls.append(("list_branches",))
        return bc.parse_branch_names(DATA["branches"])

    def open_pr_heads(self) -> set[str]:
        self.calls.append(("open_pr_heads",))
        return bc.parse_open_pr_heads(DATA["pulls"], DATA["repo"])

    def open_pr_bases(self) -> set[str]:
        self.calls.append(("open_pr_bases",))
        return bc.parse_open_pr_bases(DATA["pulls"])

    def branch_head(self, branch: str) -> Any:
        self.calls.append(("branch_head", branch))
        if branch in self._fail_head:
            raise subprocess.CalledProcessError(1, ["gh", "api"], stderr="HTTP 502")
        reads = self._head_reads.get(branch, 0)
        self._head_reads[branch] = reads + 1
        head = bc.parse_branch_head(DATA["branch_details"][branch])
        if reads > 0 and branch in self._moved:
            return bc.BranchHead(
                sha=self._moved[branch], committed_at=head.committed_at
            )
        return head

    def ahead_by(self, base: str, sha: str) -> int:
        self.calls.append(("ahead_by", base, sha))
        return int(DATA["ahead_by"][f"{base}...{sha}"])

    def delete_branch(self, branch: str) -> None:
        self.calls.append(("delete_branch", branch))
        if branch in self._fail_delete:
            raise subprocess.CalledProcessError(1, ["gh", "api"], stderr="HTTP 422")
        self.deleted.append(branch)


def _run(
    client: FixtureClient, dry_run: bool
) -> tuple[list[Any], list[str], list[str]]:
    lines: list[str] = []
    decisions, failures = bc.run(client, NOW, MIN_AGE, dry_run, log=lines.append)
    return decisions, failures, lines


def test_every_branch_gets_the_expected_decision() -> None:
    decisions, failures, _ = _run(FixtureClient(), dry_run=True)
    assert failures == []
    assert {d.branch: d.delete for d in decisions} == DATA["expected"]


def test_every_decision_is_logged_exactly_once_with_its_reason() -> None:
    decisions, _, lines = _run(FixtureClient(), dry_run=True)
    assert len(lines) == len(decisions)
    for decision in decisions:
        matching = [line for line in lines if line.startswith(f"{decision.branch}: ")]
        assert len(matching) == 1, decision.branch
        assert decision.reason in matching[0]


def test_dry_run_deletes_nothing() -> None:
    client = FixtureClient()
    _, _, lines = _run(client, dry_run=True)
    assert client.deleted == []
    assert not any(call[0] == "delete_branch" for call in client.calls)
    assert sum("[dry run: not deleted]" in line for line in lines) == 3


def test_live_run_deletes_exactly_the_selected_branches() -> None:
    client = FixtureClient()
    _, failures, lines = _run(client, dry_run=False)
    assert failures == []
    assert sorted(client.deleted) == sorted(
        name for name, delete in DATA["expected"].items() if delete
    )
    assert sum(line.endswith("[deleted]") for line in lines) == 3


@pytest.mark.parametrize("branch", ["main", "dev", "gh-pages"])
def test_long_lived_branches_are_never_even_inspected(branch: str) -> None:
    client = FixtureClient()
    _run(client, dry_run=False)
    assert ("branch_head", branch) not in client.calls
    assert branch not in client.deleted


def test_open_pr_head_and_base_are_kept_without_inspection() -> None:
    client = FixtureClient()
    decisions, _, _ = _run(client, dry_run=False)
    reasons = {d.branch: d.reason for d in decisions}
    assert reasons["feat/open-pr"] == "keep: head of an open pull request"
    assert reasons["feat/stack-base"] == "keep: base of an open pull request"
    assert ("branch_head", "feat/open-pr") not in client.calls


def test_a_fork_pr_with_the_same_head_name_does_not_protect_our_branch() -> None:
    heads = bc.parse_open_pr_heads(DATA["pulls"], DATA["repo"])
    assert "fix/typo" not in heads
    assert "feat/open-pr" in heads


def test_young_branches_cost_no_compare_call() -> None:
    client = FixtureClient()
    decisions, _, _ = _run(client, dry_run=True)
    reasons = {d.branch: d.reason for d in decisions}
    for branch in ("fix/merged-young", "fix/just-under-fourteen-days"):
        assert "younger than 14 days" in reasons[branch]
        sha = DATA["branch_details"][branch]["commit"]["sha"]
        assert not any(
            call[0] == "ahead_by" and call[2] == sha for call in client.calls
        )


def test_containment_in_dev_alone_is_enough() -> None:
    decisions, _, _ = _run(FixtureClient(), dry_run=True)
    reason = {d.branch: d.reason for d in decisions}["fix/merged-into-dev-only"]
    assert "fully contained in dev" in reason


def test_unmerged_branch_reports_how_far_ahead_it_is() -> None:
    decisions, _, _ = _run(FixtureClient(), dry_run=True)
    reason = {d.branch: d.reason for d in decisions}["feat/unmerged-old"]
    assert reason == "keep: not merged (2 ahead of main, 1 ahead of dev)"


def test_containment_is_checked_against_the_captured_sha_not_the_name() -> None:
    client = FixtureClient()
    _run(client, dry_run=True)
    for call in client.calls:
        if call[0] == "ahead_by":
            assert len(call[2]) == 40 and all(c in "0123456789abcdef" for c in call[2])


def test_a_branch_that_moved_after_evaluation_is_kept() -> None:
    client = FixtureClient(moved={"fix/merged-old": "b" * 40})
    _, failures, lines = _run(client, dry_run=False)
    assert "fix/merged-old" not in client.deleted
    assert failures == []
    assert any(line.startswith("fix/merged-old: keep: head moved") for line in lines)


def test_a_failed_delete_is_reported_and_does_not_stop_the_rest() -> None:
    client = FixtureClient(fail_delete={"fix/merged-old"})
    _, failures, lines = _run(client, dry_run=False)
    assert failures == ["fix/merged-old"]
    assert sorted(client.deleted) == ["fix/merged-into-dev-only", "fix/typo"]
    assert any(line.startswith("fix/merged-old: ERROR") for line in lines)


def test_a_branch_that_cannot_be_evaluated_is_kept_and_reported() -> None:
    client = FixtureClient(fail_head={"fix/typo"})
    decisions, failures, _ = _run(client, dry_run=False)
    assert failures == ["fix/typo"]
    assert "fix/typo" not in client.deleted
    assert {d.branch: d.delete for d in decisions}["fix/typo"] is False


def test_timestamps_parse_as_utc_in_both_spellings() -> None:
    zulu = bc.parse_timestamp("2026-09-10T00:00:00Z")
    offset = bc.parse_timestamp("2026-09-10T02:00:00+02:00")
    assert zulu == offset
    assert zulu.utcoffset() == timedelta(0)


def _workflow() -> dict[Any, Any]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_workflow_is_weekly_and_dispatchable_with_dry_run_default_true() -> None:
    document = _workflow()
    triggers = document.get("on", document.get(True))
    assert len(triggers["schedule"]) == 1
    dry_run = triggers["workflow_dispatch"]["inputs"]["dry_run"]
    assert dry_run["type"] == "boolean"
    assert dry_run["default"] is True


def test_workflow_permissions_are_minimal() -> None:
    document = _workflow()
    assert document["permissions"] == {}
    (job,) = document["jobs"].values()
    assert job["permissions"] == {"contents": "write", "pull-requests": "read"}


def test_scheduled_runs_are_live_and_manual_runs_honour_the_input() -> None:
    (job,) = _workflow()["jobs"].values()
    run_step = next(
        step for step in job["steps"] if "branch_cleanup.py" in str(step.get("run", ""))
    )
    assert run_step["env"]["DRY_RUN"] == (
        "${{ github.event_name == 'workflow_dispatch' && inputs.dry_run || 'false' }}"
    )
    assert '"$DRY_RUN" = "true"' in run_step["run"]
    assert "${{" not in run_step["run"], "expressions must reach the shell through env:"
