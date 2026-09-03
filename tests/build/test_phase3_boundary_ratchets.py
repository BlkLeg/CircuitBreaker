"""Phase 3.1 boundary ratchets: counts that may only ever go down.

Route §6 lists these as T0 gates. Each freezes a measured number; new code that
adds a violation fails the build, and a change that removes one is expected to
lower the constant in the same commit. The failure messages say so explicitly,
because a contributor meeting one of these for the first time needs to know that
lowering the number is the correct response and raising it is not.

Every number here was measured against this checkout with `_ast_helpers`, not
copied from the route — the route's F6 count (354) came from an unrecorded grep
and does not reproduce.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORT))

from tests.build._ast_helpers import (
    core_to_services_imports,
    session_op_calls,
    silent_handlers,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_ROOT = _REPO_ROOT / "apps/backend/src/app"
_CORE_ROOT = _APP_ROOT / "core"
_API_ROOT = _APP_ROOT / "api"

#: The single top-level `core -> services` import in the tree.
#: `core.destructive_actions` imports `write_log` at module scope; every other
#: inversion is deferred inside a function. Removing it should empty this set,
#: not extend it.
_ALLOWED_TOP_LEVEL = frozenset({"destructive_actions.py"})

#: Deferred (in-function) `core -> services` imports. F7's remaining surface.
#: EXACT — see `_assert_exact`.
_MAX_DEFERRED_CORE_TO_SERVICES = 21


def _assert_exact(measured: int, frozen: int, *, what: str, detail: str, guidance: str) -> None:
    """Fail when *measured* differs from *frozen* in either direction.

    These began as `<=` bounds, which reads as the safer choice and is not. Slack
    accumulates silently: slice 3.2 removed three direct-DB calls in `api/` and
    left the constant at 581, and the two units of headroom that created went on
    to absorb a real new `db.commit()` added by an unrelated commit while this
    suite stayed green. The gate had already failed at its one job before anyone
    looked at it.

    An exact count has no headroom to donate. It costs a one-line edit in the
    commit that removes a violation — which every docstring here already asked
    for and none of them could enforce.
    """
    if measured == frozen:
        return
    direction = (
        f"rose to {measured}, above the frozen {frozen}"
        if measured > frozen
        else f"fell to {measured}, below the frozen {frozen}"
    )
    tail = (
        guidance
        if measured > frozen
        else (
            "Nothing is wrong — you removed one. Lower the constant to "
            f"{measured} in this same commit. Leaving the higher number behind is "
            "how the gate acquires headroom for the next violation to hide in."
        )
    )
    raise AssertionError(f"{what} {direction}. {detail} {tail}")


def _core_files() -> list[Path]:
    return sorted(_CORE_ROOT.rglob("*.py"))


def test_no_new_top_level_core_to_services_import() -> None:
    offenders: list[str] = []
    for path in _core_files():
        top, _ = core_to_services_imports(path)
        if top and path.name not in _ALLOWED_TOP_LEVEL:
            for lineno, module in top:
                offenders.append(f"{path.relative_to(_APP_ROOT)}:{lineno} -> {module}")

    assert not offenders, (
        "new top-level `core -> services` import(s): "
        f"{offenders}. `core` is the inner layer; importing `services` at module "
        "scope inverts the dependency at import time and can deadlock the import "
        "graph. Import inside the function that needs it, or move the shared piece "
        "down into `core`. Do not add to _ALLOWED_TOP_LEVEL."
    )


def test_deferred_core_to_services_imports_do_not_grow() -> None:
    total = 0
    per_file: dict[str, int] = {}
    for path in _core_files():
        _, deferred = core_to_services_imports(path)
        if deferred:
            per_file[str(path.relative_to(_APP_ROOT))] = len(deferred)
            total += len(deferred)

    _assert_exact(
        total,
        _MAX_DEFERRED_CORE_TO_SERVICES,
        what="deferred `core -> services` imports",
        detail=f"Current spread: {per_file}.",
        guidance="Remove an inversion rather than raising the number.",
    )


#: Direct session operations inside `api/`. Route F6: routes should stay thin and
#: delegate to services. Re-measured at 579 across 41 files on 2026-09-03.
#: EXACT — see `_assert_exact`.
_MAX_DIRECT_DB_CALLS_IN_API = 579


def test_direct_db_access_in_api_does_not_grow() -> None:
    total = 0
    per_file: dict[str, int] = {}
    for path in sorted(_API_ROOT.rglob("*.py")):
        calls = session_op_calls(path)
        if calls:
            per_file[str(path.relative_to(_API_ROOT))] = len(calls)
            total += len(calls)

    worst = sorted(per_file.items(), key=lambda kv: -kv[1])[:5]
    _assert_exact(
        total,
        _MAX_DIRECT_DB_CALLS_IN_API,
        what="direct database calls in api/",
        detail=f"Heaviest files: {worst}.",
        guidance=(
            "Routes stay thin (CLAUDE.md): put the query in a service and call it "
            "from the route."
        ),
    )


#: `except: pass` handlers across the whole backend app. Route F13. 118 as of
#: 2026-09-03 — the notification worker's bare `except: pass` around a nak went
#: when that consumer moved onto the dead-letter path. EXACT — see `_assert_exact`.
_MAX_SILENT_EXCEPT_HANDLERS = 118


def test_silent_exception_handlers_do_not_grow() -> None:
    total = 0
    per_file: dict[str, int] = {}
    for path in sorted(_APP_ROOT.rglob("*.py")):
        handlers = silent_handlers(path)
        if handlers:
            per_file[str(path.relative_to(_APP_ROOT))] = len(handlers)
            total += len(handlers)

    worst = sorted(per_file.items(), key=lambda kv: -kv[1])[:5]
    _assert_exact(
        total,
        _MAX_SILENT_EXCEPT_HANDLERS,
        what="silent exception handlers",
        detail=f"Heaviest files: {worst}.",
        guidance=(
            "A handler that only passes turns a failure into silence, which is what "
            "makes production problems unfindable. Log it, record it, or let it raise."
        ),
    )
