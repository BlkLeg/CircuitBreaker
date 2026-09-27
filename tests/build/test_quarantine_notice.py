"""A quarantined check must be able to say which register row permits the skip.

QUAR-001 was expressed as `if: false` in e2e.yml, which removes the check run
entirely: the suite did not run and nothing said so. That is the defect class
`cb::skipped` exists to prevent. This script is what replaces it, so its
contract is that a skip WITHOUT a register row is an error rather than a pass —
otherwise the honest-looking marker becomes a new way to hide a dead gate.
"""

from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

from quarantine_notice import (  # noqa: E402
    REGISTER,
    format_notice,
    main,
    rows_for_check,
)

COLUMNS = [
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

CHECK = "Composed Agent E2E / composed-journey"


def _register(tmp_path: Path, **overrides: str) -> Path:
    """A one-row register CSV, with any cell overridable."""
    row = {
        "quarantine_id": "QUAR-001",
        "check": CHECK,
        "scope": "test_alpha, test_beta",
        "reason": "The bootstrap never creates its profiles, so the tests time out.",
        "owner": "shawnji (qa)",
        "tracking": "https://github.com/BlkLeg/CircuitBreaker/issues/162",
        "opened": "2026-09-23",
        "expiry": "2026-12-21",
        "notes": "Job quarantined pending a fix.",
    }
    row.update(overrides)
    path = tmp_path / "quarantine-register.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    return path


def test_a_matching_row_is_found(tmp_path: Path) -> None:
    rows = rows_for_check(_register(tmp_path), CHECK)
    assert [row["quarantine_id"] for row in rows] == ["QUAR-001"]


def test_a_different_check_matches_nothing(tmp_path: Path) -> None:
    assert rows_for_check(_register(tmp_path), "Browser E2E / browser-e2e") == []


def test_the_check_is_matched_exactly_not_by_prefix(tmp_path: Path) -> None:
    """`Composed Agent E2E` is a prefix of the real check name, and a prefix
    match would report a quarantine that the register does not actually carry."""
    assert rows_for_check(_register(tmp_path), "Composed Agent E2E") == []


def test_the_notice_names_the_row_the_expiry_and_the_tracking_item(tmp_path: Path) -> None:
    rows = rows_for_check(_register(tmp_path), CHECK)
    notice = format_notice(rows[0], date(2026, 9, 27))
    assert notice.startswith("SKIPPED (QUAR-001")
    assert "2026-12-21" in notice
    assert "85 days" in notice
    assert "issues/162" in notice
    assert CHECK in notice


def test_an_expired_rows_notice_says_expired_not_skipped(tmp_path: Path) -> None:
    """Piped into a step summary, `SKIPPED` on an expired row would read as a
    reassuring marker for a job that actually failed — the same dishonest
    marker this script exists to remove. The header must say `EXPIRED`."""
    rows = rows_for_check(_register(tmp_path, expiry="2026-09-26"), CHECK)
    notice = format_notice(rows[0], date(2026, 9, 27))
    assert notice.startswith("EXPIRED (")
    assert "SKIPPED" not in notice
    assert "1 days ago" in notice


def test_a_matching_row_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--check", CHECK, "--register", str(_register(tmp_path)), "--today", "2026-09-27"])
    assert code == 0
    assert "SKIPPED (QUAR-001" in capsys.readouterr().out


def test_no_row_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The whole point: a skip nobody registered must fail, not pass quietly."""
    code = main(
        ["--check", "Browser E2E / browser-e2e", "--register", str(_register(tmp_path)),
         "--today", "2026-09-27"]
    )
    assert code == 1
    assert "::error::" in capsys.readouterr().err


def test_an_expired_row_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An expired quarantine is not a licence to skip. test_quarantine_register.py
    fails the build on the same condition; this fails the job that would
    otherwise have reported the skip as fine."""
    register = _register(tmp_path, expiry="2026-09-26")
    code = main(["--check", CHECK, "--register", str(register), "--today", "2026-09-27"])
    assert code == 1
    assert "expired" in capsys.readouterr().err


WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _is_literal_false(value: object) -> bool:
    """True only for an actual `false`, never for an unresolved expression.

    `${{ github.event_name != 'workflow_dispatch' || inputs.quarantined }}` is
    a string and is not this; only a YAML boolean `false` (or the quoted
    string `"false"`, in case a caller ever quotes it) counts.
    """
    if value is False:
        return True
    return isinstance(value, str) and value.strip().lower() == "false"


def _quarantine_still_skippable() -> list[str]:
    """Reasons the composed journey can still be skipped, read from the live
    call sites rather than assumed.

    The rule: the skip is still possible if composed-e2e.yml's `quarantined`
    input defaults to true, OR any workflow calling composed-e2e.yml passes a
    `with.quarantined` value that is not a literal `false`. Callers are found
    by scanning every `.github/workflows/*.yml` file for a job whose `uses:`
    ends in `composed-e2e.yml`, rather than hardcoding `e2e.yml`, so a second
    caller (`tier2.yml`, in slice A2) is covered the moment it exists.
    """
    yaml = pytest.importorskip(
        "yaml", reason="PyYAML parses the workflow files; it arrives with the backend dev extra"
    )
    composed = yaml.safe_load((WORKFLOWS_DIR / "composed-e2e.yml").read_text(encoding="utf-8"))
    # PyYAML reads an unquoted `on:` key as the boolean True (YAML 1.1), not
    # the string "on" — `.get("on", .get(True))` is this repo's house pattern
    # for it (see test_workflow_wiring_resolves.py and its siblings).
    triggers = composed.get("on", composed.get(True))
    default = triggers["workflow_call"]["inputs"]["quarantined"].get("default")

    reasons = []
    if not _is_literal_false(default):
        reasons.append(
            "composed-e2e.yml's `quarantined` input default is "
            f"{default!r}, not a literal false"
        )

    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        if path.name == "composed-e2e.yml":
            continue
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_id, job in (workflow.get("jobs") or {}).items():
            if not str(job.get("uses", "")).endswith("composed-e2e.yml"):
                continue
            with_block = job.get("with") or {}
            if "quarantined" not in with_block:
                # No override: this caller inherits composed-e2e.yml's own
                # default, already accounted for above.
                continue
            value = with_block["quarantined"]
            if not _is_literal_false(value):
                reasons.append(
                    f"{path.name}:{job_id} passes quarantined={value!r}, "
                    "not a literal false"
                )
    return reasons


def test_the_real_register_still_covers_the_composed_journey() -> None:
    """Binds the script to reality, but only while reality still needs it.

    QUAR-001 was expressed as `if: false` in e2e.yml; this test's earlier
    version unconditionally required a QUAR-001 row, which meant the very
    commit that ends the quarantine — flipping the last `quarantined: true`
    to `false` and deleting the row in the same change — would fail this
    test and block itself. This version instead derives whether a row is
    required from the live call sites (see `_quarantine_still_skippable`):
    if the composed journey can still be skipped, a row must exist naming
    the call site that still demands it; once every call site is a literal
    `false`, the row is no longer required and this test passes with none.
    That makes "the quarantine outlived its row" a static failure inside
    `Lint`, not only something a nightly run would eventually notice.
    """
    reasons = _quarantine_still_skippable()
    if not reasons:
        return
    assert rows_for_check(REGISTER, CHECK), (
        f"{REGISTER} has no row for {CHECK!r}, but the composed journey can still "
        f"be skipped: {'; '.join(reasons)}. If the quarantine is truly over, flip "
        "the last such call site to `quarantined: false` in the same commit that "
        "removes the row."
    )
