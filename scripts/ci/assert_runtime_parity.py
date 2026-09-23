#!/usr/bin/env python3
"""Refuse a release whose image and native tree were not built from the same inputs.

D7 of docs/superpowers/specs/2026-09-22-installer-and-release-design.md: the
mono image rebuilds the tree from the same pins rather than copying the native
build's output, and this is the assertion that makes "the same" a fact. Both
sides write share/build-info.json; the fields below are the ones that must agree.
built_by, distro, ci_run and commit legitimately differ and are not compared.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

COMPARED: tuple[str, ...] = (
    "runtime",
    "python",
    "pbs_release",
    "pbs_sha256",
    "lock_sha256",
    "runtime_digest",
)


def main(argv: list[str]) -> int:
    """Compare two build-info.json files; exit 1 with the first differing field named."""
    if len(argv) != 3:
        print(f"usage: {argv[0]} <native build-info.json> <image build-info.json>", file=sys.stderr)
        return 2
    native = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    image = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    failures: list[str] = []
    for field in COMPARED:
        left, right = native.get(field), image.get(field)
        if left is None or right is None:
            failures.append(f"{field}: missing (native={left!r}, image={right!r})")
        elif left != right:
            failures.append(f"{field}: native={left!r} image={right!r}")
    if failures:
        print("::error::the mono image and the native tree were not built from the same inputs:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"runtime parity OK — {native['runtime']} {native['python']} digest {native['runtime_digest'][:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
