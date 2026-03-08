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

# Packages that have no pre-built wheels for linux/arm/v7 (armv7l) and whose
# source builds fail under QEMU emulation.  Each entry maps a lowercase package
# name to the PEP 508 environment marker appended to the pinned line.
#
#   uvloop   — optional uvicorn event-loop accelerator; stdlib asyncio is used
#              as fallback.  libuv's autoconf/automake configure step crashes
#              under QEMU arm emulation.
#   greenlet — used by SQLAlchemy async; CB uses synchronous SQLAlchemy only,
#              so it is safe to omit on armv7l.
ARMV7L_EXCLUSIONS: dict[str, str] = {
    "uvloop":   '; platform_machine != "armv7l"',
    "greenlet": '; platform_machine != "armv7l"',
}


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


def main() -> None:
    if not LOCK_FILE.exists():
        print(f"ERROR: {LOCK_FILE} not found. Run `poetry lock` first.", file=sys.stderr)
        sys.exit(1)

    packages = parse_lock(LOCK_FILE)
    lines = [
        f"{name}=={version}{ARMV7L_EXCLUSIONS.get(name.lower(), '')}"
        for name, version in packages
    ]

    OUT_FILE.write_text(
        "# Generated from poetry.lock — do not edit manually.\n"
        "# Regenerate: python3 scripts/gen_requirements.py\n"
        + "\n".join(lines)
        + "\n"
    )
    print(f"✅ Wrote {len(lines)} runtime packages → {OUT_FILE.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
