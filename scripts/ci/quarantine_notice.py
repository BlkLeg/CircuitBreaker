#!/usr/bin/env python3
"""Print the register row that permits a check to be skipped, or fail.

QUAR-001 disabled the composed agent journey with `if: false` in e2e.yml. That
removes the check run altogether: the suite did not run, and nothing in the
pipeline said so. `scripts/ci/lib/common.sh`'s `cb::skipped` exists because
"did not run" and "found nothing" must never be spelled the same way, and a
workflow-level `if: false` is the strongest form of that mistake — there is not
even a line of output to read.

This is the workflow-side equivalent. A quarantined job runs this instead of
the suite, and the skip is only reported when
specs/1.0.0/release-control/quarantine-register.csv actually carries a row for
that check. A missing row, or an expired one, is an error: without that, the
honest-looking marker would become a new way to hide a dead gate, which is the
defect it was written to remove.

Exit codes: 0 when every matching row is live, 1 when no row matches or a
matching row has expired, 2 on a malformed register.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTER = REPO_ROOT / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv"

# Read, never written: this script reports the register and never edits it.
# Naming the columns it reads means a renamed column fails here with the column
# name rather than with a KeyError three frames down.
READ_COLUMNS = ("quarantine_id", "check", "scope", "owner", "tracking", "expiry")


class RegisterError(Exception):
    """The register is missing, malformed, or has an unparseable date."""


def rows_for_check(register: Path, check: str) -> list[dict[str, str]]:
    """Every register row whose `check` equals `check` exactly.

    Exact equality, not a prefix or substring test: "Composed Agent E2E" is a
    prefix of "Composed Agent E2E / composed-journey", and a loose match would
    report a quarantine the register does not carry for the job being skipped.
    """
    if not register.is_file():
        raise RegisterError(f"{register} does not exist")
    with register.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in READ_COLUMNS if column not in (reader.fieldnames or ())]
        if missing:
            raise RegisterError(f"{register} is missing column(s): {', '.join(missing)}")
        return [row for row in reader if row["check"].strip() == check]


def format_notice(row: Mapping[str, str], today: date) -> str:
    """One `SKIPPED (...)` line, in `cb::skipped`'s shape, naming the row.

    The days-remaining figure is the part a reader acts on: it turns "this is
    quarantined" into "this stops being allowed on a date you can see".
    """
    expiry = _parse_date(row["expiry"], row["quarantine_id"])
    remaining = (expiry - today).days
    return (
        f"SKIPPED ({row['quarantine_id']}, expires {expiry.isoformat()}, "
        f"{remaining} days left): {row['check']}\n"
        f"  scope:    {row['scope']}\n"
        f"  owner:    {row['owner']}\n"
        f"  tracking: {row['tracking']}"
    )


def _parse_date(value: str, quarantine_id: str) -> date:
    """An ISO date from a register cell, or a RegisterError naming the row."""
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise RegisterError(f"{quarantine_id} has an unparseable expiry {value!r}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    """Report the quarantine for one check, or fail if the register does not."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        required=True,
        help="the check name exactly as the register's `check` column spells it",
    )
    parser.add_argument("--register", default=str(REGISTER))
    parser.add_argument(
        "--today",
        default=datetime.now(UTC).date().isoformat(),
        help="ISO date the expiry is measured against; defaults to today (UTC)",
    )
    args = parser.parse_args(argv)

    try:
        today = date.fromisoformat(args.today)
        rows = rows_for_check(Path(args.register), args.check)
    except RegisterError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2
    except ValueError:
        print(f"::error::--today is not an ISO date: {args.today!r}", file=sys.stderr)
        return 2

    if not rows:
        print(
            f"::error::no quarantine row for {args.check!r} in {args.register} — a check "
            "may not be skipped without one. Fix the check, or add a row with an owner, "
            "a tracking item and an expiry no more than 90 days out.",
            file=sys.stderr,
        )
        return 1

    expired = []
    for row in rows:
        try:
            notice = format_notice(row, today)
        except RegisterError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 2
        print(notice)
        if _parse_date(row["expiry"], row["quarantine_id"]) < today:
            expired.append(row["quarantine_id"])

    if expired:
        print(
            f"::error::quarantine row(s) expired: {', '.join(expired)} — the skip is no "
            "longer permitted. Fix the check, or renew the row deliberately.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
