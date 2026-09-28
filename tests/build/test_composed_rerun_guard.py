"""The composed journey never runs twice on the same inputs with its failures unaddressed."""

from __future__ import annotations

import json
import re
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
    TEST_FILE,
    Verdict,
    collect_node_ids,
    decide,
    deselect_args,
    failed_tests_from_junit,
    fingerprint,
    git_listing,
    merge_artifact_pages,
    pick_verdict_artifact,
    quarantined_tests,
    run_is_same_repo,
    verdict_candidates,
    verified_verdict_artifact,
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


# `--from=<stage>` copies an earlier build stage's output, never a path from
# the build context, so those lines carry nothing SUITE_INPUTS needs to cover.
_DOCKERFILE_COPY_RE = re.compile(r"^\s*(?:COPY|ADD)\s+(.*)$")


def _dockerfile_copy_sources(text: str) -> list[str]:
    """Every build-context path a Dockerfile's COPY/ADD instructions read from."""
    sources: list[str] = []
    for line in text.splitlines():
        match = _DOCKERFILE_COPY_RE.match(line)
        if not match:
            continue
        tokens = match.group(1).split()
        if any(token.startswith("--from=") for token in tokens):
            continue
        tokens = [token for token in tokens if not token.startswith("--")]
        if len(tokens) < 2:  # a destination-only or malformed line: nothing to check
            continue
        sources.extend(tokens[:-1])  # the last token is always the destination
    return sources


def test_every_dockerfile_mono_copy_source_is_a_suite_input_or_frontend():
    """The image the journey exercises is built from Dockerfile.mono's COPY/ADD
    sources. Enumerated from the file itself rather than guessed, so a source
    added later without a matching SUITE_INPUTS entry is caught here, not
    discovered as a rerun that silently fingerprinted nothing new."""
    sources = _dockerfile_copy_sources((REPO_ROOT / "Dockerfile.mono").read_text(encoding="utf-8"))
    assert sources, "no COPY/ADD sources found — Dockerfile.mono changed shape; update the parser"
    uncovered = []
    for source in sources:
        source = source.rstrip("/")
        if source == "apps/frontend" or source.startswith("apps/frontend/"):
            continue  # excluded on purpose: see the comment above SUITE_INPUTS
        covered = any(source == inp or source.startswith(f"{inp.rstrip('/')}/") for inp in SUITE_INPUTS)
        if not covered:
            uncovered.append(source)
    assert not uncovered, f"Dockerfile.mono COPYs from paths not in SUITE_INPUTS: {uncovered}"


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


def test_a_truncated_junit_means_no_test_level_failures_not_a_crash(tmp_path):
    """A killed `Run the composed journey` step can leave junit-agent-e2e.xml
    truncated mid-write. `record` must still produce a verdict (outcome=failure,
    failed_tests=()) rather than raising ET.ParseError and uploading nothing —
    an unrecorded run is indistinguishable from "no earlier verdict", which
    would let the next run start on a failure nobody addressed."""
    junit = tmp_path / "junit.xml"
    junit.write_text('<testsuites><testsuite><testcase name="test_x">', encoding="utf-8")
    assert failed_tests_from_junit(junit) == []


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
def _artifact(created: str, repo_id: int = 7, expired: bool = False, run_id: int = 1) -> dict:
    return {
        "name": ARTIFACT_PREFIX + "fp",
        "created_at": created,
        "expired": expired,
        "archive_download_url": f"https://api.invalid/{created}",
        "workflow_run": {"id": run_id, "head_repository_id": repo_id},
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


# ── run verification: head_repository_id alone is not trusted ───────────────
def _run(head: str | None, repo: str | None) -> dict:
    run: dict = {}
    if head is not None:
        run["head_repository"] = {"full_name": head}
    if repo is not None:
        run["repository"] = {"full_name": repo}
    return run


def test_a_same_repo_run_is_trusted():
    assert run_is_same_repo(_run("BlkLeg/circuitbreaker", "BlkLeg/circuitbreaker")) is True


def test_a_fork_run_is_not_trusted():
    assert run_is_same_repo(_run("someone/circuitbreaker", "BlkLeg/circuitbreaker")) is False


@pytest.mark.parametrize(
    "run",
    [
        _run(None, "BlkLeg/circuitbreaker"),
        _run("BlkLeg/circuitbreaker", None),
        _run(None, None),
        {"head_repository": None, "repository": {"full_name": "BlkLeg/circuitbreaker"}},
        {"head_repository": {"full_name": ""}, "repository": {"full_name": ""}},
        {"head_repository": {"full_name": 7}, "repository": {"full_name": 7}},
    ],
)
def test_a_run_missing_either_repository_is_not_trusted(run):
    assert run_is_same_repo(run) is False


def test_candidates_are_newest_first_and_prefiltered_by_repo_id():
    listing = {"artifacts": [
        _artifact("2026-09-25T00:00:00Z", run_id=1),
        _artifact("2026-09-27T00:00:00Z", repo_id=999, run_id=2),
        _artifact("2026-09-26T00:00:00Z", run_id=3),
        _artifact("2026-09-26T06:00:00Z", expired=True, run_id=4),
    ]}
    assert [a["workflow_run"]["id"] for a in verdict_candidates(listing, 7)] == [3, 1]


def test_verification_skips_a_candidate_whose_run_is_a_fork():
    listing = {"artifacts": [_artifact("2026-09-26T00:00:00Z", run_id=10), _artifact("2026-09-25T00:00:00Z", run_id=11)]}
    runs = {10: _run("fork/cb", "BlkLeg/cb"), 11: _run("BlkLeg/cb", "BlkLeg/cb")}
    chosen = verified_verdict_artifact(verdict_candidates(listing, 7), runs.__getitem__)
    assert chosen is not None and chosen["workflow_run"]["id"] == 11


def test_skip_warning_names_no_run_id_only_a_count(capsys):
    """CodeQL (py/clear-text-logging-sensitive-data): the warning for a
    foreign-repo run must be a fixed label plus our own len() count, never
    the run id or any other value read from the API response."""
    foreign_run_id = 918273645
    listing = {"artifacts": [_artifact("2026-09-26T00:00:00Z", run_id=foreign_run_id), _artifact("2026-09-25T00:00:00Z", run_id=11)]}
    runs = {foreign_run_id: _run("fork/cb", "BlkLeg/cb"), 11: _run("BlkLeg/cb", "BlkLeg/cb")}
    chosen = verified_verdict_artifact(verdict_candidates(listing, 7), runs.__getitem__)
    assert chosen is not None and chosen["workflow_run"]["id"] == 11
    err = capsys.readouterr().err
    assert str(foreign_run_id) not in err
    assert err == "::warning::skipped 1 verdict artifact(s) whose run is not from this repository\n"


def test_no_surviving_candidate_means_no_previous_verdict():
    listing = {"artifacts": [_artifact("2026-09-26T00:00:00Z", run_id=10)]}
    assert verified_verdict_artifact(verdict_candidates(listing, 7), lambda _run_id: _run("fork/cb", "BlkLeg/cb")) is None


def test_the_newest_verified_candidate_stops_the_search():
    seen: list[int] = []

    def fetch(run_id: int) -> dict:
        seen.append(run_id)
        return _run("BlkLeg/cb", "BlkLeg/cb")

    listing = {"artifacts": [_artifact("2026-09-25T00:00:00Z", run_id=1), _artifact("2026-09-26T00:00:00Z", run_id=2)]}
    assert verified_verdict_artifact(verdict_candidates(listing, 7), fetch)["workflow_run"]["id"] == 2
    assert seen == [2]


def test_an_api_error_while_verifying_propagates():
    def fetch(run_id: int) -> dict:
        raise subprocess.CalledProcessError(1, ["gh", "api", f"runs/{run_id}"])

    listing = {"artifacts": [_artifact("2026-09-26T00:00:00Z")]}
    with pytest.raises(subprocess.CalledProcessError):
        verified_verdict_artifact(verdict_candidates(listing, 7), fetch)


def test_a_candidate_without_a_run_id_is_an_error_not_a_skip():
    artifact = _artifact("2026-09-26T00:00:00Z")
    del artifact["workflow_run"]["id"]
    with pytest.raises(ValueError):
        verified_verdict_artifact([artifact], lambda _run_id: _run("BlkLeg/cb", "BlkLeg/cb"))


# ── pagination: a fork cannot crowd the real verdict off page 1 ─────────────
def test_merge_artifact_pages_combines_every_page():
    page1 = {"total_count": 3, "artifacts": [_artifact("2026-09-25T00:00:00Z")]}
    page2 = {"total_count": 3, "artifacts": [_artifact("2026-09-26T00:00:00Z"), _artifact("2026-09-27T00:00:00Z")]}
    merged = merge_artifact_pages([page1, page2])
    assert len(merged["artifacts"]) == 3
    assert pick_verdict_artifact(merged, 7)["created_at"] == "2026-09-27T00:00:00Z"


def test_merge_artifact_pages_raises_when_the_api_reports_more_than_it_returned():
    """total_count > len(merged artifacts) means the listing is partial — the
    exact shape a page of fork-uploaded decoys crowding the real artifact off
    page 1 would produce. Silently treating that as complete is the fail-open
    this guards against."""
    page = {"total_count": 5, "artifacts": [_artifact("2026-09-25T00:00:00Z")]}
    with pytest.raises(ValueError):
        merge_artifact_pages([page])


def test_merge_artifact_pages_accepts_an_empty_listing():
    assert merge_artifact_pages([]) == {"total_count": 0, "artifacts": []}
    empty = merge_artifact_pages([{"total_count": 0, "artifacts": []}])
    assert empty["artifacts"] == []


@pytest.mark.parametrize(
    "page",
    [
        {"artifacts": []},
        {"total_count": None, "artifacts": []},
        {"total_count": "3", "artifacts": []},
        {"total_count": 1.0, "artifacts": [_artifact("2026-09-25T00:00:00Z")]},
    ],
)
def test_merge_artifact_pages_fails_closed_on_a_missing_or_non_int_total_count(page):
    """A page with no usable total_count must not be read as 'nothing more to
    check': that is exactly the shape a listing corrupted or truncated before
    total_count was ever set would have, and treating it as complete would
    let check() report 'no earlier verdict' on a listing it never actually
    saw all of."""
    with pytest.raises(ValueError):
        merge_artifact_pages([page])


# ── deselection really deselects, exactly ───────────────────────────────────
def test_deselect_args_matches_by_exact_node_id_not_by_string_prefix():
    """pytest's --deselect drops any node id that STARTS WITH the given string.
    A register row naming `test_agent_update` must not also deselect the
    longer, unrelated `test_agent_update_success_and_forced_rollback` just
    because one name is a prefix of the other."""
    node_ids = ["apps/agent/e2e/test_agent_e2e.py::test_agent_update_success_and_forced_rollback"]
    assert deselect_args(frozenset({"test_agent_update"}), node_ids) == []


def test_deselect_args_matches_a_parametrised_id_by_base_name():
    node_ids = ["mod.py::test_x[a]", "mod.py::test_x[b]", "mod.py::test_y"]
    assert deselect_args(frozenset({"test_x"}), node_ids) == [
        "--deselect=mod.py::test_x[a]",
        "--deselect=mod.py::test_x[b]",
    ]


def test_deselect_args_and_decide_use_the_same_base_name_rule():
    """decide() strips `[params]` via _base before comparing to the register;
    deselect must normalise the same way, or a parametrised failure could be
    judged 'addressed' by decide() while its node id still runs."""
    assert decide(_verdict("failure", "test_x[a]"), frozenset({"test_x"}))[0]
    assert deselect_args(frozenset({"test_x"}), ["mod.py::test_x[a]"]) == ["--deselect=mod.py::test_x[a]"]


def test_collect_node_ids_reads_real_pytest_collection(tmp_path):
    """A synthetic pytest project: collect_node_ids actually runs pytest
    --collect-only and returns only the ids it reports for the named file —
    never a guessed or constructed name."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n"
        "\n"
        "def test_agent_update_success_and_forced_rollback():\n"
        "    assert True\n"
        "\n"
        "@pytest.mark.parametrize('n', [1, 2])\n"
        "def test_x(n):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    assert collect_node_ids(tmp_path / "test_sample.py") == [
        "test_sample.py::test_agent_update_success_and_forced_rollback",
        "test_sample.py::test_x[1]",
        "test_sample.py::test_x[2]",
    ]


def test_a_scope_naming_a_prefix_does_not_deselect_the_longer_real_test(tmp_path):
    """The exact defect this guards against, end to end against real pytest
    collection: a register row naming `test_agent_update` must not deselect
    `test_agent_update_success_and_forced_rollback`."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_sample.py").write_text(
        "def test_agent_update_success_and_forced_rollback():\n    assert True\n",
        encoding="utf-8",
    )
    ids = collect_node_ids(tmp_path / "test_sample.py")
    assert deselect_args(frozenset({"test_agent_update"}), ids) == []


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
    node_ids = collect_node_ids(TEST_FILE)
    assert "(1 deselected)" in collected(*deselect_args(frozenset({real_test}), node_ids)), collected()


def test_deselect_args_against_the_real_suite_gets_exactly_the_register_rows():
    """The existing real-suite deselect test still gets 3 deselected."""
    quarantined = quarantined_tests(REPO_ROOT / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv", TODAY)
    node_ids = collect_node_ids(TEST_FILE)
    args = deselect_args(quarantined, node_ids)
    assert len(quarantined) == 3
    assert len(args) == 3


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


def test_the_verdict_is_recorded_only_when_the_journey_ran():
    """An install step failing before `Run the composed journey` is an
    infrastructure problem, not a verdict on these inputs — recording one
    anyway would let an unrelated pip failure look like a suite failure the
    next run then has to address."""
    steps = _composed()["jobs"]["composed-journey"]["steps"]
    record = next(s for s in steps if s.get("name") == "Record the verdict for these inputs")
    assert "!cancelled()" in record["if"]
    assert "steps.journey.outcome != 'skipped'" in record["if"]


def test_the_journey_step_times_out_before_the_job_does():
    job = _composed()["jobs"]["composed-journey"]
    step = next(s for s in job["steps"] if s.get("id") == "journey")
    assert step["timeout-minutes"] < job["timeout-minutes"]


def test_the_guard_has_no_force_switch():
    """Maintainer decision 2026-09-27: no override input."""
    triggers = _composed().get("on", _composed().get(True))
    assert set(triggers["workflow_call"]["inputs"]) == {"ref", "quarantined"}


def test_the_journey_tests_exactly_the_tree_the_guard_fingerprinted():
    """`ref` can be a moving branch (the nightly passes `dev`). Two separate
    checkouts of it could land on two commits, recording tree B's result under
    tree A's fingerprint — failing open. The guard publishes the SHA it
    fingerprinted, and the journey checks out that SHA."""
    jobs = _composed()["jobs"]
    guard = jobs["rerun-guard"]
    assert guard["outputs"]["sha"] == "${{ steps.fingerprint.outputs.sha }}"
    fp_run = next(s for s in guard["steps"] if s.get("id") == "fingerprint")["run"]
    assert re.search(r'^\s*sha="\$\(git rev-parse HEAD\)"\s*$', fp_run, re.MULTILINE), fp_run
    assert 'echo "sha=${sha}" >> "$GITHUB_OUTPUT"' in fp_run
    checkouts = [
        s for s in jobs["composed-journey"]["steps"] if str(s.get("uses", "")).startswith("actions/checkout")
    ]
    assert [s["with"]["ref"] for s in checkouts] == ["${{ needs.rerun-guard.outputs.sha }}"]


def test_the_run_manifest_records_the_tested_sha_not_only_the_triggering_one():
    """The job checks out `needs.rerun-guard.outputs.sha`, which is the SHA the
    guard fingerprinted and the tree the suite actually runs against — not
    `GITHUB_SHA`, which on a scheduled or ref-redirected run (the nightly
    passes `ref: dev`) is the commit that triggered the *workflow*, not the
    one under test. The manifest must record both: `commit=` so nothing that
    already reads it breaks, and `tested_commit=` so a reader can tell which
    tree the suite actually exercised."""
    steps = _composed()["jobs"]["composed-journey"]["steps"]
    manifest = next(s for s in steps if s.get("name") == "Record the run manifest")["run"]
    assert 'echo "commit=${GITHUB_SHA}"' in manifest
    assert re.search(r'^\s*tested_commit="\$\(git rev-parse HEAD\)"\s*$', manifest, re.MULTILINE), manifest
    assert 'echo "tested_commit=${tested_commit}"' in manifest
