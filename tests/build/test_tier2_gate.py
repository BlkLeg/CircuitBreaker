"""tier2_gate.py: the two Tier 2 decisions that must not live in workflow YAML."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

from tier2_gate import (  # noqa: E402
    DEFAULT_SUITES,
    KNOWN_SUITES,
    PlanError,
    judge,
    main,
    parse_suites,
    resolve_ref,
)


def test_empty_suites_means_the_whole_default_tier():
    assert parse_suites("") == sorted(DEFAULT_SUITES)
    assert parse_suites("   ") == sorted(DEFAULT_SUITES)


def test_suites_are_sorted_and_deduplicated():
    assert parse_suites('["composed","browser","browser"]') == ["browser", "composed"]


@pytest.mark.parametrize(
    "raw",
    ['["brwoser"]', "browser", "[]", '"browser"', '[1]', '["browser", null]', "{}"],
)
def test_plan_rejects_unknown_or_malformed_suites(raw):
    with pytest.raises(PlanError):
        parse_suites(raw)


def test_plan_names_the_unknown_suite():
    with pytest.raises(PlanError, match="brwoser"):
        parse_suites('["browser","brwoser"]')


def test_default_suites_are_all_known():
    assert set(DEFAULT_SUITES) <= set(KNOWN_SUITES)


def test_mono_is_a_known_suite():
    assert "mono" in KNOWN_SUITES
    assert "mono" in DEFAULT_SUITES


def test_scheduled_run_tests_dev():
    assert resolve_ref("schedule", "") == "dev"
    assert resolve_ref("schedule", "main") == "dev"


@pytest.mark.parametrize("event", ["workflow_dispatch", "push", "workflow_call"])
def test_other_events_honour_the_requested_ref(event):
    assert resolve_ref(event, "") == ""
    assert resolve_ref(event, "feat/tier2-slice-a2") == "feat/tier2-slice-a2"
    assert resolve_ref(event, "v0.4.5") == "v0.4.5"


@pytest.mark.parametrize("ref", ["dev\nsuites=[]", "dev;rm -rf /", "$(id)", "a b", "x" * 256])
def test_plan_rejects_a_ref_that_could_forge_an_output(ref):
    with pytest.raises(PlanError):
        resolve_ref("workflow_dispatch", ref)


def _needs(**results: str) -> dict:
    return {job: {"result": outcome, "outputs": {}} for job, outcome in results.items()}


def test_result_passes_when_selected_succeed_and_unselected_skip():
    assert judge(_needs(plan="success", browser="success", composed="skipped", mono="skipped"), ["browser"]) == []
    assert judge(
        _needs(plan="success", browser="success", composed="success", mono="skipped"), ["browser", "composed"]
    ) == []


def test_result_fails_when_a_selected_suite_was_skipped():
    problems = judge(
        _needs(plan="success", browser="skipped", composed="success", mono="skipped"), ["browser", "composed"]
    )
    assert problems == ["browser: skipped (expected success)"]


def test_result_fails_when_an_unselected_suite_ran():
    problems = judge(_needs(plan="success", browser="success", composed="success", mono="skipped"), ["browser"])
    assert problems == ["composed: success (expected skipped)"]


def test_result_fails_when_a_known_suite_is_missing_from_needs():
    problems = judge(_needs(plan="success", browser="success", mono="skipped"), ["browser"])
    assert problems == ["composed: None (expected skipped)"]


def test_result_reports_only_the_plan_when_the_plan_failed():
    assert judge(_needs(plan="failure", browser="skipped", composed="skipped", mono="skipped"), []) == ["plan: failure"]


def test_main_plan_writes_github_output(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("SUITES", '["browser"]')
    monkeypatch.setenv("REF", "")
    monkeypatch.setenv("EVENT_NAME", "schedule")
    assert main(["plan"]) == 0
    assert out.read_text().splitlines() == ['suites=["browser"]', "ref=dev"]


def test_main_plan_fails_loudly_without_writing_output(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("SUITES", '["brwoser"]')
    monkeypatch.setenv("REF", "")
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    assert main(["plan"]) == 1
    assert not out.exists()
    assert "::error::" in capsys.readouterr().out


def test_main_result_exit_codes(monkeypatch):
    monkeypatch.setenv("SUITES", '["browser","composed"]')
    monkeypatch.setenv(
        "RESULTS", json.dumps(_needs(plan="success", browser="success", composed="success", mono="skipped"))
    )
    assert main(["result"]) == 0
    monkeypatch.setenv(
        "RESULTS", json.dumps(_needs(plan="success", browser="failure", composed="success", mono="skipped"))
    )
    assert main(["result"]) == 1
