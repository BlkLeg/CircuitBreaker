"""Importing `app` must not touch the filesystem or leave a StaticFiles mount
depending on a directory the import already created.

A T0 gate: the allowlist below is frozen at empty and must only ever shrink.
`app.api.assets`, `app.api.static_spa` and `app.db.cve_session` each used to
`mkdir` a relative, cwd-derived path at module scope — the defect the
installer journey's `runuser -u breaker -- circuit-breaker --selftest`
assertion caught (see `apps/backend/tests/test_import_purity.py` for the
subprocess-level reproduction). Directory creation belongs at the point
something actually writes, or in `app.startup.bootstrap.validate_data_dir_writable`,
which already exists for exactly this and runs in the lifespan, not at import.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORT))

from tests.build._ast_helpers import (
    module_level_filesystem_writes,
    static_files_calls_missing_check_dir_false,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_ROOT = _REPO_ROOT / "apps/backend/src/app"

#: Files allowed to write at import time, and why. Frozen at empty: this ratchet
#: may only ever shrink. Nothing is on it today — add an entry only alongside a
#: comment explaining why that specific write cannot be deferred, the way this
#: docstring documents the ones that were removed rather than allowed.
_ALLOWED: frozenset[str] = frozenset()


def _app_files() -> list[Path]:
    return sorted(_APP_ROOT.rglob("*.py"))


def test_no_module_level_filesystem_writes() -> None:
    offenders: list[str] = []
    for path in _app_files():
        rel = str(path.relative_to(_APP_ROOT))
        if rel in _ALLOWED:
            continue
        for lineno in module_level_filesystem_writes(path):
            offenders.append(f"{rel}:{lineno}")

    assert not offenders, (
        "import-time filesystem write(s) found: "
        f"{offenders}. Importing `app` must never write to disk — it runs as "
        "`--selftest`, for an unprivileged user, in an arbitrary and possibly "
        "unwritable cwd. Move the write into the function that actually needs "
        "it (mkdir immediately before the write it guards), or into "
        "app.startup.bootstrap.validate_data_dir_writable if it belongs at "
        "startup. Do not add to _ALLOWED without a comment explaining why the "
        "write cannot be deferred."
    )


def test_every_staticfiles_mount_tolerates_a_missing_directory() -> None:
    offenders: list[str] = []
    for path in _app_files():
        for lineno in static_files_calls_missing_check_dir_false(path):
            offenders.append(f"{path.relative_to(_APP_ROOT)}:{lineno}")

    assert not offenders, (
        f"StaticFiles(...) call(s) without check_dir=False: {offenders}. "
        "check_dir defaults to True, which stats the directory during "
        "construction — at import time, for any mount built at module scope "
        "or from app.main's straight-line app construction. A directory this "
        "process cannot create must not be able to stop the application from "
        "importing; check_dir=False defers the check to the first request, "
        "where a missing directory is a 404, not an ImportError."
    )
