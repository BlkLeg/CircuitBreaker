#!/usr/bin/env python3
"""The release asset names install.sh downloads, read from install.sh itself.

One definition, used by both the release dry run's staged-publication step and
tests/build/test_release_publication_is_gated.py. Before this existed each had
its own regex, and the workflow's took the FIRST `tarball_name="..."` in
install.sh: `local tarball_name="$2"`, a function parameter, so the dry run
went looking for an asset literally named `$2`.

install.sh assigns `tarball_name` more than once. The assignment that names a
release asset is the one built from both the version and the architecture, so
that is the only kind of candidate accepted, and exactly one must exist.

Runs on the ubuntu-22.04 runner's system python3 (3.10) with the stdlib only:
the step that calls it has no setup-python.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

VERSION_PLACEHOLDER = "${CB_VERSION}"
ARCH_PLACEHOLDER = "${ARCH}"
DEFAULT_ARCHES: tuple[str, ...] = ("amd64", "arm64")

_ASSIGNMENT = re.compile(r'tarball_name="([^"]+)"')


class InstallerTemplateError(ValueError):
    """install.sh does not name exactly one release asset template."""


def tarball_template(installer_text: str) -> str:
    """The one `tarball_name` template built from the version and the architecture.

    Raises InstallerTemplateError when there is none, or more than one.
    """
    candidates = [
        value
        for value in _ASSIGNMENT.findall(installer_text)
        if VERSION_PLACEHOLDER in value and ARCH_PLACEHOLDER in value
    ]
    if len(candidates) != 1:
        raise InstallerTemplateError(
            "expected exactly one tarball_name assignment in install.sh built from "
            f"{VERSION_PLACEHOLDER} and {ARCH_PLACEHOLDER}; found {candidates}"
        )
    return candidates[0]


def expected_assets(installer_text: str, version: str, arches: Iterable[str]) -> list[str]:
    """The asset name install.sh would download for *version* on each of *arches*."""
    template = tarball_template(installer_text)
    return [
        template.replace(VERSION_PLACEHOLDER, version).replace(ARCH_PLACEHOLDER, arch)
        for arch in arches
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Check that *release-dir* holds every asset install.sh would download."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--installer", type=Path, default=Path("install.sh"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--arch", action="append", dest="arches")
    parser.add_argument("--release-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    installer = args.installer.read_text(encoding="utf-8")
    try:
        template = tarball_template(installer)
    except InstallerTemplateError as exc:
        print(f"::error::{exc}. Update scripts/ci/installer_assets.py rather than deleting the check.")
        return 1
    print(f"install.sh downloads: {template}")

    names = expected_assets(installer, args.version, args.arches or DEFAULT_ARCHES)
    missing = [name for name in names if not (args.release_dir / name).is_file()]
    if missing:
        print(f"::error::the build produced no asset named {missing}")
        present = sorted(p.name for p in args.release_dir.iterdir()) if args.release_dir.is_dir() else []
        print(f"present: {present}")
        return 1
    print(f"every asset install.sh resolves is present: {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
