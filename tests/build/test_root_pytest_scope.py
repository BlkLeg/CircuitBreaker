"""`pytest tests/` from the repo root must actually run.

PREEXISTING-2. The command died during collection with
``ModuleNotFoundError: No module named 'app'``: ``tests/integration/conftest.py``
does ``from app.main import app`` at import time, which needs
``apps/backend/src`` on ``sys.path``. One un-importable conftest aborts the
whole run, so the 144 tests that ARE root-scoped -- every repo-policy suite in
``tests/build`` among them -- ran not at all. Verified identical at base commit
021780a0, so it predates this branch; the update plan's own verification table
lists the command, which is how a verification path that cannot run went
unnoticed.

``tests/integration`` is backend-scoped despite its location: ``make
test-backend`` runs it as ``cd apps/backend && PYTHONPATH=src pytest
../../tests/integration``, with a live PostgreSQL and the CB_ALLOW_* flags the
Makefile documents. ``/conftest.py`` says so and excludes it from root
collection, announcing the exclusion in the run header rather than dropping it
silently -- pytest.ini exists because a silent zero-collection went unnoticed
once already.

Two properties are pinned here, and they pull against each other on purpose:
the root command must succeed, and it must not succeed by collecting nothing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_CONFTEST = REPO_ROOT / "conftest.py"


def _collect(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args, "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_pytest_tests_collects_from_the_repo_root():
    result = _collect("tests/")
    assert result.returncode == 0, (
        "`pytest tests/` from the repo root must collect cleanly.\n"
        f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-2000:]}"
    )
    assert "No module named 'app'" not in result.stdout + result.stderr


def test_the_root_run_is_not_empty():
    """Succeeding by collecting nothing is the failure mode pytest.ini exists
    to prevent. tests/build alone is dozens of files."""
    result = _collect("tests/")
    assert " tests collected" in result.stdout, result.stdout[-2000:]
    count = int(result.stdout.split(" tests collected")[0].strip().split("\n")[-1])
    assert count > 100, f"root collection dropped to {count} tests"


def test_a_bare_pytest_at_the_root_also_collects():
    """pytest.ini's `testpaths = tests` means the bare command takes the same
    path, so it must not be left broken either."""
    assert _collect().returncode == 0


def test_the_exclusion_is_announced_rather_than_silent():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert "tests/integration is excluded" in result.stdout, result.stdout[:2000]
    assert "make test-backend" in result.stdout


def test_the_root_conftest_documents_why_rather_than_just_ignoring():
    """A bare `collect_ignore` with no reason is how the next person deletes it."""
    source = ROOT_CONFTEST.read_text(encoding="utf-8")
    assert 'collect_ignore = ["tests/integration"]' in source
    assert "make test-backend" in source
    assert "PostgreSQL" in source


def test_the_integration_suite_is_not_deleted_or_emptied():
    """The fix may not be "remove the tests that do not collect"."""
    integration = REPO_ROOT / "tests/integration"
    assert integration.is_dir()
    assert len(list(integration.glob("test_*.py"))) > 20
