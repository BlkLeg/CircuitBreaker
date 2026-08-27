"""`datetime.utcnow()` is deprecated, and the repo's rule is to fix ours.

Two calls in the API layer failed `tests/integration` under Python 3.14, where
`filterwarnings = error` turns the DeprecationWarning into a test failure. They
survived because CI runs 3.12, where the warning does not fire, and because
`tests/integration` is not in CI's backend job at all.

Suppressing it would have been wrong twice over. It is our code, so the rule in
apps/backend/pyproject.toml's filter block applies -- suppress third-party,
fix ours. And `utcnow()` returns a *naive* datetime, so `.isoformat()` wrote a
string with no offset; the frontend renders those with `new Date(...)`, which
reads a bare timestamp as local time and therefore displayed a UTC value at the
wrong hour.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tracked_backend_sources() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "apps/backend/src/**/*.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [REPO_ROOT / p for p in out]


def test_backend_source_uses_timezone_aware_utc():
    offenders = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}"
        for path in _tracked_backend_sources()
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if "datetime.utcnow()" in line
    ]
    assert not offenders, (
        "datetime.utcnow() is deprecated and returns a naive datetime; use "
        "datetime.now(UTC). Found at:\n  " + "\n  ".join(offenders)
    )
