#!/usr/bin/env python3
"""Delete remote branches that are merged, idle and not under review.

Run weekly by `.github/workflows/branch-cleanup.yml`. A branch is deleted only
when ALL of these hold, checked in this order (cheapest first, so most
branches cost no API call beyond the listings):

1. it is not a long-lived branch (`main`, `dev`, `gh-pages`);
2. no open pull request in this repository has it as its head — nor as its
   base, since deleting the base of a stacked PR closes that PR;
3. its head commit is older than ``--min-age-days`` (default 14);
4. its head commit is fully contained in `main` or in `dev` — the compare API
   reports ``ahead_by == 0`` for ``<base>...<head sha>``, i.e. the branch
   carries no commit that the base does not already have.

Every branch gets exactly one logged decision line, deleted or kept, with the
reason. Containment is evaluated against the head SHA captured at the start,
and the branch is re-read immediately before deletion: if it moved in between,
it is kept rather than deleted on the strength of a stale evaluation.

Usage::

    branch_cleanup.py --repo OWNER/NAME [--dry-run] [--min-age-days N]

All GitHub access goes through the ``gh`` CLI (``gh api``), which reads its
token from ``GH_TOKEN``. The selection logic is independent of it
(:func:`evaluate` takes any :class:`GitHubClient`), which is what the unit
tests in ``tests/build/test_branch_cleanup.py`` exercise with fixture data.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import quote

PROTECTED_BRANCHES: frozenset[str] = frozenset({"main", "dev", "gh-pages"})
CONTAINMENT_BASES: tuple[str, ...] = ("main", "dev")
DEFAULT_MIN_AGE_DAYS = 14


@dataclass(frozen=True)
class BranchHead:
    """The commit a branch points at, and when that commit was made."""

    sha: str
    committed_at: datetime


@dataclass(frozen=True)
class Decision:
    """The outcome for one branch: whether to delete it, and why."""

    branch: str
    delete: bool
    reason: str
    sha: str | None = None


class GitHubClient(Protocol):
    """The GitHub reads and the one write the cleanup needs."""

    def list_branches(self) -> list[str]:
        """Names of every branch in the repository."""
        ...

    def open_pr_heads(self) -> set[str]:
        """Head branch names of open PRs whose head lives in this repository."""
        ...

    def open_pr_bases(self) -> set[str]:
        """Base branch names of open PRs."""
        ...

    def branch_head(self, branch: str) -> BranchHead:
        """The branch's current head commit."""
        ...

    def ahead_by(self, base: str, sha: str) -> int:
        """Commits reachable from ``sha`` that are not reachable from ``base``."""
        ...

    def delete_branch(self, branch: str) -> None:
        """Delete the branch ref."""
        ...


def parse_timestamp(value: str) -> datetime:
    """Parse a GitHub ISO-8601 timestamp (``2026-09-01T12:00:00Z``) as aware UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_branch_names(pages: list[Any]) -> list[str]:
    """Branch names from ``GET /repos/{r}/branches`` output (a list of pages)."""
    names: list[str] = []
    for page in pages:
        for branch in page:
            names.append(str(branch["name"]))
    return names


def parse_open_pr_heads(pages: list[Any], repo: str) -> set[str]:
    """Head refs of open PRs from ``GET /repos/{r}/pulls?state=open`` output.

    A PR from a fork names a branch in *another* repository; a same-named
    branch here is not protected by it, so only heads in ``repo`` count. A PR
    whose head repository was deleted has ``head.repo == null`` and is skipped
    for the same reason.
    """
    heads: set[str] = set()
    for page in pages:
        for pull in page:
            head = pull.get("head") or {}
            head_repo = head.get("repo") or {}
            if str(head_repo.get("full_name", "")).lower() == repo.lower():
                heads.add(str(head["ref"]))
    return heads


def parse_open_pr_bases(pages: list[Any]) -> set[str]:
    """Base refs of open PRs from ``GET /repos/{r}/pulls?state=open`` output.

    The base of a PR always lives in this repository.
    """
    return {str(pull["base"]["ref"]) for page in pages for pull in page}


def parse_branch_head(payload: dict[str, Any]) -> BranchHead:
    """The head commit from ``GET /repos/{r}/branches/{branch}``.

    Uses the committer date, not the author date: a rebased or cherry-picked
    commit keeps its old author date but was committed when it was rewritten,
    and it is the latest activity on the branch that the age rule is about.
    """
    commit = payload["commit"]
    return BranchHead(
        sha=str(commit["sha"]),
        committed_at=parse_timestamp(str(commit["commit"]["committer"]["date"])),
    )


def evaluate(
    branch: str,
    client: GitHubClient,
    open_heads: set[str],
    open_bases: set[str],
    now: datetime,
    min_age: timedelta,
) -> Decision:
    """Decide whether one branch is deleted, calling the API only as needed."""
    if branch in PROTECTED_BRANCHES:
        return Decision(branch, False, "keep: long-lived branch")
    if branch in open_heads:
        return Decision(branch, False, "keep: head of an open pull request")
    if branch in open_bases:
        return Decision(branch, False, "keep: base of an open pull request")

    head = client.branch_head(branch)
    age = now - head.committed_at
    if age < min_age:
        return Decision(
            branch,
            False,
            f"keep: last commit {head.committed_at.isoformat()} is younger than "
            f"{min_age.days} days",
            head.sha,
        )

    ahead: list[str] = []
    for base in CONTAINMENT_BASES:
        count = client.ahead_by(base, head.sha)
        if count == 0:
            return Decision(
                branch,
                True,
                f"delete: {head.sha[:12]} fully contained in {base}, last commit "
                f"{head.committed_at.isoformat()} ({age.days} days old)",
                head.sha,
            )
        ahead.append(f"{count} ahead of {base}")
    return Decision(branch, False, f"keep: not merged ({', '.join(ahead)})", head.sha)


def run(
    client: GitHubClient,
    now: datetime,
    min_age: timedelta,
    dry_run: bool,
    log: Callable[[str], None] = print,
) -> tuple[list[Decision], list[str]]:
    """Evaluate every branch and delete the selected ones unless ``dry_run``.

    Returns the decisions and the names of branches that could not be
    evaluated or deleted. A failure on one branch does not stop the others,
    and a branch that could not be evaluated is kept. A branch whose head
    moved since it was evaluated is kept and logged, never deleted.
    """
    open_heads = client.open_pr_heads()
    open_bases = client.open_pr_bases()
    decisions: list[Decision] = []
    failures: list[str] = []
    for branch in sorted(client.list_branches()):
        try:
            decision = evaluate(branch, client, open_heads, open_bases, now, min_age)
        except (subprocess.CalledProcessError, KeyError, ValueError, TypeError) as exc:
            decision = Decision(branch, False, f"keep: evaluation failed: {exc}")
            failures.append(branch)
        decisions.append(decision)
        if not decision.delete:
            log(f"{branch}: {decision.reason}")
            continue
        if dry_run:
            log(f"{branch}: {decision.reason} [dry run: not deleted]")
            continue
        try:
            current = client.branch_head(branch)
            if current.sha != decision.sha:
                log(
                    f"{branch}: keep: head moved to {current.sha[:12]} since evaluation"
                )
                continue
            client.delete_branch(branch)
        except (subprocess.CalledProcessError, KeyError, ValueError, TypeError) as exc:
            failures.append(branch)
            log(f"{branch}: ERROR: deletion failed: {exc}")
            continue
        log(f"{branch}: {decision.reason} [deleted]")
    return decisions, failures


class GhCliClient:
    """:class:`GitHubClient` backed by ``gh api`` subprocess calls."""

    def __init__(self, repo: str) -> None:
        """Bind the client to ``OWNER/NAME``."""
        self.repo = repo
        self._open_pulls: list[Any] | None = None

    def _api(self, *args: str) -> Any:
        """Run ``gh api`` and return its parsed JSON output (None if empty)."""
        result = subprocess.run(
            ["gh", "api", *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout) if result.stdout.strip() else None

    def _paginated(self, path: str) -> list[Any]:
        """Every page of a list endpoint, one JSON array per page."""
        pages = self._api("--paginate", "--slurp", path)
        return list(pages or [])

    def list_branches(self) -> list[str]:
        """Names of every branch in the repository."""
        return parse_branch_names(
            self._paginated(f"repos/{self.repo}/branches?per_page=100")
        )

    def _open_pull_pages(self) -> list[Any]:
        """The open-PR listing, fetched once and shared by heads and bases."""
        if self._open_pulls is None:
            self._open_pulls = self._paginated(
                f"repos/{self.repo}/pulls?state=open&per_page=100"
            )
        return self._open_pulls

    def open_pr_heads(self) -> set[str]:
        """Head branch names of open PRs whose head lives in this repository."""
        return parse_open_pr_heads(self._open_pull_pages(), self.repo)

    def open_pr_bases(self) -> set[str]:
        """Base branch names of open PRs."""
        return parse_open_pr_bases(self._open_pull_pages())

    def branch_head(self, branch: str) -> BranchHead:
        """The branch's current head commit."""
        return parse_branch_head(
            self._api(f"repos/{self.repo}/branches/{quote(branch, safe='/')}")
        )

    def ahead_by(self, base: str, sha: str) -> int:
        """Commits reachable from ``sha`` that are not reachable from ``base``."""
        payload = self._api(f"repos/{self.repo}/compare/{quote(base, safe='')}...{sha}")
        return int(payload["ahead_by"])

    def delete_branch(self, branch: str) -> None:
        """Delete the branch ref."""
        self._api(
            "-X",
            "DELETE",
            f"repos/{self.repo}/git/refs/heads/{quote(branch, safe='/')}",
        )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns 1 if any selected branch failed to delete."""
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None
    )
    parser.add_argument("--repo", required=True, help="OWNER/NAME")
    parser.add_argument(
        "--dry-run", action="store_true", help="log decisions, delete nothing"
    )
    parser.add_argument("--min-age-days", type=int, default=DEFAULT_MIN_AGE_DAYS)
    args = parser.parse_args(argv)
    if args.min_age_days < 1:
        parser.error("--min-age-days must be at least 1")

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"branch cleanup of {args.repo} ({mode}, min age {args.min_age_days} days)")
    decisions, failures = run(
        GhCliClient(args.repo),
        now=datetime.now(UTC),
        min_age=timedelta(days=args.min_age_days),
        dry_run=args.dry_run,
    )
    selected = sum(1 for decision in decisions if decision.delete)
    print(
        f"{len(decisions)} branches evaluated, {selected} selected for deletion, "
        f"{len(failures)} failed{' (dry run: none deleted)' if args.dry_run else ''}"
    )
    if failures:
        print(f"::error::failed to delete: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
