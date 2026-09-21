"""Release readiness is asserted, not felt.

specs/1.0.0/release-control/ is strong governance scoped to one future
milestone. v0.4.2 shipped with no equivalent: the gap between the rigour of
that directory and how 0.4.2 actually shipped is the disjointedness this whole
design exists to close.

The checklist is generated rather than hand-written on purpose. A hand-written
checklist is a signal, and a signal that can be waved through is the failure
mode documented in §1.9 of the design.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "release_checklist.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def test_checklist_passes_on_the_current_tree() -> None:
    from release_checklist import evaluate

    rows = evaluate(version=(REPO_ROOT / "VERSION").read_text().strip(), repo_root=REPO_ROOT)
    unsatisfied = [row for row in rows if not row.satisfied]
    assert not unsatisfied, "unsatisfied rows: " + "; ".join(
        f"{row.name}: {row.detail}" for row in unsatisfied
    )


def test_checklist_reports_every_expected_row() -> None:
    from release_checklist import evaluate

    rows = evaluate(version=(REPO_ROOT / "VERSION").read_text().strip(), repo_root=REPO_ROOT)
    names = {row.name for row in rows}
    assert names == {
        "changelog_entry",
        "quarantine_register_current",
        "tier_table_matches_evidence",
        "version_parity",
    }, f"unexpected checklist rows: {sorted(names)}"


def test_an_expired_quarantine_fails_the_checklist(tmp_path: Path) -> None:
    """The row that connects Step 0's register to the release gate."""
    from release_checklist import evaluate

    fake_root = tmp_path / "repo"
    (fake_root / "specs" / "1.0.0" / "release-control").mkdir(parents=True)
    (fake_root / "VERSION").write_text("9.9.9\n")
    (fake_root / "CHANGELOG.md").write_text("## 9.9.9\n\n- entry\n")
    yesterday = date.today() - timedelta(days=1)
    (fake_root / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv").write_text(
        "quarantine_id,check,scope,reason,owner,tracking,opened,expiry,notes\n"
        f"QUAR-001,Some Check,tests/x.py,reason,shawnji (release),RISK-010,"
        f"{yesterday - timedelta(days=10)},{yesterday},note\n"
    )
    rows = {row.name: row for row in evaluate(version="9.9.9", repo_root=fake_root)}
    assert not rows["quarantine_register_current"].satisfied
    assert "QUAR-001" in rows["quarantine_register_current"].detail


def test_a_wrong_candidate_version_fails_version_parity() -> None:
    """version_parity must compare against the candidate, not just self-consistency.

    scripts/release_checklist.py used to run check_version_parity.py with no
    --expected, so it only asserted the tree agreed with itself and then
    reported parity for a candidate version it never compared against.
    """
    from release_checklist import evaluate

    rows = {row.name: row for row in evaluate(version="9.9.9", repo_root=REPO_ROOT)}
    assert not rows["version_parity"].satisfied
    assert "9.9.9" in rows["version_parity"].detail


def test_changelog_entry_does_not_match_a_longer_version(tmp_path: Path) -> None:
    """"0.4.2" must not match a changelog that only ever mentions "0.4.20"."""
    from release_checklist import evaluate

    fake_root = tmp_path / "repo"
    (fake_root / "specs" / "1.0.0" / "release-control").mkdir(parents=True)
    (fake_root / "VERSION").write_text("0.4.2\n")
    (fake_root / "CHANGELOG.md").write_text(
        "## [0.4.20] — 2026-09-01\n\n- entry\n\nSee https://example.test/0.4.2/notes\n"
    )
    (fake_root / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv").write_text(
        "quarantine_id,check,scope,reason,owner,tracking,opened,expiry,notes\n"
    )
    rows = {row.name: row for row in evaluate(version="0.4.2", repo_root=fake_root)}
    assert not rows["changelog_entry"].satisfied


def test_malformed_expiry_produces_a_blocking_row_not_an_exception(tmp_path: Path) -> None:
    """A bad `expiry` value must fail the checklist row, not raise into the caller."""
    from release_checklist import evaluate

    fake_root = tmp_path / "repo"
    (fake_root / "specs" / "1.0.0" / "release-control").mkdir(parents=True)
    (fake_root / "VERSION").write_text("9.9.9\n")
    (fake_root / "CHANGELOG.md").write_text("## [9.9.9] — 2026-09-20\n\n- entry\n")
    (fake_root / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv").write_text(
        "quarantine_id,check,scope,reason,owner,tracking,opened,expiry,notes\n"
        "QUAR-002,Some Check,tests/x.py,reason,shawnji (release),RISK-011,"
        "2026-01-01,not-a-date,note\n"
    )
    rows = {
        row.name: row for row in evaluate(version="9.9.9", repo_root=fake_root)
    }
    assert not rows["quarantine_register_current"].satisfied
    assert "QUAR-002" in rows["quarantine_register_current"].detail
    assert "not-a-date" in rows["quarantine_register_current"].detail


def test_cli_exits_non_zero_when_a_row_is_unsatisfied(tmp_path: Path) -> None:
    fake_root = tmp_path / "repo"
    (fake_root / "specs" / "1.0.0" / "release-control").mkdir(parents=True)
    (fake_root / "VERSION").write_text("9.9.9\n")
    (fake_root / "CHANGELOG.md").write_text("nothing relevant\n")
    (fake_root / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv").write_text(
        "quarantine_id,check,scope,reason,owner,tracking,opened,expiry,notes\n"
    )
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--version", "9.9.9", "--repo-root", str(fake_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "changelog_entry" in completed.stdout + completed.stderr
