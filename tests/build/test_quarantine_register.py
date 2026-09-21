"""A red required check is fixed, or quarantined with an owner and an expiry.

There is no third option. "Probably flaky" is not an outcome, and the six
incidents in docs/design/2026-09-20-install-experience-and-release-verification-design.md
§1.9 are what the third option costs: a nightly that characterised three-week-old
`main` for nine consecutive runs, an agent suite where eight of ten failures
traced to one harness bug, and a genuinely red Browser E2E written off as
"stale runs from before #137 landed".

Modelled on test_skip_register.py, deliberately, including the lesson its
docstring records: expiry is compared against `date.today()`, never against the
date the register was written. A register whose rows expire relative to their
own authoring date is green forever.

The expiry ceiling is the part that makes an expiry date mean anything. A
quarantine renewable to an arbitrary date is a permanent exemption with a date
column, so a row may not be opened for more than 90 days. Renewing it is a
commit that a reviewer sees.
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTER = REPO_ROOT / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv"
OWNER_MAP = REPO_ROOT / "specs" / "1.0.0" / "release-control" / "owner-map.md"

EXPECTED_COLUMNS = [
    "quarantine_id",
    "check",
    "scope",
    "reason",
    "owner",
    "tracking",
    "opened",
    "expiry",
    "notes",
]

ID_RE = re.compile(r"^QUAR-\d{3}$")
MAX_QUARANTINE_DAYS = 90
REQUIRED_NON_EMPTY = ("check", "scope", "reason", "owner", "tracking", "opened", "expiry")


def _rows() -> list[dict[str, str]]:
    """Every row in the register, as dicts keyed by column name."""
    with REGISTER.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _owners() -> set[str]:
    """Owner strings the owner map declares, e.g. 'shawnji (release)'."""
    text = OWNER_MAP.read_text(encoding="utf-8")
    return set(re.findall(r"\|\s*(shawnji \([a-z]+\))\s*\|", text))


def test_register_exists_and_has_the_expected_columns() -> None:
    assert REGISTER.exists(), (
        f"{REGISTER.relative_to(REPO_ROOT)} is missing. The register is the only "
        "permitted alternative to fixing a red required check, so its absence "
        "means the policy has no mechanism."
    )
    with REGISTER.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    assert header == EXPECTED_COLUMNS, (
        f"quarantine-register.csv header is {header}, expected {EXPECTED_COLUMNS}. "
        "scripts/release_checklist.py reads these column names."
    )


def test_no_quarantine_is_past_its_expiry() -> None:
    """The one assertion that makes the expiry column load-bearing."""
    today = date.today()
    expired = [
        (row["quarantine_id"], row["check"], row["expiry"])
        for row in _rows()
        if date.fromisoformat(row["expiry"]) < today
    ]
    assert not expired, (
        "Quarantine entries are past their expiry: "
        + "; ".join(f"{qid} ({check}) expired {exp}" for qid, check, exp in expired)
        + ". Fix the check, or renew the row with a new expiry and a reason — "
        "renewal is a commit a reviewer sees, which is the point."
    )


def test_every_row_is_complete_and_well_formed() -> None:
    for row in _rows():
        qid = row["quarantine_id"]
        assert ID_RE.match(qid), f"quarantine_id {qid!r} is not QUAR-NNN"
        for column in REQUIRED_NON_EMPTY:
            assert row[column].strip(), (
                f"{qid} has an empty {column}. A row missing an owner, a reason "
                "or a tracking item is a placeholder, which is the state this "
                "register exists to reject."
            )
        opened = date.fromisoformat(row["opened"])
        expiry = date.fromisoformat(row["expiry"])
        assert expiry > opened, f"{qid} expires ({expiry}) on or before it opened ({opened})"
        assert (expiry - opened).days <= MAX_QUARANTINE_DAYS, (
            f"{qid} is quarantined for {(expiry - opened).days} days, over the "
            f"{MAX_QUARANTINE_DAYS}-day ceiling. A quarantine renewable to an "
            "arbitrary date is a permanent exemption with a date column."
        )


def test_quarantine_ids_are_unique() -> None:
    ids = [row["quarantine_id"] for row in _rows()]
    duplicates = sorted({qid for qid in ids if ids.count(qid) > 1})
    assert not duplicates, f"duplicate quarantine ids: {duplicates}"


def test_every_owner_is_named_in_the_owner_map() -> None:
    known = _owners()
    assert known, (
        "No owners parsed from owner-map.md — the parser and the map have "
        "diverged, and this test would pass vacuously."
    )
    for row in _rows():
        assert row["owner"] in known, (
            f"{row['quarantine_id']} names owner {row['owner']!r}, which is not in "
            f"owner-map.md. Known owners: {sorted(known)}"
        )
