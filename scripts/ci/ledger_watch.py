#!/usr/bin/env python3
"""Report release-control ledger rows that are about to expire, and overdue risks.

Four ledgers under ``specs/1.0.0/release-control/`` carry an expiry date that a
build check enforces against *today*: the quarantine register
(tests/build/test_quarantine_register.py), the skip register
(tests/build/test_skip_register.py), active exceptions
(scripts/validate_v1_release_control.py) and scanner suppressions
(scripts/validate_security_suppressions.py). Each of those checks goes red on
the morning a row expires, on every branch at once, with no warning beforehand.
The risk register's ``next_review`` column is checked by nothing at all.

This script is the warning. It lists every row expiring within a horizon
(default 30 days) or already expired, and every open risk past its
``next_review``, as Markdown or — with ``--json`` — as a machine-readable
document that .github/workflows/ledger-watch.yml turns into a single tracking
issue.

It is a reporter, not a gate: it exits 0 whatever it finds. It exits 2 only when
a ledger cannot be read or parsed, because then it cannot say what is due.

The ledger locations are taken from the validators and tests that enforce them
rather than restated here, so moving a ledger moves this script's input with it.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HORIZON_DAYS = 30

# Basenames within the release-control directory. `LedgerPaths.default()`
# resolves the real locations through the enforcing validators; these names are
# only used to lay out a fixture directory with `--release-control`.
QUARANTINE_FILE = "quarantine-register.csv"
SKIP_FILE = "skip-register.csv"
EXCEPTION_FILE = "exception-register.csv"
SUPPRESSION_FILE = "security-suppressions.json"
RISK_FILE = "risk-register.csv"

EXIT_OK = 0
EXIT_UNPARSEABLE = 2


class LedgerError(Exception):
    """A ledger is missing, malformed, or carries an unparseable date."""


@dataclass(frozen=True)
class LedgerPaths:
    """Where each of the five ledgers lives."""

    quarantine: Path
    skip: Path
    exceptions: Path
    suppressions: Path
    risks: Path

    @classmethod
    def under(cls, directory: Path) -> LedgerPaths:
        """Ledgers laid out under one directory with their canonical file names."""
        return cls(
            quarantine=directory / QUARANTINE_FILE,
            skip=directory / SKIP_FILE,
            exceptions=directory / EXCEPTION_FILE,
            suppressions=directory / SUPPRESSION_FILE,
            risks=directory / RISK_FILE,
        )

    @classmethod
    def default(cls) -> LedgerPaths:
        """The real ledgers, located through the modules that enforce them."""
        release_control = _load_module(
            "validate_v1_release_control",
            REPO_ROOT / "scripts" / "validate_v1_release_control.py",
        )
        suppressions = _load_module(
            "validate_security_suppressions",
            REPO_ROOT / "scripts" / "validate_security_suppressions.py",
        )
        skip_register = _load_module(
            "test_skip_register",
            REPO_ROOT / "tests" / "build" / "test_skip_register.py",
        )
        quarantine = _load_module(
            "test_quarantine_register",
            REPO_ROOT / "tests" / "build" / "test_quarantine_register.py",
        )
        return cls(
            quarantine=Path(quarantine.REGISTER),
            skip=Path(skip_register.REGISTER),
            exceptions=Path(release_control.DEFAULT_EXCEPTIONS),
            suppressions=Path(suppressions.DEFAULT_MANIFEST),
            risks=Path(skip_register.RISK_REGISTER),
        )


@dataclass(frozen=True)
class DueItem:
    """One ledger row whose date falls inside the report."""

    ledger: str
    item_id: str
    due: str
    days_left: int
    owner: str
    subject: str
    path: str

    @property
    def overdue(self) -> bool:
        """True when the date has already passed."""
        return self.days_left < 0


@dataclass(frozen=True)
class Report:
    """Everything due, relative to one `today` and one horizon."""

    today: date
    horizon_days: int
    expiring: list[DueItem]
    risks_due: list[DueItem]

    @property
    def cutoff(self) -> date:
        """The last date inside the horizon."""
        return self.today + timedelta(days=self.horizon_days)

    @property
    def anything_due(self) -> bool:
        """True when there is at least one row or risk to act on."""
        return bool(self.expiring or self.risks_due)

    def issue_title(self) -> str:
        """The tracking-issue title the workflow uses."""
        parts: list[str] = []
        if self.expiring or not self.risks_due:
            parts.append(
                f"{len(self.expiring)} rows expire by {self.cutoff.isoformat()}"
            )
        if self.risks_due:
            parts.append(f"{len(self.risks_due)} risk reviews overdue")
        return "Release-control ledgers: " + ", ".join(parts)

    def to_json(self) -> dict[str, Any]:
        """A JSON-serialisable form of the report."""
        return {
            "today": self.today.isoformat(),
            "horizon_days": self.horizon_days,
            "cutoff": self.cutoff.isoformat(),
            "anything_due": self.anything_due,
            "expiring_count": len(self.expiring),
            "expired_count": sum(1 for item in self.expiring if item.overdue),
            "risks_due_count": len(self.risks_due),
            "issue_title": self.issue_title(),
            "expiring": [asdict(item) for item in self.expiring],
            "risks_due": [asdict(item) for item in self.risks_due],
        }


def _load_module(name: str, path: Path) -> ModuleType:
    """Import a repository script or test module by path, for its constants."""
    spec = importlib.util.spec_from_file_location(f"_ledger_watch_{name}", path)
    if spec is None or spec.loader is None:
        raise LedgerError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _display(path: Path) -> str:
    """A repository-relative path where possible."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _read_csv(path: Path, required: tuple[str, ...]) -> list[dict[str, str]]:
    """Rows of a ledger CSV, after checking the columns this report reads exist."""
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = reader.fieldnames or []
            missing = [column for column in required if column not in header]
            if missing:
                raise LedgerError(f"{_display(path)}: missing columns {missing}")
            return list(reader)
    except OSError as exc:
        raise LedgerError(f"{_display(path)}: {exc.strerror or exc}") from exc
    except csv.Error as exc:
        raise LedgerError(f"{_display(path)}: {exc}") from exc


def _parse_date(value: str, path: Path, item_id: str, column: str) -> date:
    """An ISO date from a ledger cell, or a LedgerError naming the row."""
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise LedgerError(
            f"{_display(path)}: {item_id} has an invalid {column} {value!r}"
        ) from exc


def _item(
    ledger: str,
    path: Path,
    item_id: str,
    due: date,
    today: date,
    owner: str,
    subject: str,
) -> DueItem:
    """Build a DueItem with its day count relative to `today`."""
    return DueItem(
        ledger=ledger,
        item_id=item_id,
        due=due.isoformat(),
        days_left=(due - today).days,
        owner=owner,
        subject=subject,
        path=_display(path),
    )


def _csv_expiries(
    ledger: str,
    path: Path,
    *,
    id_column: str,
    subject_column: str,
    today: date,
    active_only: bool = False,
) -> list[DueItem]:
    """Every row of an expiry-dated CSV ledger, as DueItems."""
    required = (id_column, subject_column, "owner", "expiry") + (
        ("status",) if active_only else ()
    )
    items: list[DueItem] = []
    for row in _read_csv(path, required):
        # An inactive exception carries no expiry the validator enforces.
        if active_only and row["status"].strip() != "active":
            continue
        item_id = row[id_column].strip()
        due = _parse_date(row["expiry"], path, item_id, "expiry")
        items.append(
            _item(
                ledger,
                path,
                item_id,
                due,
                today,
                row["owner"].strip(),
                row[subject_column].strip(),
            )
        )
    return items


def _suppression_expiries(path: Path, today: date) -> list[DueItem]:
    """Every scanner suppression in the JSON manifest, as DueItems."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LedgerError(f"{_display(path)}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise LedgerError(f"{_display(path)}: invalid JSON: {exc}") from exc
    rows = document.get("suppressions") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise LedgerError(
            f"{_display(path)}: manifest must contain a suppressions list"
        )
    items: list[DueItem] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or not row.get("id") or not row.get("expiry"):
            raise LedgerError(
                f"{_display(path)}: suppression #{index} has no id or expiry"
            )
        item_id = str(row["id"])
        due = _parse_date(str(row["expiry"]), path, item_id, "expiry")
        subject = f"{row.get('tool', '?')}: {row.get('selector', '?')}"
        items.append(
            _item(
                "security-suppressions",
                path,
                item_id,
                due,
                today,
                str(row.get("owner", "")),
                subject,
            )
        )
    return items


def _risk_reviews(path: Path, today: date) -> list[DueItem]:
    """Every risk that is not closed, as DueItems dated by `next_review`."""
    items: list[DueItem] = []
    for row in _read_csv(
        path, ("risk_id", "status", "owner", "summary", "next_review")
    ):
        if row["status"].strip().lower() == "closed":
            continue
        item_id = row["risk_id"].strip()
        due = _parse_date(row["next_review"], path, item_id, "next_review")
        items.append(
            _item(
                "risk-register",
                path,
                item_id,
                due,
                today,
                row["owner"].strip(),
                row["summary"].strip(),
            )
        )
    return items


def build_report(
    paths: LedgerPaths, today: date, horizon_days: int = DEFAULT_HORIZON_DAYS
) -> Report:
    """Read every ledger and collect what is due.

    A row is reported when its expiry is on or before ``today + horizon_days``,
    which includes rows already expired. A risk is reported when its
    ``next_review`` is before ``today``.
    """
    if horizon_days < 0:
        raise ValueError("horizon_days must not be negative")
    rows = [
        *_csv_expiries(
            "quarantine-register",
            paths.quarantine,
            id_column="quarantine_id",
            subject_column="check",
            today=today,
        ),
        *_csv_expiries(
            "skip-register",
            paths.skip,
            id_column="skip_id",
            subject_column="path",
            today=today,
        ),
        *_csv_expiries(
            "exception-register",
            paths.exceptions,
            id_column="exception_id",
            subject_column="requirement_ids",
            today=today,
            active_only=True,
        ),
        *_suppression_expiries(paths.suppressions, today),
    ]
    expiring = sorted(
        (item for item in rows if item.days_left <= horizon_days),
        key=lambda item: (item.due, item.ledger, item.item_id),
    )
    risks_due = sorted(
        (item for item in _risk_reviews(paths.risks, today) if item.overdue),
        key=lambda item: (item.due, item.item_id),
    )
    return Report(
        today=today, horizon_days=horizon_days, expiring=expiring, risks_due=risks_due
    )


def _cell(text: str) -> str:
    """Make free text safe inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def _when(item: DueItem) -> str:
    """Human wording for a day count."""
    if item.days_left < 0:
        return f"**expired {-item.days_left}d ago**"
    if item.days_left == 0:
        return "**last day today**"
    return f"in {item.days_left}d"


def render_markdown(report: Report) -> str:
    """The report as Markdown, suitable for an issue body or a step summary."""
    lines = [
        "## Release-control ledger watch",
        "",
        (
            f"As of **{report.today.isoformat()}** (UTC), horizon {report.horizon_days} days "
            f"(through {report.cutoff.isoformat()})."
        ),
        "",
    ]
    if not report.anything_due:
        lines.append(
            "Nothing expires inside the horizon and no risk review is overdue."
        )
        return "\n".join(lines) + "\n"

    expired = sum(1 for item in report.expiring if item.overdue)
    lines.append(
        f"- **{len(report.expiring)}** ledger rows expire by {report.cutoff.isoformat()}"
        + (
            f" ({expired} already expired — the enforcing build checks are red)"
            if expired
            else ""
        )
    )
    lines.append(f"- **{len(report.risks_due)}** open risks are past `next_review`")
    lines.append("")

    if report.expiring:
        lines += [
            "### Expiring rows",
            "",
            "Resolve the row, or renew it with a new expiry and a note saying what changed.",
            "",
            "| Ledger | ID | Expiry | When | Owner | Subject |",
            "|---|---|---|---|---|---|",
        ]
        for item in report.expiring:
            lines.append(
                f"| `{item.path}` | {_cell(item.item_id)} | {item.due} | {_when(item)} "
                f"| {_cell(item.owner)} | {_cell(item.subject)} |"
            )
        lines.append("")

    if report.risks_due:
        lines += [
            "### Risks past next review",
            "",
            "No build check enforces `next_review`; this list is the only reminder.",
            "",
            "| ID | Next review | Overdue | Owner | Summary |",
            "|---|---|---|---|---|",
        ]
        for item in report.risks_due:
            lines.append(
                f"| {_cell(item.item_id)} | {item.due} | {-item.days_left}d "
                f"| {_cell(item.owner)} | {_cell(item.subject)} |"
            )
        lines.append("")

    return "\n".join(lines)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Command-line options."""
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_HORIZON_DAYS,
        help=f"report rows expiring within this many days (default {DEFAULT_HORIZON_DAYS})",
    )
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=datetime.now(UTC).date(),
        help="evaluate as of this ISO date instead of today (UTC)",
    )
    parser.add_argument(
        "--release-control",
        type=Path,
        default=None,
        help="read the ledgers from this directory instead of the repository's",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit JSON instead of Markdown"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Print the report; exit 0 unless a ledger cannot be parsed."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.days < 0:
        print("ledger_watch: --days must not be negative", file=sys.stderr)
        return EXIT_UNPARSEABLE
    try:
        paths = (
            LedgerPaths.under(args.release_control)
            if args.release_control
            else LedgerPaths.default()
        )
        report = build_report(paths, args.today, args.days)
    except LedgerError as exc:
        print(f"ledger_watch: cannot parse ledgers: {exc}", file=sys.stderr)
        return EXIT_UNPARSEABLE
    if args.json:
        print(json.dumps(report.to_json(), indent=2))
    else:
        print(render_markdown(report), end="")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
