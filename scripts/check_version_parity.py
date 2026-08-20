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
    for rel in _JSON_MANIFESTS:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert every version source agrees with VERSION.")
    parser.add_argument(
        "--expected", default=None, help="Version the caller (e.g. a git tag) expects"
    )
    args = parser.parse_args()

    problems = check_parity(REPO_ROOT, expected=args.expected)
    problems += check_doc_versions(REPO_ROOT, expected=args.expected)
    if problems:
        print("version parity FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"version parity ok: {(REPO_ROOT / 'VERSION').read_text().strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
