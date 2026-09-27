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
from collections.abc import Mapping, Sequence
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

# What the journey exercises: the agent and its E2E harness, the backend and
# the mono image it runs in, and the suite's own invocation. A change under any
# of these counts as an attempt to fix a failure. apps/frontend is left out on
# purpose: the journey drives the API, and counting every UI commit as a "fix"
# would let a known failure re-run nightly on dev.
SUITE_INPUTS: tuple[str, ...] = (
    ".github/workflows/composed-e2e.yml",
    "Dockerfile.mono",
    "apps/agent",
    "apps/backend",
    "docker",
    "scripts/ci/tier2-agent-journey.sh",
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
    """Return the sorted names of test cases with a <failure> or <error>. A missing file means none were recorded."""
    if not path.is_file():
        return []
    failed = {
        case.get("name", "")
        for case in ET.parse(path).getroot().iter("testcase")
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


def pick_verdict_artifact(listing: Mapping[str, object], repo_id: int) -> dict[str, object] | None:
    """Return the newest unexpired verdict artifact produced by a run of THIS repository, or None."""
    artifacts = listing.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    trusted = [
        artifact for artifact in artifacts
        if isinstance(artifact, dict)
        and not artifact.get("expired")
        and (artifact.get("workflow_run") or {}).get("head_repository_id") == repo_id
    ]
    return max(trusted, key=lambda artifact: str(artifact["created_at"]), default=None)


def deselect_args(quarantined: frozenset[str]) -> list[str]:
    """Return one pytest --deselect argument per quarantined test, sorted."""
    return [f"--deselect={NODE_PREFIX}{name}" for name in sorted(quarantined)]


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _gh_api(path: str) -> bytes:
    return subprocess.run(["gh", "api", path], capture_output=True, check=True).stdout


def _fetch_previous(repo: str, repo_id: int, fp: str) -> Verdict | None:
    listing = json.loads(_gh_api(f"repos/{repo}/actions/artifacts?name={ARTIFACT_PREFIX}{fp}&per_page=100"))
    artifact = pick_verdict_artifact(listing, repo_id)
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
    previous = _fetch_previous(os.environ["REPO"], int(os.environ["REPO_ID"]), fp)
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
