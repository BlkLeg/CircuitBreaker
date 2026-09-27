"""The post-release follow-up opens the next patch without a person editing files.

scripts/post_release_bump.py is what release-followup.yml runs on dev after a
stable release is published. It must leave a tree that release_checklist.py
accepts for the NEW version, must never list a published release (or a later
draft) for deletion, and must be a no-op when re-run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "post_release_bump.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from post_release_bump import (
    ReleaseFollowupError,
    SemVer,
    date_released_heading,
    insert_next_heading,
    next_patch,
    open_next,
    read_json_stream,
    release_date,
    resolve_next_version,
    stale_draft_ids,
)

CHANGELOG = """# Changelog

Policy paragraph.

## [0.4.4] — unreleased

### Fixed

- Something.

## [0.4.2] — 2026-09-20

- Older.
"""


def _tree(tmp_path: Path, version: str = "0.4.4", changelog: str = CHANGELOG) -> Path:
    (tmp_path / "VERSION").write_text(version + "\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return tmp_path


def test_next_patch_increments_the_patch() -> None:
    assert next_patch("0.4.4") == "0.4.5"
    assert next_patch("1.9.99") == "1.9.100"


def test_next_patch_refuses_a_prerelease() -> None:
    with pytest.raises(ReleaseFollowupError):
        next_patch("1.0.0-rc.1")


def test_semver_precedence() -> None:
    assert SemVer.parse("1.0.0-rc.1") < SemVer.parse("1.0.0")
    assert SemVer.parse("1.0.0-rc.2") < SemVer.parse("1.0.0-rc.10")
    assert SemVer.parse("0.4.4") < SemVer.parse("0.4.10")
    assert SemVer.parse("v0.4.4") == SemVer.parse("0.4.4")
    with pytest.raises(ValueError):
        SemVer.parse("0.4")


def test_resolve_next_version_keeps_a_dev_that_is_already_ahead() -> None:
    assert resolve_next_version("0.4.4", "0.4.4") == "0.4.5"
    assert resolve_next_version("0.4.5", "0.4.4") == "0.4.5"
    assert resolve_next_version("0.5.0", "0.4.4") == "0.5.0"
    with pytest.raises(ReleaseFollowupError):
        resolve_next_version("0.4.3", "0.4.4")


def test_release_date_is_the_utc_calendar_day() -> None:
    assert release_date("2026-09-27T23:30:00Z") == date(2026, 9, 27)
    assert release_date("2026-09-27T23:30:00-05:00") == date(2026, 9, 28)


def test_dating_the_heading_is_idempotent_and_leaves_older_entries() -> None:
    once = date_released_heading(CHANGELOG, "0.4.4", date(2026, 9, 27))
    assert "## [0.4.4] — 2026-09-27\n" in once
    assert "unreleased" not in once
    assert "## [0.4.2] — 2026-09-20" in once
    assert date_released_heading(once, "0.4.4", date(2026, 10, 1)) == once


def test_dating_accepts_a_hand_typed_hyphen() -> None:
    text = CHANGELOG.replace("[0.4.4] — unreleased", "[0.4.4] - Unreleased")
    assert "## [0.4.4] — 2026-09-27" in date_released_heading(
        text, "0.4.4", date(2026, 9, 27)
    )


def test_a_missing_released_heading_is_an_error() -> None:
    with pytest.raises(ReleaseFollowupError):
        date_released_heading(CHANGELOG, "0.4.3", date(2026, 9, 27))


def test_the_next_heading_opens_directly_above_the_released_one() -> None:
    opened = insert_next_heading(CHANGELOG, "0.4.4", "0.4.5")
    assert (
        "Policy paragraph.\n\n## [0.4.5] — unreleased\n\n## [0.4.4] — unreleased"
        in opened
    )
    assert insert_next_heading(opened, "0.4.4", "0.4.5") == opened


def test_open_next_rotates_the_tree_and_satisfies_the_checklist_heading(
    tmp_path: Path,
) -> None:
    from release_checklist import _changelog_entry

    root = _tree(tmp_path)
    result = open_next(root, "0.4.4", date(2026, 9, 27))

    assert result.next_version == "0.4.5"
    assert (root / "VERSION").read_text(encoding="utf-8") == "0.4.5\n"
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.index("## [0.4.5] — unreleased") < text.index("## [0.4.4] — 2026-09-27")
    assert _changelog_entry("0.4.5", root).satisfied
    assert _changelog_entry("0.4.4", root).satisfied


def test_open_next_is_a_no_op_on_rerun(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    open_next(root, "0.4.4", date(2026, 9, 27))
    before = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    again = open_next(root, "0.4.4", date(2026, 9, 28))

    assert again.changed == []
    assert again.next_version == "0.4.5"
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == before


def test_open_next_uses_a_version_dev_already_chose(tmp_path: Path) -> None:
    root = _tree(tmp_path, version="0.5.0")
    result = open_next(root, "0.4.4", date(2026, 9, 27))
    assert result.next_version == "0.5.0"
    assert (root / "VERSION").read_text(encoding="utf-8") == "0.5.0\n"
    assert "## [0.5.0] — unreleased" in (root / "CHANGELOG.md").read_text(
        encoding="utf-8"
    )


def test_stale_drafts_are_only_drafts_at_or_below_the_release() -> None:
    records: list[dict[str, object]] = [
        {"id": 1, "tag_name": "v0.4.4", "draft": False},  # published: never
        {"id": 2, "tag_name": "v0.4.4", "draft": True},  # leftover draft of the release
        {"id": 3, "tag_name": "v0.4.3", "draft": True},
        {"id": 4, "tag_name": "v0.4.5", "draft": True},  # later: never
        {"id": 5, "tag_name": "v0.4.4-rc.1", "draft": True},
        {"id": 6, "tag_name": "untagged-abc", "draft": True},  # not a version: never
        {"id": 7, "tag_name": "v0.3.9", "draft": False},
    ]
    assert stale_draft_ids(records, "0.4.4") == [3, 5, 2]


def test_cli_open_next_prints_the_next_version(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "open-next",
            "--released",
            "0.4.4",
            "--published-at",
            "2026-09-27T10:00:00Z",
            "--repo-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "0.4.5"


def test_cli_stale_drafts_reads_json_lines() -> None:
    lines = "\n".join(
        json.dumps(record)
        for record in (
            {"id": 11, "tag_name": "v0.4.4", "draft": True},
            {"id": 12, "tag_name": "v0.4.4", "draft": False},
        )
    )
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "stale-drafts", "--released", "0.4.4"],
        input=lines + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.split() == ["11"]


def test_cli_reports_a_prerelease_as_an_error(tmp_path: Path) -> None:
    root = _tree(tmp_path, version="1.0.0-rc.1")
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "open-next",
            "--released",
            "1.0.0-rc.1",
            "--published-at",
            "2026-09-27T10:00:00Z",
            "--repo-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    assert "::error::" in completed.stderr


def test_the_release_stream_parses_in_every_shape_gh_emits() -> None:
    compact = '{"id": 1, "draft": true}\n{"id": 2, "draft": false}\n'
    pretty = '{\n  "id": 1,\n  "draft": true\n}\n{\n  "id": 2\n}'
    pages = '[{"id": 1}, {"id": 2}][{"id": 3}]'
    assert [r["id"] for r in read_json_stream(compact)] == [1, 2]
    assert [r["id"] for r in read_json_stream(pretty)] == [1, 2]
    assert [r["id"] for r in read_json_stream(pages)] == [1, 2, 3]
    assert read_json_stream("  \n") == []
    with pytest.raises(ValueError):
        read_json_stream("{not json")
