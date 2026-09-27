"""scripts/ci/ledger_watch.py reports what is about to expire, and nothing else.

The build checks that enforce the release-control ledgers go red on the day a
row expires. The watch exists to say so a month earlier, so the boundary is
the contract: a row inside the horizon is reported, one outside it is not, an
expired row is always reported, and a risk past its `next_review` is reported
although nothing else checks that column. It is a reporter, so it exits 0 on
findings and non-zero only when it cannot read a ledger.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "ledger_watch.py"
TODAY = date(2026, 10, 1)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ledger_watch_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ledger_watch = _load()


def _write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in header})


def _in(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.fixture
def ledgers(tmp_path: Path) -> Path:
    """A release-control directory with one row per interesting boundary."""
    _write_csv(
        tmp_path / "quarantine-register.csv",
        [
            "quarantine_id",
            "check",
            "scope",
            "reason",
            "owner",
            "tracking",
            "opened",
            "expiry",
            "notes",
        ],
        [
            {
                "quarantine_id": "QUAR-001",
                "check": "E2E / soon",
                "owner": "shawnji (qa)",
                "expiry": _in(29),
            },
            {
                "quarantine_id": "QUAR-002",
                "check": "E2E / later",
                "owner": "shawnji (qa)",
                "expiry": _in(31),
            },
        ],
    )
    _write_csv(
        tmp_path / "skip-register.csv",
        [
            "skip_id",
            "path",
            "kind",
            "signature",
            "occurrences",
            "category",
            "reason",
            "owner",
            "tracking",
            "expiry",
            "notes",
        ],
        [
            {
                "skip_id": "SKIP-001",
                "path": "a_test.go",
                "owner": "shawnji (agent)",
                "expiry": _in(-3),
            },
            {
                "skip_id": "SKIP-002",
                "path": "b_test.go",
                "owner": "shawnji (agent)",
                "expiry": _in(30),
            },
        ],
    )
    _write_csv(
        tmp_path / "exception-register.csv",
        ["exception_id", "status", "severity", "requirement_ids", "owner", "expiry"],
        [
            {
                "exception_id": "EXC-001",
                "status": "active",
                "requirement_ids": "SEC-02",
                "owner": "x",
                "expiry": _in(10),
            },
            # Closed exceptions are not enforced, so their dates are not news.
            {
                "exception_id": "EXC-002",
                "status": "closed",
                "requirement_ids": "SEC-03",
                "owner": "x",
                "expiry": "",
            },
        ],
    )
    (tmp_path / "security-suppressions.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "suppressions": [
                    {
                        "id": "TRIVY-001",
                        "tool": "trivy",
                        "selector": ".venv/",
                        "owner": "security-owner",
                        "expiry": _in(90),
                    },
                    {
                        "id": "TRIVY-002",
                        "tool": "trivy",
                        "selector": "tls/",
                        "owner": "security-owner",
                        "expiry": _in(0),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_csv(
        tmp_path / "risk-register.csv",
        ["risk_id", "status", "severity", "owner", "summary", "next_review"],
        [
            {
                "risk_id": "RISK-001",
                "status": "open",
                "owner": "security-owner",
                "summary": "late",
                "next_review": _in(-1),
            },
            {
                "risk_id": "RISK-002",
                "status": "open",
                "owner": "qa-owner",
                "summary": "on time",
                "next_review": _in(0),
            },
            {
                "risk_id": "RISK-003",
                "status": "closed",
                "owner": "qa-owner",
                "summary": "done",
                "next_review": _in(-50),
            },
        ],
    )
    return tmp_path


def _report(directory: Path, days: int = 30) -> Any:
    return ledger_watch.build_report(
        ledger_watch.LedgerPaths.under(directory), TODAY, days
    )


def _expiring_ids(report: Any) -> set[str]:
    return {item.item_id for item in report.expiring}


def test_a_row_expiring_in_29_days_is_reported(ledgers: Path) -> None:
    assert "QUAR-001" in _expiring_ids(_report(ledgers))


def test_a_row_expiring_in_31_days_is_not_reported(ledgers: Path) -> None:
    assert "QUAR-002" not in _expiring_ids(_report(ledgers))


def test_the_horizon_is_inclusive_and_covers_today(ledgers: Path) -> None:
    ids = _expiring_ids(_report(ledgers))
    assert "SKIP-002" in ids, "a row expiring exactly on the horizon is inside it"
    assert "TRIVY-002" in ids, "a row on its last valid day is inside it"
    assert "TRIVY-001" not in ids


def test_an_expired_row_is_reported_and_marked_overdue(ledgers: Path) -> None:
    report = _report(ledgers)
    expired = [item for item in report.expiring if item.item_id == "SKIP-001"]
    assert len(expired) == 1 and expired[0].overdue and expired[0].days_left == -3


def test_only_active_exceptions_are_reported(ledgers: Path) -> None:
    ids = _expiring_ids(_report(ledgers))
    assert "EXC-001" in ids and "EXC-002" not in ids


def test_a_risk_past_next_review_is_reported(ledgers: Path) -> None:
    risks = {item.item_id for item in _report(ledgers).risks_due}
    assert risks == {"RISK-001"}, (
        "past review is reported; due today and closed risks are not"
    )


def test_the_horizon_is_configurable(ledgers: Path) -> None:
    assert "QUAR-002" in _expiring_ids(_report(ledgers, days=31))
    assert _expiring_ids(_report(ledgers, days=0)) == {"SKIP-001", "TRIVY-002"}


def test_json_output_carries_the_issue_title_and_exits_zero(ledgers: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--release-control",
            str(ledgers),
            "--today",
            TODAY.isoformat(),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["anything_due"] is True
    assert document["expiring_count"] == 5
    assert document["expired_count"] == 1
    assert document["risks_due_count"] == 1
    assert document["issue_title"] == (
        f"Release-control ledgers: 5 rows expire by {_in(30)}, 1 risk reviews overdue"
    )


def test_markdown_output_lists_every_due_item(ledgers: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--release-control",
            str(ledgers),
            "--today",
            TODAY.isoformat(),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for item_id in (
        "QUAR-001",
        "SKIP-001",
        "SKIP-002",
        "EXC-001",
        "TRIVY-002",
        "RISK-001",
    ):
        assert item_id in result.stdout
    for item_id in ("QUAR-002", "TRIVY-001", "EXC-002", "RISK-002", "RISK-003"):
        assert item_id not in result.stdout


def test_nothing_due_is_reported_as_such(ledgers: Path) -> None:
    report = _report(ledgers)
    empty = ledger_watch.Report(today=TODAY, horizon_days=30, expiring=[], risks_due=[])
    assert report.anything_due and not empty.anything_due
    assert "Nothing expires" in ledger_watch.render_markdown(empty)


def test_an_unparseable_ledger_exits_non_zero(ledgers: Path) -> None:
    (ledgers / "skip-register.csv").write_text(
        "skip_id,path,owner,expiry\nSKIP-009,x,y,not-a-date\n", encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--release-control", str(ledgers)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "SKIP-009" in result.stderr


def test_a_missing_ledger_exits_non_zero(ledgers: Path) -> None:
    (ledgers / "risk-register.csv").unlink()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--release-control", str(ledgers)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "risk-register.csv" in result.stderr


def test_the_real_ledgers_parse() -> None:
    """The fixture format and the real files must not drift apart."""
    paths = ledger_watch.LedgerPaths.default()
    for path in (
        paths.quarantine,
        paths.skip,
        paths.exceptions,
        paths.suppressions,
        paths.risks,
    ):
        assert path.is_file(), f"{path} does not exist"
    # A horizon wide enough to include every dated row proves each one parsed.
    report = ledger_watch.build_report(paths, TODAY, horizon_days=100_000)
    assert report.expiring, "no expiry-dated rows parsed from the real ledgers"
    ledgers = {item.ledger for item in report.expiring}
    assert ledgers == {
        "quarantine-register",
        "skip-register",
        "exception-register",
        "security-suppressions",
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    json.loads(result.stdout)
