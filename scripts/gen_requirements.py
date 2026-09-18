#!/usr/bin/env python3
"""
Generate apps/backend/requirements.txt from apps/backend/poetry.lock.

Run from the repo root:
    python3 scripts/gen_requirements.py

Or add to Makefile via the `lock` target. Requires no extra dependencies —
uses only the stdlib `re` module so it works in any Python 3 environment.

Only runtime (non-optional) packages are emitted. Dev extras (pytest, ruff,
etc.) are excluded because they are marked `optional = true` in the lock file.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = REPO_ROOT / "apps" / "backend" / "poetry.lock"
OUT_FILE = REPO_ROOT / "apps" / "backend" / "requirements.txt"

# Additional environment markers to append to selected packages.
# - uvloop/greenlet: armv7l builds fail under QEMU emulation.
# - pywin32: Windows-only runtime dependency.
PACKAGE_MARKERS: dict[str, str] = {
    "uvloop": '; platform_machine != "armv7l"',
    "greenlet": '; platform_machine != "armv7l"',
    "pywin32": '; platform_system == "Windows"',
}

HEADER = (
    "# Generated from poetry.lock — do not edit manually.\n"
    "# Regenerate: python3 scripts/gen_requirements.py\n"
)


def parse_lock(lock_path: Path) -> list[tuple[str, str]]:
    content = lock_path.read_text()
    blocks = re.split(r"\n\[\[package\]\]\n", content)
    packages: list[tuple[str, str]] = []
    for block in blocks[1:]:
        name_m = re.search(r'^name\s*=\s*"([^"]+)"', block, re.MULTILINE)
        ver_m = re.search(r'^version\s*=\s*"([^"]+)"', block, re.MULTILINE)
        optional_m = re.search(r"^optional\s*=\s*(true|false)", block, re.MULTILINE)
        if name_m and ver_m:
            optional = optional_m and optional_m.group(1) == "true"
            if not optional:
                packages.append((name_m.group(1), ver_m.group(1)))
    return sorted(packages, key=lambda x: x[0].lower())


def render(lock_path: Path) -> str:
    """Return the exact text requirements.txt should hold for this lock.

    Split out of main() so a repo-policy test can regenerate in memory and
    compare against the committed file without writing to the tree.
    """
    lines = [
        f"{name}=={version}{PACKAGE_MARKERS.get(name.lower(), '')}"
        for name, version in parse_lock(lock_path)
    ]
    return HEADER + "\n".join(lines) + "\n"


def main() -> None:
    if not LOCK_FILE.exists():
        print(f"ERROR: {LOCK_FILE} not found. Run `poetry lock` first.", file=sys.stderr)
        sys.exit(1)

    text = render(LOCK_FILE)
    OUT_FILE.write_text(text)
    count = len(text.splitlines()) - len(HEADER.splitlines())
    print(f"✅ Wrote {count} runtime packages → {OUT_FILE.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
