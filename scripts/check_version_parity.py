#!/usr/bin/env python3
"""GOV-09: VERSION is the only hand-edited version. Prove everything agrees.

Run with --expected <v> in the release workflow to also prove the pushed git
tag matches, which release.yml's version job otherwise trusts blindly: it
derived the version from GITHUB_REF_NAME and never compared it to the VERSION
file the artifacts are actually built from.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Every file that carries a copy of the version. apps/backend/pyproject.toml is
# absent on purpose: [tool.hatch.version] reads ../../VERSION directly, so it
# cannot drift.
_JSON_MANIFESTS = ("package.json", "apps/frontend/package.json")

# The lockfiles carry the project's own version too, in two places each: the
# top-level "version" and packages[""].version, which npm keeps in step with
# the manifest beside it. Registered separately from _JSON_MANIFESTS because
# writing one means writing both copies, and because every other "version" in
# the file belongs to a dependency and must never be touched — the root
# lockfile sat two releases behind package.json precisely because nothing here
# was looking at it.
_LOCKFILES = ("package-lock.json", "apps/frontend/package-lock.json")

# A semver-ish token, used to capture the version out of running prose. The
# prerelease part requires each dot to be followed by another character, so a
# sentence-ending period after "1.0.0-rc.3" is left where it belongs.
_VERSION_TOKEN = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"

# Prose that states which release is shipping. The manifests above can be
# parsed; these sentences cannot, so each entry pins the phrasing that carries
# the version and captures it.
#
# This is a registry rather than "every version-shaped token in every doc"
# because most version mentions in the tree are legitimately historical:
# packaging/README.md illustrates a filename pattern, SECURITY_REPORTS/ rows
# cite the release each archived audit actually ran against, and specs/ and
# plans/ describe the tree as it stood on a date. Only claims about what is
# shipping *now* belong here.
_DOC_VERSION_REFS: tuple[tuple[str, str], ...] = (
    ("README.md", rf"^> ({_VERSION_TOKEN})\. Not fully audited"),
    ("SECURITY_REPORTS/README.md", rf"has been re-run against ({_VERSION_TOKEN})"),
    ("SECURITY_REPORTS/README.md", rf"not re-verified against ({_VERSION_TOKEN})"),
    ("docs/assets/screenshots/MANIFEST.md", rf"rendering the ({_VERSION_TOKEN}) UI"),
)


def collect_versions(root: Path) -> dict[str, str]:
    versions = {"VERSION": (root / "VERSION").read_text().strip()}
    for rel in (*_JSON_MANIFESTS, *_LOCKFILES):
        path = root / rel
        if path.exists():
            versions[rel] = json.loads(path.read_text())["version"]
    return versions


def check_parity(root: Path, expected: str | None = None) -> list[str]:
    """Human-readable mismatches; an empty list means parity holds."""
    versions = collect_versions(root)
    canonical = versions["VERSION"]
    problems = [
        f"{source} is {value!r}, but VERSION is {canonical!r}"
        for source, value in versions.items()
        if source != "VERSION" and value != canonical
    ]
    if expected is not None and expected.strip() != canonical:
        problems.append(f"VERSION is {canonical!r}, but expected {expected.strip()}")
    return problems


def check_doc_versions(root: Path, expected: str | None = None) -> list[str]:
    """Human-readable mismatches in the prose that names the shipping release.

    A pattern that stops matching is reported as a failure rather than skipped.
    Silence would be the worse outcome: 0c8c9f3f bumped VERSION and left three
    documents claiming the previous release candidate, and nothing noticed
    because nothing was looking. A registry that quietly matches nothing is
    indistinguishable from no registry at all.
    """
    canonical = (expected or (root / "VERSION").read_text()).strip()
    problems: list[str] = []
    for rel, pattern in _DOC_VERSION_REFS:
        path = root / rel
        if not path.exists():
            problems.append(f"{rel} is registered as naming the shipping release but is missing")
            continue
        found = re.findall(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
        if not found:
            problems.append(
                f"{rel} no longer matches {pattern!r} — the wording changed, so update "
                f"the pattern; do not leave the version unchecked"
            )
            continue
        problems.extend(
            f"{rel} says {value!r}, but VERSION is {canonical!r}"
            for value in found
            if value != canonical
        )
    return problems


def _rewrite_manifest(path: Path, current: str, canonical: str) -> None:
    """Replace only the top-level "version" value, leaving the file otherwise byte-identical.

    Not json.loads/json.dumps: a package.json is hand-maintained, and reflowing
    the whole file to change four characters would bury the one edit that
    matters in a diff nobody can review. The old value is read out of the
    parsed document first, so the string being replaced is known exactly rather
    than guessed at by pattern — a dependency pinned to the same version is
    left alone.
    """
    text = path.read_text(encoding="utf-8")
    needle = f'"version": "{current}"'
    if needle not in text:
        # Unusual spacing. Fall back to a targeted pattern rather than
        # rewriting the document.
        pattern = r'("version"\s*:\s*)"' + re.escape(current) + r'"'
        updated, count = re.subn(pattern, lambda m: f'{m.group(1)}"{canonical}"', text, count=1)
    else:
        updated, count = text.replace(needle, f'"version": "{canonical}"', 1), 1
    if count != 1:
        raise ValueError(f"{path}: could not locate the version field to rewrite")
    path.write_text(updated, encoding="utf-8")


def _rewrite_lockfile(path: Path, canonical: str) -> None:
    """Set both copies of the project's own version, leaving dependencies alone.

    A full JSON round-trip here rather than a textual substitution, because a
    lockfile is full of dependency versions and some of them legitimately equal
    this project's. npm writes these as JSON.stringify(obj, null, 2) followed
    by a newline, which json.dumps(indent=2) reproduces byte for byte, so the
    diff is the two lines that changed and not the whole 600 KB file.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    document["version"] = canonical
    root_package = document.get("packages", {}).get("")
    if root_package is not None and "version" in root_package:
        root_package["version"] = canonical
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _rewrite_doc(path: Path, pattern: str, canonical: str) -> int:
    """Replace the captured version inside each match, leaving the prose alone."""
    text = path.read_text(encoding="utf-8")

    def repl(match: re.Match[str]) -> str:
        whole = match.group(0)
        start = match.start(1) - match.start()
        end = match.end(1) - match.start()
        return whole[:start] + canonical + whole[end:]

    updated, count = re.subn(pattern, repl, text, flags=re.MULTILINE)
    if count and updated != text:
        path.write_text(updated, encoding="utf-8")
    return count


def sync_versions(root: Path, expected: str | None = None) -> list[str]:
    """Rewrite every registered version source to match VERSION. Returns what changed.

    The point of GOV-09 is that VERSION is the only hand-edited version, and
    for apps/backend/pyproject.toml that is literally true — hatch reads the
    file. A package.json cannot, and neither can a sentence in a README, so
    for those "derives from VERSION" has to mean generated from it and gated on
    it. This is the generator; check_parity and check_doc_versions are the gate.

    It shares _JSON_MANIFESTS and _DOC_VERSION_REFS with them deliberately. A
    separate list of places to write would be one more thing that can fall out
    of step with the list of places to check, which is the class of bug this
    whole module exists to prevent.

    Only mechanical edits are made. A document whose wording changed so its
    pattern no longer matches is left untouched for a human, and the gate then
    reports it — sync never invents a sentence.
    """
    canonical = (expected or (root / "VERSION").read_text()).strip()
    changed: list[str] = []

    version_file = root / "VERSION"
    if version_file.read_text().strip() != canonical:
        version_file.write_text(canonical + "\n")
        changed.append(f"VERSION -> {canonical}")

    for rel, current in collect_versions(root).items():
        if rel == "VERSION" or current == canonical:
            continue
        if rel in _LOCKFILES:
            _rewrite_lockfile(root / rel, canonical)
        else:
            _rewrite_manifest(root / rel, current, canonical)
        changed.append(f"{rel}: {current} -> {canonical}")

    for rel, pattern in _DOC_VERSION_REFS:
        path = root / rel
        if not path.exists():
            continue
        before = re.findall(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
        stale = [v for v in before if v != canonical]
        if not stale:
            continue
        _rewrite_doc(path, pattern, canonical)
        changed.extend(f"{rel}: {value} -> {canonical}" for value in stale)

    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert every version source agrees with VERSION.")
    parser.add_argument(
        "--expected", default=None, help="Version the caller (e.g. a git tag) expects"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Rewrite every version source to match VERSION instead of only reporting drift",
    )
    args = parser.parse_args()

    if args.write:
        for line in sync_versions(REPO_ROOT, expected=args.expected):
            print(f"  {line}")

    problems = check_parity(REPO_ROOT, expected=args.expected)
    problems += check_doc_versions(REPO_ROOT, expected=args.expected)
    if problems:
        # After --write these are the edits sync could not make mechanically:
        # a registered document that has been reworded or deleted. Both need a
        # person, and both are reported rather than passed over.
        print("version parity FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"version parity ok: {(REPO_ROOT / 'VERSION').read_text().strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
