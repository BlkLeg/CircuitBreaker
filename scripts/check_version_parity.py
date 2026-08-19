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
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Every file that carries a copy of the version. apps/backend/pyproject.toml is
# absent on purpose: [tool.hatch.version] reads ../../VERSION directly, so it
# cannot drift.
_JSON_MANIFESTS = ("package.json", "apps/frontend/package.json")


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert every version source agrees with VERSION.")
    parser.add_argument(
        "--expected", default=None, help="Version the caller (e.g. a git tag) expects"
    )
    args = parser.parse_args()

    problems = check_parity(REPO_ROOT, expected=args.expected)
    if problems:
        print("version parity FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"version parity ok: {(REPO_ROOT / 'VERSION').read_text().strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
