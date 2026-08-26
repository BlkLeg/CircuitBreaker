"""Repo-root pytest scope.

`tests/` at the repo root holds two different kinds of suite, and only one of
them is runnable from here.

  * `tests/build/` and `tests/unit/*.py` are repo-policy and pure-logic suites.
    They read the checked-out tree, import nothing from the application, and
    need no services. `pytest tests/` is their intended command, and CI runs
    `pytest tests/build` in the Lint job.

  * `tests/integration/` is backend-scoped despite living here. Its conftest
    does `from app.main import app` at import time, which needs
    `apps/backend/src` on `sys.path`, and its fixtures need a live PostgreSQL
    plus `CB_ALLOW_DEGRADED_DEPENDENCIES` / `CB_ALLOW_DIRECT_EGRESS` (see the
    comment above `test-backend` in the Makefile — those flags are load-bearing,
    not leftovers). It is run by `make test-backend`, which does
    `cd apps/backend && PYTHONPATH=src pytest ../../tests/integration`, and by
    nothing else. No CI job runs it, because no workflow provides the database.

Without this file, `pytest tests/` from the repo root — a command the update
plan's own verification table lists — died during collection with
`ModuleNotFoundError: No module named 'app'` and ran nothing at all, including
the 144 tests that ARE root-scoped.

Adding `apps/backend/src` to the root `pythonpath` would fix the import and
make things worse: collection would succeed and then every integration test
would error in fixture setup against a database that is not there, trading one
honest error for a hundred misleading ones. The honest answer is that these
tests are not meant to run from the root, so that is what is written down here.

The exclusion is announced in the header of every root run rather than applied
silently. pytest.ini exists because a silent zero-collection went unnoticed for
a whole directory; this file must not create a second one.
"""

from __future__ import annotations

collect_ignore = ["tests/integration"]


def pytest_report_header(config) -> str:
    """Say out loud what is being skipped and how to run it."""
    return (
        "root scope: tests/integration is excluded (backend-scoped: needs "
        "apps/backend/src on sys.path and a live PostgreSQL). "
        "Run it with `make test-backend`."
    )
