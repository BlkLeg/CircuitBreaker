#!/usr/bin/env python3
"""Assert every release-readiness condition for a candidate.

specs/1.0.0/release-control/ governs one future milestone. Nothing governed
v0.4.2, and v0.4.2 shipped a binary with no application in it through a fully
green pipeline. This is the per-release equivalent: generated rather than
hand-written, because a hand-written checklist is one more signal that can be
waved through.

Run by release.yml before publish. Exits non-zero if any row is unsatisfied,
and names the row.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class ChecklistRow:
    """One readiness condition and whether the tree satisfies it.

    Attributes:
        name: Stable identifier, used by tests and by the CI summary.
        satisfied: True when the condition holds.
        detail: Human-readable evidence or the reason it does not hold.
    """

    name: str
    satisfied: bool
    detail: str


def _changelog_entry(version: str, repo_root: Path) -> ChecklistRow:
    """The release must be described somewhere a user can read."""
    changelog = repo_root / "CHANGELOG.md"
    if not changelog.exists():
        return ChecklistRow("changelog_entry", False, "CHANGELOG.md is missing")
    text = changelog.read_text(encoding="utf-8")
    # A bare substring test lets "0.4.2" match "0.4.20" or a URL containing the
    # digits. Require the version to head its own "## [x.y.z]" entry instead.
    heading = re.compile(rf"^##\s*\[{re.escape(version)}\]", re.M)
    if heading.search(text):
        return ChecklistRow(
            "changelog_entry", True, f"CHANGELOG.md has a heading for {version}"
        )
    return ChecklistRow(
        "changelog_entry",
        False,
        f"CHANGELOG.md has no '## [{version}]' heading",
    )


def _quarantine_register_current(repo_root: Path) -> ChecklistRow:
    """No quarantined check may be past its expiry at release time."""
    register = repo_root / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv"
    if not register.exists():
        return ChecklistRow(
            "quarantine_register_current", False, f"{register} is missing"
        )
    today = date.today()
    expired: list[str] = []
    with register.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                is_expired = date.fromisoformat(row["expiry"]) < today
            except ValueError:
                return ChecklistRow(
                    "quarantine_register_current",
                    False,
                    f"{row['quarantine_id']} has a malformed expiry: {row['expiry']!r}",
                )
            if is_expired:
                expired.append(
                    f"{row['quarantine_id']} ({row['check']}) expired {row['expiry']}"
                )
    if expired:
        return ChecklistRow(
            "quarantine_register_current",
            False,
            "expired quarantine entries: " + "; ".join(expired),
        )
    return ChecklistRow("quarantine_register_current", True, "no expired entries")


def _tier_table_matches_evidence(repo_root: Path) -> ChecklistRow:
    """ADR 0005's in-force column must not claim more than exists.

    Checked structurally rather than semantically: the table must still carry an
    explicit state for every tier. A row whose state cell has been emptied is
    the shape of a claim made by deletion.
    """
    adr = repo_root / "docs" / "adr" / "0005-verification-tiers-and-platform-support.md"
    if not adr.exists():
        return ChecklistRow("tier_table_matches_evidence", False, f"{adr} is missing")
    text = adr.read_text(encoding="utf-8")
    states = re.findall(r"^\|\s*([123])\s*\|.*\|\s*(\*\*.+?\*\*.*?)\s*\|\s*$", text, re.M)
    if len(states) != 3:
        return ChecklistRow(
            "tier_table_matches_evidence",
            False,
            f"expected 3 tier rows with an explicit state, found {len(states)}",
        )
    return ChecklistRow(
        "tier_table_matches_evidence",
        True,
        "; ".join(f"tier {tier}: {state[:40]}" for tier, state in states),
    )


def _version_parity(version: str, repo_root: Path) -> ChecklistRow:
    """Delegates to the existing parity gate rather than reimplementing it."""
    script = repo_root / "scripts" / "check_version_parity.py"
    if not script.exists():
        return ChecklistRow("version_parity", False, f"{script} is missing")
    completed = subprocess.run(
        [sys.executable, str(script), "--expected", version],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )
    if completed.returncode != 0:
        return ChecklistRow(
            "version_parity",
            False,
            (completed.stdout + completed.stderr).strip()[:400],
        )
    return ChecklistRow(
        "version_parity", True, f"every version source matches candidate {version}"
    )


def evaluate(version: str, repo_root: Path) -> list[ChecklistRow]:
    """Every readiness row for this candidate, in a stable order."""
    return [
        _changelog_entry(version, repo_root),
        _quarantine_register_current(repo_root),
        _tier_table_matches_evidence(repo_root),
        _version_parity(version, repo_root),
    ]


def main(argv: list[str] | None = None) -> int:
    """Print the checklist and return 0 only when every row is satisfied."""
    parser = argparse.ArgumentParser(description="Assert release readiness.")
    parser.add_argument("--version", required=True, help="Candidate version, e.g. 0.4.3")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root to evaluate.",
    )
    args = parser.parse_args(argv)

    rows = evaluate(version=args.version, repo_root=Path(args.repo_root))
    width = max(len(row.name) for row in rows)
    for row in rows:
        mark = "PASS" if row.satisfied else "FAIL"
        print(f"[{mark}] {row.name.ljust(width)}  {row.detail}")

    unsatisfied = [row.name for row in rows if not row.satisfied]
    if unsatisfied:
        print(f"\nRelease blocked: {', '.join(unsatisfied)}", file=sys.stderr)
        return 1
    print("\nRelease checklist satisfied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
