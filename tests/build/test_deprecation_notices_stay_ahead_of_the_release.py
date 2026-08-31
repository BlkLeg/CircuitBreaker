"""A deprecation notice that has already come due is worse than none at all.

v0.4.0 shipped telling operators "CB_API_TOKEN is deprecated and will be removed
in v0.4.0" — from inside v0.4.0. Read literally it says the feature the user is
currently relying on is already gone, which is false; read charitably it says
nothing at all. Either way it teaches people to ignore the warnings, and the one
that eventually matters gets ignored with the rest.

The mistake is structural: the notice was accurate when written, and nothing
re-read it when VERSION moved. This test is that reader. It fails the build the
moment a shipped notice names a version this release has reached, which is the
release where someone must either do the removal or push the date out.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = REPO_ROOT / "VERSION"

# Source and deployment artifacts only. docs/ is excluded on purpose: a
# changelog saying "SQLite was removed in v0.2.0" is a true statement about the
# past, not a promise about the future.
SEARCH_ROOTS = (
    "apps/backend/src",
    "apps/frontend/src",
    "apps/agent",
    "deploy",
    "scripts",
    "docker",
)
SEARCH_FILES = ("install.sh",)
SUFFIXES = {".py", ".sh", ".js", ".jsx", ".go", ".conf", ".service", ".template", ".yml", ".yaml"}

# "will be removed in v0.5.0", "removal in v1.0", "removed in version 0.6.0"
NOTICE = re.compile(
    r"(?i)\bremov(?:ed|al|ing)\b[^.\n]{0,60}?\bin\s+(?:version\s+)?v?(\d+)\.(\d+)(?:\.(\d+))?"
)


def _current_version() -> tuple[int, int, int]:
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", raw)
    assert match, f"VERSION is not a semantic version: {raw!r}"
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _candidate_files() -> list[Path]:
    files = [REPO_ROOT / name for name in SEARCH_FILES]
    for root in SEARCH_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        files.extend(
            path
            for path in base.rglob("*")
            if path.is_file()
            and path.suffix in SUFFIXES
            and "node_modules" not in path.parts
            and "__pycache__" not in path.parts
        )
    return files


def test_no_shipped_notice_promises_a_removal_this_release_has_already_reached():
    """Every "will be removed in vX.Y.Z" must name a version strictly ahead of the
    one being shipped, or the notice is telling the operator something untrue
    about the software they are running right now."""
    current = _current_version()
    stale: list[str] = []

    for path in _candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in NOTICE.finditer(text):
            named = (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3) or 0),
            )
            if named > current:
                continue
            line = text[: match.start()].count("\n") + 1
            rel = path.relative_to(REPO_ROOT).as_posix()
            stale.append(f"{rel}:{line}: {match.group(0).strip()}")

    assert not stale, (
        "These notices name a removal version that VERSION ("
        + ".".join(str(part) for part in current)
        + ") has already reached, so they ship claiming a feature is gone while "
        "it still works:\n  "
        + "\n  ".join(stale)
        + "\n\nEither perform the removal, or move the notice to a version this "
        "release has not reached. Do not delete the warning to make this pass."
    )
