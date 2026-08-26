"""REL-20: deterministic shard assignment for the backend test suite.

The backend suite is the long pole in every workflow — ~2900 tests behind a
TimescaleDB testcontainer — so CI runs it in parallel shards. "Deterministic"
is the requirement that makes that safe to reason about: a given test file
lands in the same shard on every run, on every machine, and on every Python
build, so "shard 3 failed" names a reproducible set of tests rather than
whatever a scheduler happened to hand that worker.

How the assignment works, and why this way:

  * **Hash the path, do not slice the list.** ``blake2b(path) % total`` moves a
    file between shards only when its own path changes. Slicing a sorted list
    into N chunks — or round-robin over it — reassigns roughly half the suite
    whenever a file is added or renamed, which destroys the run-to-run
    comparability the shards exist to give.
  * **blake2b, not ``hash()``.** CPython salts ``hash()`` of ``str`` per
    process unless ``PYTHONHASHSEED`` is set, so a ``hash()``-based split is a
    different split on every invocation. That is the exact failure this module
    is named for.
  * **Whole files, not individual tests.** Module- and class-scoped fixtures
    stay inside one shard, so sharding cannot change what a test sees. It also
    keeps the command short enough to pass as argv.
  * **Enumerate the filesystem, not the git index.** ``git ls-files`` misses a
    test file that exists but is not yet committed, and a shard runner that
    silently drops uncommitted tests is worse than no sharding: the suite goes
    green having never run them. The rule below is pytest's own —
    ``testpaths = ["tests"]`` and ``python_files = "test_*.py"`` from
    ``apps/backend/pyproject.toml``.

The partition is exact by construction (every file matches exactly one
residue), and ``tests/build/test_backend_shard.py`` holds that to the real
tree rather than to an example.

Run as a script, it prints one path per line, relative to ``apps/backend``,
which is the directory CI invokes pytest from:

    python3 tests/build/backend_shard.py --index 3 --total 4
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "apps/backend"

# apps/backend/pyproject.toml: testpaths = ["tests"], python_files = "test_*.py".
TESTPATH = "tests"
TEST_FILE_GLOB = "test_*.py"

# The shard count CI uses. The workflows do not read this — a GitHub matrix
# cannot be computed at runtime — so they carry the literal `shard: [1, 2, 3, 4]`
# and tests/build/test_ci_evidence_retention.py asserts the two agree. Changing
# the count means changing both, and the test is what makes that unavoidable.
CI_SHARD_TOTAL = 4


def backend_test_files() -> list[str]:
    """Every backend test file pytest would collect, relative to apps/backend.

    Sorted so the listing itself is reproducible; the shard assignment does not
    depend on the order, but a diffable manifest in the CI artifacts does.
    """
    root = BACKEND / TESTPATH
    return sorted(
        path.relative_to(BACKEND).as_posix()
        for path in root.rglob(TEST_FILE_GLOB)
        if path.is_file() and "__pycache__" not in path.parts
    )


def shard_of(path: str, total: int) -> int:
    """1-based shard number for `path`, stable across processes and platforms."""
    if total < 1:
        raise ValueError(f"total must be >= 1, got {total}")
    digest = hashlib.blake2b(path.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % total + 1


def select(index: int, total: int, files: list[str] | None = None) -> list[str]:
    if not 1 <= index <= total:
        raise ValueError(f"shard index {index} is outside 1..{total}")
    candidates = backend_test_files() if files is None else files
    return [path for path in candidates if shard_of(path, total) == index]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, required=True, help="1-based shard number")
    parser.add_argument("--total", type=int, required=True, help="number of shards")
    args = parser.parse_args(argv)

    selected = select(args.index, args.total)
    if not selected:
        # A silently empty shard is the dangerous outcome: pytest with no file
        # arguments falls back to `testpaths` and runs the WHOLE suite, so an
        # empty selection would look like a very slow but passing shard while
        # the other shards ran the same tests again.
        print(
            f"shard {args.index}/{args.total} selected no test files out of "
            f"{len(backend_test_files())} — refusing to hand pytest an empty "
            f"argument list, which would silently re-run the entire suite",
            file=sys.stderr,
        )
        return 1
    print("\n".join(selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
