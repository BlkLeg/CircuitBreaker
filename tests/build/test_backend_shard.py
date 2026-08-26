"""REL-20: the backend shard split must be a partition, and must not move.

Two properties, and both have a concrete failure behind them.

*Exactness.* Every backend test file lands in exactly one shard. A file in no
shard is a test that stopped running while CI stayed green — the same silent
zero-collection that ``/pytest.ini`` exists to prevent, arriving by a different
route. A file in two shards wastes a runner and, worse, makes a flaky test look
like it failed twice.

*Stability.* The same file lands in the same shard on every run. Without it,
"shard 2 is red" is not a reproducible statement, and comparing two runs of the
suite means comparing two different partitions of it. CPython salts ``hash()``
per process, so this is a property that has to be asserted rather than assumed.

These run against the real tree, not a fixture list, because the property that
matters is the one holding for the files CI will actually shard.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# `pytest tests/build` from the repo root puts the root on sys.path via the
# root conftest, but this suite is also run by path from other directories.
# Importing the module under one name matters: the monkeypatch below patches
# `tests.build.backend_shard`, and a second copy imported as `build.backend_shard`
# would leave the patch pointing at an object nothing calls.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.build.backend_shard import (  # noqa: E402
    BACKEND,
    CI_SHARD_TOTAL,
    backend_test_files,
    main,
    select,
    shard_of,
)

# The count CI uses, read from the module rather than repeated here.
# test_ci_evidence_retention.py holds the workflow matrices to the same number.
SHARD_TOTAL = CI_SHARD_TOTAL


def test_the_backend_suite_is_found_at_all():
    """The enumeration rule is pytest's; if it stops matching, every shard is
    empty and the guard in `main` is the only thing standing between that and a
    green run that tested nothing."""
    files = backend_test_files()
    assert len(files) > 150, f"only {len(files)} backend test files found"
    assert all((BACKEND / path).is_file() for path in files)
    assert all(path.startswith("tests/") for path in files)


def test_every_file_lands_in_exactly_one_shard():
    files = backend_test_files()
    assigned = Counter()
    for index in range(1, SHARD_TOTAL + 1):
        for path in select(index, SHARD_TOTAL):
            assigned[path] += 1

    missing = sorted(set(files) - set(assigned))
    duplicated = sorted(path for path, count in assigned.items() if count > 1)
    assert not missing, (
        f"{len(missing)} backend test file(s) belong to no shard and would "
        f"never run: {missing[:10]}"
    )
    assert not duplicated, f"file(s) assigned to more than one shard: {duplicated[:10]}"
    assert sum(assigned.values()) == len(files)


def test_no_shard_is_empty():
    """An empty selection makes pytest fall back to `testpaths` and re-run the
    whole suite, which reads as a slow pass rather than as a misconfiguration."""
    for index in range(1, SHARD_TOTAL + 1):
        assert select(index, SHARD_TOTAL), f"shard {index}/{SHARD_TOTAL} is empty"


def test_the_assignment_does_not_depend_on_the_process():
    """`hash()` of a str is salted per process unless PYTHONHASHSEED is set.

    A subprocess with a deliberately different hash seed must produce the same
    shard as this one; that is the difference between blake2b and `hash()`, and
    it is the whole determinism claim.
    """
    expected = select(2, SHARD_TOTAL)
    result = subprocess.run(
        [sys.executable, "tests/build/backend_shard.py", "--index", "2", "--total", str(SHARD_TOTAL)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        # The parent environment is kept and only the seed overridden: a
        # stripped env would prove the shard is stable under a different
        # interpreter setup, which is a different and weaker claim.
        env={**os.environ, "PYTHONHASHSEED": "12345"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == expected


def test_the_assignment_does_not_depend_on_the_other_files():
    """Adding a file must not reshuffle the ones already placed.

    This is the property a list-slicing split does not have, and the reason a
    hash is used: a run of the suite stays comparable to the run before it.
    """
    files = backend_test_files()
    before = {path: shard_of(path, SHARD_TOTAL) for path in files}
    after = {
        path: shard_of(path, SHARD_TOTAL)
        for path in [*files, "tests/test_a_file_added_later.py"]
    }
    moved = {path for path in files if before[path] != after[path]}
    assert not moved, f"adding one file moved {len(moved)} others between shards"


def test_the_shards_are_not_wildly_unbalanced():
    """Balance is not correctness, but a shard holding most of the suite makes
    the parallelism decorative. File counts, not test counts — the split is by
    file, and counting tests would need a collection run behind a database."""
    sizes = [len(select(index, SHARD_TOTAL)) for index in range(1, SHARD_TOTAL + 1)]
    assert min(sizes) * 2 >= max(sizes), f"shard sizes are lopsided: {sizes}"


def test_an_out_of_range_shard_is_refused_rather_than_silently_empty():
    for index, total in ((0, 4), (5, 4), (-1, 4)):
        try:
            select(index, total)
        except ValueError:
            continue
        raise AssertionError(f"select({index}, {total}) did not refuse")


def test_the_script_refuses_an_empty_selection(capsys, monkeypatch):
    """The guard that stops pytest re-running the whole suite under a shard's
    name. Forced here by handing the selector a tree with no test files."""
    monkeypatch.setattr("tests.build.backend_shard.backend_test_files", lambda: [])
    assert main(["--index", "1", "--total", "4"]) == 1
    assert "refusing" in capsys.readouterr().err
