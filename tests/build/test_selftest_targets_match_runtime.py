"""The self-test must check what the runtime actually loads.

A self-test naming a hand-copied list of modules is a second source of truth,
and the first time the two disagree the gate passes on a binary the runtime
cannot start. That is the v0.4.2 failure with an extra step, so both halves of
what --selftest checks are pinned to the code that does the loading.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "apps" / "backend" / "src"
WORKERS_MAIN = BACKEND_SRC / "app" / "workers" / "main.py"

sys.path.insert(0, str(BACKEND_SRC))


def _dispatch_branch_types() -> set[str]:
    """Every worker type string compared against in `_dispatch`.

    Read from the AST rather than by importing, so this suite stays runnable
    without the backend's dependency tree installed.
    """
    tree = ast.parse(WORKERS_MAIN.read_text(encoding="utf-8"), filename=str(WORKERS_MAIN))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != "_dispatch":
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Compare) or len(inner.comparators) != 1:
                continue
            left, right = inner.left, inner.comparators[0]
            if (
                isinstance(left, ast.Name)
                and left.id == "kind"
                and isinstance(right, ast.Constant)
                and isinstance(right.value, str)
            ):
                found.add(right.value)
    return found


def test_worker_modules_covers_every_dispatch_branch() -> None:
    from app.workers.main import WORKER_MODULES

    branches = _dispatch_branch_types()
    assert branches, (
        "No `kind == \"...\"` comparisons were found in _dispatch. Either the "
        "function was restructured or this parser is broken; either way the "
        "assertion below would pass vacuously."
    )
    missing = branches - set(WORKER_MODULES)
    extra = set(WORKER_MODULES) - branches
    assert not missing, (
        f"_dispatch handles worker types {sorted(missing)} that WORKER_MODULES "
        "does not list, so --selftest would not check the module they load. "
        "Add them to WORKER_MODULES."
    )
    assert not extra, (
        f"WORKER_MODULES lists {sorted(extra)}, which _dispatch cannot dispatch. "
        "Remove them, or add the dispatch branch."
    )
