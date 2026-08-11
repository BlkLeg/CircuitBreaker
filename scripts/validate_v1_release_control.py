#!/usr/bin/env python3
"""Validate the 1.0.0 release-control ledger.

The canonical requirement ID set is derived from the normative spec files under
``specs/1.0.0/[0-9][0-9]-*.md``. The ledger must contain each canonical ID exactly
once and no unknown IDs.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "specs" / "1.0.0"
DEFAULT_LEDGER = SPEC_DIR / "release-control" / "requirement-ledger.csv"
DEFAULT_EXCEPTIONS = SPEC_DIR / "release-control" / "exception-register.csv"

ID_RE = re.compile(r"\| ((?:RC|SEC|AGT|SRV|ACC|REL|GOV|NPM|EXEC)-\d{2}) \|")
VALID_STATUSES = {
    "not_started",
    "in_progress",
    "blocked",
    "passed",
    "failed",
    "excepted",
    "invalidated",
}
VALID_INVALIDATION_STATES = {
    "not_evidenced",
    "current",
    "invalidated",
    "superseded",
    "exception",
}
REQUIRED_LEDGER_FIELDS = [
    "requirement_id",
    "requirement_source",
    "summary",
    "owner",
    "reviewer",
    "status",
    "commit",
    "version",
    "artifact_digest",
    "environment",
    "procedure",
    "evidence_url",
    "evidence_digest",
    "completion_time",
    "issues",
    "exception_id",
    "invalidation_state",
    "invalidated_by",
    "notes",
]
REQUIRED_EXCEPTION_FIELDS = [
    "exception_id",
    "status",
    "severity",
    "requirement_ids",
    "owner",
    "reviewer",
    "rationale",
    "compensating_control",
    "evidence_url",
    "expiry",
    "approval",
    "closure",
    "notes",
]


def canonical_requirement_ids() -> set[str]:
    ids: set[str] = set()
    for path in sorted(SPEC_DIR.glob("[0-9][0-9]-*.md")):
        if path.name.endswith("-implementation.md"):
            continue
        for match in ID_RE.finditer(path.read_text(encoding="utf-8")):
            ids.add(match.group(1))
    return ids


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def validate_ledger(
    canonical: set[str], *, ledger_path: Path, strict_passes: bool
) -> list[dict[str, str]]:
    if not ledger_path.exists():
        fail(f"missing ledger: {display_path(ledger_path)}")

    rows = read_csv(ledger_path)
    if not rows:
        fail("ledger is empty")

    fields = set(rows[0].keys())
    missing_fields = [field for field in REQUIRED_LEDGER_FIELDS if field not in fields]
    if missing_fields:
        fail(f"ledger missing required fields: {', '.join(missing_fields)}")

    ids = [row["requirement_id"] for row in rows]
    counts = Counter(ids)
    duplicates = sorted(requirement_id for requirement_id, count in counts.items() if count > 1)
    if duplicates:
        fail(f"duplicate ledger IDs: {', '.join(duplicates)}")

    ledger_ids = set(ids)
    missing = sorted(canonical - ledger_ids)
    unknown = sorted(ledger_ids - canonical)
    if missing:
        fail(f"ledger missing canonical IDs: {', '.join(missing)}")
    if unknown:
        fail(f"ledger contains unknown IDs: {', '.join(unknown)}")

    for index, row in enumerate(rows, start=2):
        rid = row["requirement_id"]
        if row["status"] not in VALID_STATUSES:
            fail(f"{display_path(ledger_path)}:{index}: invalid status for {rid}: {row['status']}")
        if row["invalidation_state"] not in VALID_INVALIDATION_STATES:
            fail(
                f"{display_path(ledger_path)}:{index}: invalid invalidation_state for "
                f"{rid}: {row['invalidation_state']}"
            )
        for field in ("owner", "reviewer", "version", "requirement_source"):
            if not row[field].strip():
                fail(f"{display_path(ledger_path)}:{index}: {rid} missing {field}")

        if row["status"] == "passed" or strict_passes:
            missing_evidence = [
                field
                for field in (
                    "commit",
                    "artifact_digest",
                    "environment",
                    "procedure",
                    "evidence_url",
                    "evidence_digest",
                    "completion_time",
                )
                if not row[field].strip()
            ]
            if row["status"] == "passed" and missing_evidence:
                fail(
                    f"{display_path(ledger_path)}:{index}: {rid} is passed but missing "
                    f"{', '.join(missing_evidence)}"
                )
            if row["status"] == "passed" and row["invalidation_state"] != "current":
                fail(f"{display_path(ledger_path)}:{index}: {rid} passed evidence is not current")

        if row["status"] == "excepted" and not row["exception_id"].strip():
            fail(f"{display_path(ledger_path)}:{index}: {rid} excepted without exception_id")

    return rows


def validate_exceptions(
    canonical: set[str], ledger_rows: list[dict[str, str]], *, exceptions_path: Path
) -> None:
    if not exceptions_path.exists():
        fail(f"missing exception register: {display_path(exceptions_path)}")

    with exceptions_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing_fields = [field for field in REQUIRED_EXCEPTION_FIELDS if field not in fields]
        if missing_fields:
            fail(f"exception register missing required fields: {', '.join(missing_fields)}")
        rows = list(reader)

    exception_ids = {row["exception_id"] for row in rows if row.get("exception_id")}
    referenced_exception_ids = {
        row["exception_id"] for row in ledger_rows if row.get("exception_id", "").strip()
    }
    unknown_references = sorted(referenced_exception_ids - exception_ids)
    if unknown_references:
        fail(f"ledger references unknown exception IDs: {', '.join(unknown_references)}")

    today = date.today()
    for index, row in enumerate(rows, start=2):
        exception_id = row["exception_id"].strip()
        if not exception_id:
            fail(f"{EXCEPTIONS.relative_to(ROOT)}:{index}: missing exception_id")
        requirement_ids = [
            part.strip() for part in row["requirement_ids"].split(";") if part.strip()
        ]
        unknown = sorted(set(requirement_ids) - canonical)
        if unknown:
            fail(
                f"{display_path(exceptions_path)}:{index}: {exception_id} references "
                f"unknown requirement IDs: {', '.join(unknown)}"
            )
        if row["status"] == "active":
            if not row["expiry"].strip():
                fail(f"{display_path(exceptions_path)}:{index}: active exception missing expiry")
            try:
                expiry = date.fromisoformat(row["expiry"])
            except ValueError:
                fail(f"{display_path(exceptions_path)}:{index}: invalid expiry date")
            if expiry < today:
                fail(f"{display_path(exceptions_path)}:{index}: active exception expired")
            for field in (
                "severity",
                "owner",
                "reviewer",
                "rationale",
                "compensating_control",
                "evidence_url",
                "approval",
            ):
                if not row[field].strip():
                    fail(
                        f"{display_path(exceptions_path)}:{index}: active exception "
                        f"{exception_id} missing {field}"
                    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict-passes",
        action="store_true",
        help="Require evidence fields on every row, not only rows marked passed.",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=DEFAULT_LEDGER,
        help="Path to requirement-ledger.csv.",
    )
    parser.add_argument(
        "--exceptions",
        type=Path,
        default=DEFAULT_EXCEPTIONS,
        help="Path to exception-register.csv.",
    )
    args = parser.parse_args()

    canonical = canonical_requirement_ids()
    rows = validate_ledger(canonical, ledger_path=args.ledger, strict_passes=args.strict_passes)
    validate_exceptions(canonical, rows, exceptions_path=args.exceptions)
    print(f"release-control validation ok: {len(rows)} ledger rows, {len(canonical)} canonical IDs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
