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

from tests.build._ast_helpers import core_to_services_imports

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
#: MAY ONLY DECREASE.
_MAX_DEFERRED_CORE_TO_SERVICES = 21


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

    assert total <= _MAX_DEFERRED_CORE_TO_SERVICES, (
        f"deferred `core -> services` imports rose to {total}, above the frozen "
        f"{_MAX_DEFERRED_CORE_TO_SERVICES}. Current spread: {per_file}. This ratchet "
        "only ever goes down: remove an inversion rather than raising the number."
    )
