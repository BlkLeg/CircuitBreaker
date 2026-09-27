#!/usr/bin/env python3
"""Open the next patch on dev after a release is published.

Run by .github/workflows/release-followup.yml, which release.yml's post-publish
job dispatches once a stable release is live. Two jobs, both mechanical:

``open-next``
    VERSION moves from the released version to the next patch (0.4.4 → 0.4.5),
    and CHANGELOG.md's ``## [0.4.4] — unreleased`` heading takes the date the
    release was published while a fresh ``## [0.4.5] — unreleased`` heading
    opens above it — the rotation CHANGELOG.md's own policy paragraph
    describes. scripts/release_checklist.py requires a ``## [<VERSION>]``
    heading, so the bumped tree still satisfies it.

``stale-drafts``
    Reads the repository's releases as a JSON stream on stdin and prints the ids
    of DRAFT releases whose version is at or below the released one. Published
    releases are never listed, nor is a draft for a later version, nor a
    release whose tag does not parse as a version.

Both are idempotent: re-running for the same released version after it has
already been applied changes nothing, so the follow-up workflow can be re-run
safely.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

# The dash between the version and its state. The file uses an em dash; an en
# dash or hyphen typed by hand is accepted so a heading is never silently
# missed over punctuation.
_DASH = "[—–-]"


class ReleaseFollowupError(Exception):
    """A condition the follow-up cannot resolve mechanically; a person must."""


@dataclass(frozen=True)
class SemVer:
    """A parsed semantic version, comparable by semver 2.0.0 precedence.

    Attributes:
        major: Major component.
        minor: Minor component.
        patch: Patch component.
        prerelease: Dot-separated prerelease identifiers; empty for a release.
    """

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = field(default=())

    @classmethod
    def parse(cls, text: str) -> SemVer:
        """Parse ``X.Y.Z`` or ``X.Y.Z-pre``, tolerating a leading ``v``.

        Raises:
            ValueError: when ``text`` is not a semantic version.
        """
        match = _SEMVER_RE.match(text.strip().removeprefix("v").removeprefix("V"))
        if match is None:
            raise ValueError(f"{text!r} is not a semantic version")
        pre = match.group("pre")
        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            prerelease=tuple(pre.split(".")) if pre else (),
        )

    @property
    def is_prerelease(self) -> bool:
        """True when the version carries a prerelease suffix."""
        return bool(self.prerelease)

    def _key(self) -> tuple[int, int, int, int, tuple[tuple[int, int, str], ...]]:
        """Sort key implementing semver precedence (§11).

        A release sorts after every prerelease of the same core; numeric
        identifiers compare numerically and sort before alphanumeric ones.
        """
        identifiers = tuple(
            (0, int(part), "") if part.isdigit() else (1, 0, part)
            for part in self.prerelease
        )
        return (
            self.major,
            self.minor,
            self.patch,
            0 if self.prerelease else 1,
            identifiers,
        )

    def __lt__(self, other: SemVer) -> bool:
        """Semver precedence: True when ``self`` sorts before ``other``."""
        return self._key() < other._key()

    def __le__(self, other: SemVer) -> bool:
        """Semver precedence: True when ``self`` sorts before or equal to ``other``."""
        return self._key() <= other._key()

    def __str__(self) -> str:
        """The canonical ``X.Y.Z[-pre]`` spelling."""
        core = f"{self.major}.{self.minor}.{self.patch}"
        return f"{core}-{'.'.join(self.prerelease)}" if self.prerelease else core


def next_patch(released: str) -> str:
    """The patch after ``released``: 0.4.4 → 0.4.5.

    Raises:
        ReleaseFollowupError: for a prerelease, whose successor (another rc, or
            the final release) is a decision rather than arithmetic.
    """
    version = SemVer.parse(released)
    if version.is_prerelease:
        raise ReleaseFollowupError(
            f"{released} is a prerelease; the version after it is a release "
            "captain's decision, not a patch bump. Open it on dev by hand."
        )
    return str(SemVer(version.major, version.minor, version.patch + 1))


def resolve_next_version(current: str, released: str) -> str:
    """The version dev should carry once ``released`` is out.

    ``current`` equal to ``released`` is the normal case and yields the next
    patch. ``current`` already beyond ``released`` means dev was opened (by an
    earlier run, or by hand with a minor bump) and is kept as it is.

    Raises:
        ReleaseFollowupError: when VERSION on dev is behind the release, which
            means dev is not the branch the release was cut from.
    """
    released_version = SemVer.parse(released)
    current_version = SemVer.parse(current)
    if current_version == released_version:
        return next_patch(released)
    if released_version < current_version:
        return str(current_version)
    raise ReleaseFollowupError(
        f"VERSION on this branch is {current}, behind the released {released}; "
        "refusing to guess which branch the release came from."
    )


def release_date(published_at: str) -> date:
    """The UTC calendar date of a GitHub ``publishedAt`` timestamp.

    Raises:
        ValueError: when the timestamp is not ISO 8601.
    """
    stamp = datetime.fromisoformat(published_at.strip().replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC).date()


def _heading(version: str) -> re.Pattern[str]:
    """Any ``## [version]`` heading line, capturing what follows the bracket."""
    return re.compile(rf"^##\s*\[{re.escape(version)}\](?P<rest>.*)$", re.MULTILINE)


def date_released_heading(text: str, released: str, day: date) -> str:
    """Replace ``## [released] — unreleased`` with ``## [released] — <day>``.

    A heading that already carries a date is left untouched, so a re-run is a
    no-op.

    Raises:
        ReleaseFollowupError: when the changelog has no heading for the
            released version at all — release_checklist.py required one, so
            its absence means the file changed underneath the release.
    """
    match = _heading(released).search(text)
    if match is None:
        raise ReleaseFollowupError(
            f"CHANGELOG.md has no '## [{released}]' heading to date"
        )
    unreleased = re.fullmatch(
        rf"\s*{_DASH}\s*unreleased\s*", match.group("rest"), re.IGNORECASE
    )
    if unreleased is None:
        return text
    dated = f"## [{released}] — {day.isoformat()}"
    return text[: match.start()] + dated + text[match.end() :]


def insert_next_heading(text: str, released: str, upcoming: str) -> str:
    """Open ``## [upcoming] — unreleased`` directly above the released heading.

    Nothing is inserted when a heading for ``upcoming`` already exists.

    Raises:
        ReleaseFollowupError: when there is no released heading to anchor on.
    """
    if _heading(upcoming).search(text):
        return text
    match = _heading(released).search(text)
    if match is None:
        raise ReleaseFollowupError(
            f"CHANGELOG.md has no '## [{released}]' heading to open {upcoming} above"
        )
    opened = f"## [{upcoming}] — unreleased\n\n"
    return text[: match.start()] + opened + text[match.start() :]


@dataclass(frozen=True)
class OpenNextResult:
    """What ``open_next`` decided and changed.

    Attributes:
        next_version: The version dev carries after the run.
        changed: Human-readable descriptions of each file edit; empty when the
            tree was already open.
    """

    next_version: str
    changed: list[str]


def open_next(repo_root: Path, released: str, day: date) -> OpenNextResult:
    """Bump VERSION and rotate CHANGELOG.md for the release of ``released``.

    Manifests that copy VERSION (package.json, lockfiles, docs) are not
    touched here; ``scripts/check_version_parity.py --write`` owns them and is
    run after this.
    """
    changed: list[str] = []

    version_file = repo_root / "VERSION"
    current = version_file.read_text(encoding="utf-8").strip()
    upcoming = resolve_next_version(current, released)
    if current != upcoming:
        version_file.write_text(upcoming + "\n", encoding="utf-8")
        changed.append(f"VERSION: {current} -> {upcoming}")

    changelog = repo_root / "CHANGELOG.md"
    before = changelog.read_text(encoding="utf-8")
    after = date_released_heading(before, released, day)
    if after != before:
        changed.append(f"CHANGELOG.md: dated [{released}] {day.isoformat()}")
    opened = insert_next_heading(after, released, upcoming)
    if opened != after:
        changed.append(f"CHANGELOG.md: opened [{upcoming}] — unreleased")
    if opened != before:
        changelog.write_text(opened, encoding="utf-8")

    return OpenNextResult(next_version=upcoming, changed=changed)


def stale_draft_ids(records: Iterable[dict[str, object]], released: str) -> list[int]:
    """Ids of draft releases at or below ``released``, oldest version first.

    Each record is a GitHub release object (only ``id``, ``tag_name`` and
    ``draft`` are read). Published releases, drafts for a later version, and
    drafts whose tag is not a version are never returned.
    """
    ceiling = SemVer.parse(released)
    stale: list[tuple[SemVer, int]] = []
    for record in records:
        if record.get("draft") is not True:
            continue
        release_id = record.get("id")
        tag = record.get("tag_name")
        if not isinstance(release_id, int) or not isinstance(tag, str):
            continue
        try:
            version = SemVer.parse(tag)
        except ValueError:
            continue
        if version <= ceiling:
            stale.append((version, release_id))
    stale.sort()
    return [release_id for _, release_id in stale]


def read_json_stream(text: str) -> list[dict[str, object]]:
    """Parse a stream of concatenated JSON values, as ``gh api --paginate`` emits.

    Accepts one object per line, pretty-printed objects, or whole page arrays
    back to back (``[...][...]``); arrays are flattened. Non-object values are
    ignored.

    Raises:
        ValueError: when the stream is not valid JSON.
    """
    decoder = json.JSONDecoder()
    records: list[dict[str, object]] = []
    index = 0
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            return records
        value, index = decoder.raw_decode(text, index)
        items = value if isinstance(value, list) else [value]
        records.extend(item for item in items if isinstance(item, dict))


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)

    opener = commands.add_parser(
        "open-next", help="Bump VERSION and rotate CHANGELOG.md"
    )
    opener.add_argument(
        "--released", required=True, help="The version just published, e.g. 0.4.4"
    )
    opener.add_argument(
        "--published-at",
        required=True,
        help="The release's publishedAt timestamp (ISO 8601)",
    )
    opener.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root to edit.",
    )

    drafts = commands.add_parser(
        "stale-drafts",
        help="Print ids of draft releases at or below --released (JSON on stdin)",
    )
    drafts.add_argument("--released", required=True, help="The version just published")

    args = parser.parse_args(argv)
    try:
        if args.command == "open-next":
            result = open_next(
                Path(args.repo_root), args.released, release_date(args.published_at)
            )
            for line in result.changed:
                print(f"  {line}", file=sys.stderr)
            if not result.changed:
                print("  already open; nothing to change", file=sys.stderr)
            print(result.next_version)
            return 0
        for release_id in stale_draft_ids(
            read_json_stream(sys.stdin.read()), args.released
        ):
            print(release_id)
        return 0
    except (ReleaseFollowupError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
