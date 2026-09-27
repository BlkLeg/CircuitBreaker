#!/usr/bin/env python3
"""The composed journey never runs twice on the same inputs with its failures unaddressed.

Maintainer decision, 2026-09-27 (Tier 2 slice A2 plan). Every real run records
a verdict artifact named after a fingerprint of the suite's inputs. The next
run looks up the verdict for its own fingerprint and refuses to start when that
verdict failed and the failures were neither

  fixed        — anything under SUITE_INPUTS changed, so the fingerprint is new
                 and there is no verdict to find, or
  quarantined  — every failed test has a live register row for CHECK, which the
                 journey then deselects (`deselect`).

These are the two outcomes CLAUDE.md rule 2 permits. There is deliberately no
force switch.

Two limits, stated rather than hidden:

  - "Never runs twice" is best-effort across concurrent runs on the same
    fingerprint. Two runs can both pass the guard before either records a
    verdict. tier2.yml's concurrency group serialises its own runs, but
    e2e.yml's tag and pull-request runs are outside it.
  - Verdict artifacts are retained for 90 days. After that the verdict is gone
    and an unaddressed failure may run once more, which records a fresh one.

Only verdicts from this repository's own runs count. The artifact listing's
`workflow_run.head_repository_id` is a first pass; each candidate's run is then
fetched and must have head_repository.full_name == repository.full_name
(`run_is_same_repo`), so a fork's pull_request run cannot plant a verdict.

Subcommands:
  fingerprint  print the fingerprint of HEAD's suite inputs
  check        fetch the previous verdict (gh api) and exit 1 if unaddressed
  record       write this run's verdict from JUnit and the step outcome
  deselect     print one --deselect argument per quarantined test

Runs on the runner's system Python (3.10 on ubuntu-22.04).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quarantine_notice import REGISTER, RegisterError, rows_for_check

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = "Composed Agent E2E / composed-journey"
# pytest.ini at the repo root makes node ids rootdir-relative. A bare
# `test_agent_e2e.py::` prefix deselects nothing, silently.
NODE_PREFIX = "apps/agent/e2e/test_agent_e2e.py::"
ARTIFACT_PREFIX = "composed-journey-verdict-"

# What the journey exercises: the agent and its E2E harness, the backend, the
# suite's own invocation, and every build-context path Dockerfile.mono's
# COPY/ADD instructions read from — enumerated, not guessed:
# test_every_dockerfile_mono_copy_source_is_a_suite_input_or_frontend parses
# the Dockerfile itself and fails if a COPY source is added here without a
# matching entry. A change under any of these counts as an attempt to fix a
# failure.
#
# apps/frontend is the one deliberate exception, even though the mono image
# DOES contain it (Dockerfile.mono's frontend-builder stage bakes its build
# into the same runtime tree as everything else here): the journey drives the
# API, never the UI, so a frontend-caused crash still records as fix-only and
# a frontend-only commit never counts as a fix on its own. Without that
# exception, the daily UI commits on dev would each change the fingerprint and
# let a known agent failure re-run every night, defeating maintainer
# decision 2.
SUITE_INPUTS: tuple[str, ...] = (
    ".github/workflows/composed-e2e.yml",
    "Dockerfile.mono",
    "VERSION",
    "apps/agent",
    "apps/backend",
    "cb",
    "deploy",
    "docker",
    "docker-compose.yml",
    "packaging",
    "pytest.ini",
    "scripts/ci/lib/common.sh",
    "scripts/ci/tier2-agent-journey.sh",
    "scripts/pbs_tree.py",
)

_OUTCOMES = ("success", "failure")


@dataclass(frozen=True)
class Verdict:
    """One real run of the journey, keyed by the inputs it ran on."""

    fingerprint: str
    sha: str
    run_url: str
    outcome: str
    failed_tests: tuple[str, ...]

    def to_json(self) -> str:
        """Serialise for the verdict artifact."""
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> Verdict:
        """Parse a verdict artifact. Anything malformed raises ValueError: an
        unreadable verdict is a gate that did not evaluate, never a pass."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"verdict is not JSON: {exc.msg}") from exc
        if not isinstance(data, dict):
            # ValueError, not TypeError (TRY004): every malformed-verdict path in
            # this method raises ValueError by contract — callers catch one type.
            raise ValueError("verdict is not a JSON object")  # noqa: TRY004
        try:
            verdict = cls(
                fingerprint=str(data["fingerprint"]),
                sha=str(data["sha"]),
                run_url=str(data["run_url"]),
                outcome=str(data["outcome"]),
                failed_tests=tuple(str(name) for name in data["failed_tests"]),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"verdict is missing or mistypes a field: {exc}") from exc
        if verdict.outcome not in _OUTCOMES:
            raise ValueError(f"verdict outcome {verdict.outcome!r} is not one of {_OUTCOMES}")
        return verdict


def git_listing(root: Path, rev: str = "HEAD") -> str:
    """Return `git ls-tree -r` of SUITE_INPUTS at `rev`: blob ids and paths, content-addressed."""
    return subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--full-tree", rev, "--", *SUITE_INPUTS],
        capture_output=True, text=True, check=True,
    ).stdout


def fingerprint(listing: str) -> str:
    """Return a short, stable digest of a `git_listing`."""
    return hashlib.sha256(listing.encode("utf-8")).hexdigest()[:16]


def quarantined_tests(register: Path, today: date) -> frozenset[str]:
    """Return the test names that live register rows for CHECK quarantine. A row is live through its expiry day."""
    names: set[str] = set()
    for row in rows_for_check(register, CHECK):
        try:
            expiry = date.fromisoformat(row["expiry"].strip())
        except ValueError as exc:
            raise RegisterError(f"{row['quarantine_id']}: unparseable expiry {row['expiry']!r}") from exc
        if expiry >= today:
            names.update(name.strip() for name in row["scope"].split(",") if name.strip())
    return frozenset(names)


def failed_tests_from_junit(path: Path) -> list[str]:
    """Return the sorted names of test cases with a <failure> or <error>.

    A missing file means none were recorded. So does one that exists but will
    not parse: a job killed mid-write (a timeout, an OOM) can leave
    junit-agent-e2e.xml truncated, and ET.ParseError escaping from here would
    crash `record` before it writes a verdict at all — which fails open, since
    the next run finds no verdict and simply proceeds. Reporting zero
    test-level failures instead means `record` still writes outcome=failure
    with failed_tests=(), the same "crash, not a named failure" verdict
    decide() already requires a suite-input change to clear.
    """
    if not path.is_file():
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        print(
            f"::warning::{path} exists but did not parse as XML ({exc}); "
            "treating it as no test-level failures recorded",
            file=sys.stderr,
        )
        return []
    failed = {
        case.get("name", "")
        for case in root.iter("testcase")
        if case.find("failure") is not None or case.find("error") is not None
    }
    return sorted(name for name in failed if name)


def _base(name: str) -> str:
    return name.split("[", 1)[0]


def decide(previous: Verdict | None, quarantined: frozenset[str]) -> tuple[bool, str]:
    """Return (allowed, reason) for running the journey after `previous` on the same inputs."""
    if previous is None:
        return True, "no earlier verdict for these inputs"
    if previous.outcome == "success":
        return True, f"last run on these inputs passed: {previous.run_url}"
    if not previous.failed_tests:
        return False, (
            f"{previous.run_url} failed with no test-level failure recorded (a crash or timeout); "
            "only a change to the suite's inputs addresses it"
        )
    unaddressed = [name for name in previous.failed_tests if _base(name) not in quarantined]
    if unaddressed:
        return False, (
            f"failures from {previous.run_url} are unaddressed: {', '.join(unaddressed)}; "
            f"fix them (any change under {', '.join(SUITE_INPUTS)}) or quarantine them "
            f"(a register row for {CHECK!r} naming each test)"
        )
    return True, f"all failures from {previous.run_url} are quarantined: {', '.join(previous.failed_tests)}"


def merge_artifact_pages(pages: list[Mapping[str, object]]) -> dict[str, object]:
    """Merge every page of a `gh api --paginate --slurp` artifact listing into one.

    Raises ValueError when the merged artifact count falls short of the first
    page's `total_count`. `gh api ...&per_page=100` alone reads only page 1: the
    artifacts API lists every run in the repository, including `pull_request`
    runs from forks, and a fork can upload any number of its own artifacts
    under the same (public, computable) verdict name. Enough of those crowd
    the real verdict off page 1, and `pick_verdict_artifact` would then see a
    listing that looks complete but is missing the one artifact that matters —
    `check` would report "no earlier verdict" and let an unaddressed failure
    re-run. A short count is the one signal that distinguishes that case from
    an actually-empty listing, so it is treated as failure, not as "found
    nothing".
    """
    merged: list[object] = []
    for page in pages:
        artifacts = page.get("artifacts")
        if isinstance(artifacts, list):
            merged.extend(artifacts)
    total_count = pages[0].get("total_count") if pages else 0
    if isinstance(total_count, int) and len(merged) < total_count:
        raise ValueError(
            f"artifact listing incomplete: the API reported {total_count} artifact(s) "
            f"but only {len(merged)} came back across {len(pages)} page(s)"
        )
    return {"total_count": total_count, "artifacts": merged}


def verdict_candidates(listing: Mapping[str, object], repo_id: int) -> list[dict[str, object]]:
    """Return unexpired verdict artifacts whose run claims THIS repository as head, newest first.

    `workflow_run.head_repository_id` is only a first pass: whether a fork's
    pull_request run reports the fork's id there is not verified, so every
    candidate is re-checked against its run (`verified_verdict_artifact`).
    """
    artifacts = listing.get("artifacts")
    if not isinstance(artifacts, list):
        return []
    trusted = [
        artifact for artifact in artifacts
        if isinstance(artifact, dict)
        and not artifact.get("expired")
        and (artifact.get("workflow_run") or {}).get("head_repository_id") == repo_id
    ]
    return sorted(trusted, key=lambda artifact: str(artifact["created_at"]), reverse=True)


def pick_verdict_artifact(listing: Mapping[str, object], repo_id: int) -> dict[str, object] | None:
    """Return the newest first-pass candidate (`verdict_candidates`), or None."""
    candidates = verdict_candidates(listing, repo_id)
    return candidates[0] if candidates else None


def _full_name(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    name = value.get("full_name")
    return name if isinstance(name, str) and name else None


def run_is_same_repo(run: Mapping[str, object]) -> bool:
    """True only when a workflow run's head repository IS the repository it ran in.

    A fork's pull_request run has head_repository = the fork. A run missing
    either name is not trusted: that fails closed, towards "not our verdict".
    """
    head = _full_name(run.get("head_repository"))
    repo = _full_name(run.get("repository"))
    return head is not None and repo is not None and head == repo


def verified_verdict_artifact(
    candidates: Sequence[Mapping[str, object]],
    fetch_run: Callable[[int], Mapping[str, object]],
) -> Mapping[str, object] | None:
    """Return the first candidate whose run `run_is_same_repo`, or None.

    `fetch_run` returns `repos/{repo}/actions/runs/{id}`. Its errors propagate:
    an API failure is a lookup that did not answer, never "no verdict".
    """
    for artifact in candidates:
        workflow_run = artifact.get("workflow_run")
        run_id = workflow_run.get("id") if isinstance(workflow_run, Mapping) else None
        if not isinstance(run_id, int):
            # ValueError (TRY004): `check` turns ValueError into a closed ::error::.
            raise ValueError(f"verdict artifact {artifact.get('name')!r} has no workflow_run.id to verify")  # noqa: TRY004
        if run_is_same_repo(fetch_run(run_id)):
            return artifact
        print(
            f"::warning::skipping verdict artifact from run {run_id}: its head repository is not this repository",
            file=sys.stderr,
        )
    return None


def deselect_args(quarantined: frozenset[str]) -> list[str]:
    """Return one pytest --deselect argument per quarantined test, sorted."""
    return [f"--deselect={NODE_PREFIX}{name}" for name in sorted(quarantined)]


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _gh_api(path: str) -> bytes:
    return subprocess.run(["gh", "api", path], capture_output=True, check=True).stdout


def _gh_api_paginated(path: str) -> list[Mapping[str, object]]:
    """Every page of `path`, via `gh api --paginate --slurp` (a JSON array of page objects)."""
    raw = subprocess.run(["gh", "api", "--paginate", "--slurp", path], capture_output=True, check=True).stdout
    pages = json.loads(raw)
    if not isinstance(pages, list):
        # ValueError, not TypeError (TRY004): `check`'s ValueError handler is
        # what turns this into a clear ::error:: instead of a bare traceback.
        raise ValueError(f"gh api --slurp did not return a JSON array for {path}")  # noqa: TRY004
    return pages


def _gh_api_json(path: str) -> Mapping[str, object]:
    data = json.loads(_gh_api(path))
    if not isinstance(data, dict):
        raise ValueError(f"gh api did not return a JSON object for {path}")  # noqa: TRY004
    return data


def _fetch_previous(repo: str, repo_id: int, fp: str) -> Verdict | None:
    pages = _gh_api_paginated(f"repos/{repo}/actions/artifacts?name={ARTIFACT_PREFIX}{fp}&per_page=100")
    listing = merge_artifact_pages(pages)
    artifact = verified_verdict_artifact(
        verdict_candidates(listing, repo_id),
        lambda run_id: _gh_api_json(f"repos/{repo}/actions/runs/{run_id}"),
    )
    if artifact is None:
        return None
    archive = zipfile.ZipFile(io.BytesIO(_gh_api(str(artifact["archive_download_url"]))))
    return Verdict.from_json(archive.read("verdict.json").decode("utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand and return its exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fingerprint")
    sub.add_parser("check")
    record = sub.add_parser("record")
    record.add_argument("--junit", type=Path, required=True)
    record.add_argument("--out", type=Path, required=True)
    sub.add_parser("deselect")
    args = parser.parse_args(argv)

    if args.command == "fingerprint":
        print(fingerprint(git_listing(REPO_ROOT)))
        return 0
    if args.command == "deselect":
        quarantined = quarantined_tests(REGISTER, _today())
        if quarantined:
            print(f"quarantined, deselected: {', '.join(sorted(quarantined))}", file=sys.stderr)
        for arg in deselect_args(quarantined):
            print(arg)
        return 0
    if args.command == "record":
        verdict = Verdict(
            fingerprint=os.environ["FINGERPRINT"],
            # The checked-out tree, not GITHUB_SHA: on a nightly those differ (D2).
            sha=subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip(),
            run_url=os.environ["RUN_URL"],
            outcome="success" if os.environ["OUTCOME"] == "success" else "failure",
            failed_tests=tuple(failed_tests_from_junit(args.junit)),
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(verdict.to_json(), encoding="utf-8")
        print(verdict.to_json())
        return 0
    # check
    fp = fingerprint(git_listing(REPO_ROOT))
    try:
        previous = _fetch_previous(os.environ["REPO"], int(os.environ["REPO_ID"]), fp)
    except ValueError as exc:
        # An incomplete artifact listing (merge_artifact_pages) or a verdict
        # artifact that won't parse (Verdict.from_json) both mean the lookup
        # did not answer trustworthily. Failing closed here, with a specific
        # reason, is what stops either case from being read as "no earlier
        # verdict" and letting an unaddressed failure re-run.
        print(f"::error::rerun guard could not read the previous verdict: {exc}")
        return 1
    if previous is not None and previous.fingerprint != fp:
        print(f"::error::verdict artifact for {fp} records fingerprint {previous.fingerprint}")
        return 1
    allowed, reason = decide(previous, quarantined_tests(REGISTER, _today()))
    print(f"inputs fingerprint: {fp}")
    if allowed:
        print(f"rerun guard: allowed — {reason}")
        return 0
    print(f"::error::Composed journey NOT RUN — {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
