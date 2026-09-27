"""The composed journey never runs twice on the same inputs with its failures unaddressed."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

from composed_rerun_guard import (  # noqa: E402
    ARTIFACT_PREFIX,
    CHECK,
    NODE_PREFIX,
    SUITE_INPUTS,
    Verdict,
    decide,
    deselect_args,
    failed_tests_from_junit,
    fingerprint,
    git_listing,
    pick_verdict_artifact,
    quarantined_tests,
)

HEADER = "quarantine_id,check,scope,reason,owner,tracking,opened,expiry,notes\n"
TODAY = date(2026, 9, 27)


def _register(tmp_path: Path, *rows: str) -> Path:
    path = tmp_path / "register.csv"
    path.write_text(HEADER + "".join(f"{row}\n" for row in rows), encoding="utf-8")
    return path


def _row(scope: str, expiry: str = "2026-12-21", check: str = CHECK) -> str:
    return f'Q-1,{check},"{scope}",why,owner,#1,2026-09-01,{expiry},'


def _verdict(outcome: str, *failed: str) -> Verdict:
    return Verdict("fp", "abc123", "https://example.invalid/run/1", outcome, tuple(failed))


# ── fingerprint ─────────────────────────────────────────────────────────────
def test_fingerprint_is_stable_and_input_sensitive():
    assert fingerprint("a\nb\n") == fingerprint("a\nb\n")
    assert fingerprint("a\nb\n") != fingerprint("a\nc\n")
    assert len(fingerprint("x")) == 16


def test_every_suite_input_exists_in_the_tree():
    """A renamed input would silently narrow the fingerprint: a fix under the new
    path would no longer count as a fix."""
    listing = git_listing(REPO_ROOT)
    for path in SUITE_INPUTS:
        # A directory shows as `<tab>path/…`, a file as `<tab>path<newline>`. A bare
        # prefix test would let `docker` match `docker-compose.yml`.
        assert f"\t{path}/" in listing or f"\t{path}\n" in listing, (
            f"{path} is in SUITE_INPUTS but not in the tree"
        )


def test_git_listing_fails_loudly_outside_a_repo(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        git_listing(tmp_path)


# ── register ────────────────────────────────────────────────────────────────
def test_quarantined_tests_reads_live_rows_for_this_check_only(tmp_path):
    register = _register(
        tmp_path,
        _row("test_a, test_b"),
        _row("test_old", expiry="2026-09-26"),
        _row("test_other", check="Browser E2E / browser-e2e"),
    )
    assert quarantined_tests(register, TODAY) == frozenset({"test_a", "test_b"})


def test_a_row_expiring_today_is_still_live(tmp_path):
    assert quarantined_tests(_register(tmp_path, _row("test_a", expiry="2026-09-27")), TODAY) == {"test_a"}


# ── junit ───────────────────────────────────────────────────────────────────
def test_failed_tests_from_junit(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite>'
        '<testcase name="test_pass"/>'
        '<testcase name="test_fail"><failure message="x"/></testcase>'
        '<testcase name="test_err"><error message="y"/></testcase>'
        '<testcase name="test_skip"><skipped/></testcase>'
        '</testsuite></testsuites>',
        encoding="utf-8",
    )
    assert failed_tests_from_junit(junit) == ["test_err", "test_fail"]


def test_missing_junit_means_no_test_level_failures(tmp_path):
    assert failed_tests_from_junit(tmp_path / "absent.xml") == []


# ── decide ──────────────────────────────────────────────────────────────────
def test_first_run_is_allowed():
    allowed, why = decide(None, frozenset())
    assert allowed and "no earlier verdict" in why


def test_a_pass_allows_the_next_run():
    assert decide(_verdict("success"), frozenset())[0]


def test_an_unaddressed_failure_blocks_and_names_the_tests():
    allowed, why = decide(_verdict("failure", "test_a", "test_b"), frozenset({"test_a"}))
    assert not allowed
    assert "test_b" in why and "https://example.invalid/run/1" in why


def test_a_fully_quarantined_failure_is_addressed():
    assert decide(_verdict("failure", "test_a", "test_b"), frozenset({"test_a", "test_b"}))[0]


def test_parametrised_names_match_their_base_row():
    assert decide(_verdict("failure", "test_a[x-1]"), frozenset({"test_a"}))[0]


def test_a_failure_without_test_names_can_only_be_fixed():
    allowed, why = decide(_verdict("failure"), frozenset({"test_a"}))
    assert not allowed and "change to the suite's inputs" in why


# ── verdict JSON ────────────────────────────────────────────────────────────
def test_verdict_round_trips():
    verdict = _verdict("failure", "test_a")
    assert Verdict.from_json(verdict.to_json()) == verdict


@pytest.mark.parametrize("text", ["", "{}", '{"outcome": "maybe"}', "[1]"])
def test_a_malformed_verdict_is_an_error_not_a_pass(text):
    with pytest.raises(ValueError):
        Verdict.from_json(text)


# ── artifact choice ─────────────────────────────────────────────────────────
def _artifact(created: str, repo_id: int = 7, expired: bool = False) -> dict:
    return {
        "name": ARTIFACT_PREFIX + "fp",
        "created_at": created,
        "expired": expired,
        "archive_download_url": f"https://api.invalid/{created}",
        "workflow_run": {"head_repository_id": repo_id},
    }


def test_pick_prefers_the_newest_trusted_unexpired_artifact():
    listing = {"artifacts": [
        _artifact("2026-09-25T00:00:00Z"),
        _artifact("2026-09-27T00:00:00Z", repo_id=999),        # a fork: never trusted
        _artifact("2026-09-26T12:00:00Z", expired=True),
        _artifact("2026-09-26T00:00:00Z"),
    ]}
    assert pick_verdict_artifact(listing, 7)["created_at"] == "2026-09-26T00:00:00Z"


def test_pick_returns_none_when_nothing_is_trusted():
    assert pick_verdict_artifact({"artifacts": [_artifact("2026-09-27T00:00:00Z", repo_id=999)]}, 7) is None


# ── deselection really deselects ────────────────────────────────────────────
def test_deselect_args_use_the_rootdir_relative_prefix():
    assert deselect_args(frozenset({"test_b", "test_a"})) == [
        f"--deselect={NODE_PREFIX}test_a",
        f"--deselect={NODE_PREFIX}test_b",
    ]


def test_deselect_args_actually_deselect_a_real_test():
    """A --deselect whose prefix is wrong deselects nothing and says nothing.
    This asks pytest itself, against the real suite file."""
    e2e = REPO_ROOT / "apps" / "agent" / "e2e"

    def collected(*extra: str) -> str:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "test_agent_e2e.py", "--collect-only", "-q", *extra],
            cwd=e2e, capture_output=True, text=True, check=True,
        ).stdout
        return out.strip().splitlines()[-1]

    real_test = "test_agent_zero_configuration_discovery_import_and_replay"
    assert "(1 deselected)" in collected(*deselect_args(frozenset({real_test}))), collected()


# ── workflow wiring ─────────────────────────────────────────────────────────
def _composed() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((REPO_ROOT / ".github/workflows/composed-e2e.yml").read_text(encoding="utf-8"))


def test_the_journey_cannot_start_without_the_guard():
    jobs = _composed()["jobs"]
    assert jobs["composed-journey"]["needs"] == "rerun-guard"
    assert jobs["rerun-guard"]["permissions"] == {"actions": "read", "contents": "read"}


def test_the_verdict_is_named_by_the_guards_fingerprint():
    steps = _composed()["jobs"]["composed-journey"]["steps"]
    upload = next(s for s in steps if s.get("name") == "Upload the verdict")
    assert upload["with"]["name"] == ARTIFACT_PREFIX + "${{ needs.rerun-guard.outputs.fingerprint }}"
    assert "steps.journey.outcome != 'skipped'" in upload["if"]


def test_the_journey_step_times_out_before_the_job_does():
    job = _composed()["jobs"]["composed-journey"]
    step = next(s for s in job["steps"] if s.get("id") == "journey")
    assert step["timeout-minutes"] < job["timeout-minutes"]


def test_the_guard_has_no_force_switch():
    """Maintainer decision 2026-09-27: no override input."""
    triggers = _composed().get("on", _composed().get(True))
    assert set(triggers["workflow_call"]["inputs"]) == {"ref", "quarantined"}
