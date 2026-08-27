"""`make dev` must not race its own schema, and must declare one worker owner.

Two defects, both surfaced by running `make dev` against a *fresh* database on
2026-08-27 and both invisible against an already-migrated one:

* The three branches (`backend`, `monitor-workers`, `frontend`) are started
  concurrently with `&`, and only `backend` runs `alembic upgrade head`. So the
  monitor scheduler begins ticking once a second while the schema is still
  being created, and every tick raises
  `UndefinedTable: relation "monitor_items" does not exist`. On a migrated
  database the window is zero, which is exactly why this survived: the
  developer who has run it before never sees it, and the one cloning the repo
  sees a wall of tracebacks on their first command.

* `make dev` starts *dedicated* monitor workers while leaving the API process
  on the default `CB_TOPOLOGY_MODE=mono`, which also owns the in-process loops.
  `app/core/topology.py`'s docstring names this as one of the two combinations
  that were "silently wrong rather than rejected", and `app/workers/main.py`
  warns about it on every start. `make dev` was tripping that warning by
  construction.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


def _target(name: str) -> tuple[list[str], str]:
    """Return (prerequisites, recipe) for a Makefile target."""
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}:([^\n]*)\n((?:\t[^\n]*\n|\n)*)", text, re.M)
    assert match, f"no {name} target in the Makefile"
    prereq_part = match.group(1).split("##")[0]
    return prereq_part.split(), match.group(2)


def test_dev_finishes_migrations_before_starting_the_workers():
    """A prerequisite completes before any recipe line runs; a `&` branch does
    not. The barrier has to be the former."""
    prerequisites, _ = _target("dev")
    assert "migrate" in prerequisites, (
        "`make dev` starts monitor-workers concurrently with the backend's own "
        "alembic call, so on a fresh database the scheduler polls tables that "
        "do not exist yet. `migrate` must be a prerequisite of dev, not a step "
        "inside one of the parallel branches. Got: " + " ".join(prerequisites)
    )


def test_dev_hands_the_api_no_inprocess_workers():
    """dev runs dedicated monitor workers, so the API must be mode=api."""
    _, recipe = _target("dev")
    assert "CB_TOPOLOGY_MODE_DEV=api" in recipe, (
        "`make dev` starts dedicated monitor_scheduler and monitor_poll "
        "workers, so the API process must not also own the in-process loops. "
        "Pass CB_TOPOLOGY_MODE_DEV=api to the backend branch."
    )


def test_backend_target_honours_the_topology_override():
    """And the backend target has to actually pass it to the process."""
    _, recipe = _target("backend")
    assert "CB_TOPOLOGY_MODE=" in recipe, (
        "the backend target must set CB_TOPOLOGY_MODE so `make dev` can "
        "declare the API worker-free; without it the override is inert"
    )


def test_standalone_backend_still_owns_its_workers():
    """`make backend` on its own is a single-process appliance: it must stay
    mono, or a developer running just the backend silently loses monitoring."""
    text = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^CB_TOPOLOGY_MODE_DEV\s*\?=\s*mono\s*$", text, re.M), (
        "CB_TOPOLOGY_MODE_DEV must default to mono so that `make backend` "
        "alone keeps running the in-process background workers"
    )


def test_dedicated_workers_declare_themselves_as_workers():
    """The warning is emitted by each worker process from its OWN environment,
    so setting mode=api on the API alone does not silence it -- and should not.
    A dedicated worker is `worker` by definition (app/start.py setdefaults
    exactly that for its own path); leaving it on the mono default means the
    process believes the API is also running its loop."""
    _, recipe = _target("monitor-workers")
    assert "CB_TOPOLOGY_MODE=" in recipe and "worker" in recipe, (
        "monitor-workers runs dedicated worker processes; each must declare "
        "CB_TOPOLOGY_MODE=worker or it resolves to mono and warns on start"
    )
