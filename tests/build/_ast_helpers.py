"""AST walkers shared by the Phase 3 boundary ratchets.

Three gates count three different things, but they must agree on what a
"session operation", an "import", and a "silent handler" are — otherwise a
refactor can lower one count while raising another and the suite still passes.
One module, one definition each.

`ast` rather than grep, deliberately. The route's own F6 number (354) came from
a grep pattern it does not record, and could not be reproduced: the same
finding measures 581 here. A gate whose count cannot be re-derived is not a
gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Parameter names bound to a SQLAlchemy `Session` in this codebase. `db` is the
#: `Depends(get_db)` convention; the other two appear in older routes.
SESSION_RECEIVERS = frozenset({"db", "session", "sess"})

#: Session methods that read or write the database. Deliberately excludes
#: `close`, which is lifecycle rather than data access, and pure builders.
SESSION_OPS = frozenset(
    {
        "query",
        "add",
        "add_all",
        "commit",
        "refresh",
        "delete",
        "execute",
        "get",
        "flush",
        "merge",
        "scalar",
        "scalars",
        "rollback",
        "bulk_save_objects",
    }
)

Import = tuple[int, str]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def session_op_calls(path: Path) -> list[tuple[int, str]]:
    """Every `<session>.<op>(...)` call in *path*, as `(lineno, op)`.

    Calls only. `fn = db.execute` hands the method somewhere else and is rare
    enough to review by hand; counting it would make the number move on
    refactors that change no database access.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(_parse(path)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in SESSION_RECEIVERS
            and node.func.attr in SESSION_OPS
        ):
            found.append((node.lineno, node.func.attr))
    # `ast.walk` is breadth-first, so a call nested inside another expression is
    # yielded after shallower ones regardless of where it sits in the file.
    # Sorting by line makes the output source-ordered and therefore reproducible
    # — a counter whose report reshuffles between runs is hard to diff and hard
    # to trust.
    return sorted(found)


def core_to_services_imports(path: Path) -> tuple[list[Import], list[Import]]:
    """`app.services` imports in *path*, split into (top-level, deferred).

    The split is the whole point. A top-level import creates a real import-time
    dependency from `core` to `services` and can deadlock the import graph. An
    import inside a function is the deliberate idiom for breaking exactly that
    cycle — it is still an inversion worth counting down, but it is not the same
    defect and must not be banned outright, because 21 of the 22 in this tree
    are of that kind.
    """
    tree = _parse(path)
    inside_function: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                inside_function.add(id(child))

    top: list[Import] = []
    deferred: list[Import] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("app.services"):
                modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(
                a.name for a in node.names if a.name.startswith("app.services")
            )
        for module in modules:
            (deferred if id(node) in inside_function else top).append(
                (node.lineno, module)
            )
    return sorted(top), sorted(deferred)


def silent_handlers(path: Path) -> list[int]:
    """Line numbers of `except` handlers that swallow without acting.

    A leading docstring does not make a handler non-silent — it explains the
    silence, it does not end it — so it is stripped before the body is judged.
    `...` counts the same as `pass`.
    """
    found: list[int] = []
    for node in ast.walk(_parse(path)):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = [
            stmt
            for stmt in node.body
            if not (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            )
        ]
        if len(body) != 1:
            continue
        only = body[0]
        is_pass = isinstance(only, ast.Pass)
        is_ellipsis = (
            isinstance(only, ast.Expr)
            and isinstance(only.value, ast.Constant)
            and only.value.value is Ellipsis
        )
        if is_pass or is_ellipsis:
            found.append(node.lineno)
    return sorted(found)
