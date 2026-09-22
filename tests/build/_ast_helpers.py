"""AST walkers shared by the boundary ratchets.

Four gates count four different things, but they must agree on what a
"session operation", an "import", a "silent handler" and an "import-time
filesystem write" are — otherwise a refactor can lower one count while raising
another and the suite still passes. One module, one definition each.

`ast` rather than grep, deliberately. The route's own F6 number (354) came from
a grep pattern it does not record, and could not be reproduced: the same
finding measures 581 here. A gate whose count cannot be re-derived is not a
gate.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
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


#: `pathlib.Path` / `shutil` method names that mutate the filesystem. A call
#: to one of these, reached at import time, is what made importing
#: `app.api.assets` fail as an unprivileged user in an unwritable cwd — see
#: `test_import_time_side_effects.py`.
#:
#: Deliberately excludes `rename`, `replace` and `copy`: all three are common
#: method names on non-filesystem builtins (`str.replace`, `dict.copy`,
#: `dataclasses.replace`) and a pure attribute-name match cannot tell them
#: apart from `Path.rename`/`Path.replace`/`shutil.copy` without type
#: inference. `str.replace` at module level is exactly the false positive
#: this exclusion exists to avoid — measured against this tree.
_FS_WRITE_METHODS = frozenset(
    {
        "mkdir",
        "makedirs",
        "touch",
        "write_text",
        "write_bytes",
        "unlink",
        "rmtree",
        "chmod",
        "chown",
        "symlink",
        "copy2",
        "copyfile",
        "copytree",
    }
)

#: `open()` mode characters that mutate the filesystem. Read-only modes ("r",
#: "rb") are not in this set on purpose.
_WRITE_MODE_CHARS = frozenset("wax+")


def _is_write_open_call(node: ast.Call) -> bool:
    if not (isinstance(node.func, ast.Name) and node.func.id == "open"):
        return False
    mode_arg: ast.expr | None = node.args[1] if len(node.args) >= 2 else None
    for kw in node.keywords:
        if kw.arg == "mode":
            mode_arg = kw.value
    if not (isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str)):
        return False
    return any(ch in _WRITE_MODE_CHARS for ch in mode_arg.value)


def _is_fs_write_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute) and node.func.attr in _FS_WRITE_METHODS:
        return True
    return _is_write_open_call(node)


def _contains_fs_write(node: ast.AST) -> bool:
    """Whether *node*'s subtree contains a filesystem-mutating call anywhere.

    Used only on function bodies, to decide whether calling that function is
    itself a filesystem write — deliberately a full `ast.walk`, not a pruned
    one: a function that writes via a nested helper still writes.
    """
    return any(_is_fs_write_call(n) for n in ast.walk(node))


def _iter_import_time_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """Yield *node* and every descendant that runs when the module is imported.

    Does not descend into a function/class body or a lambda — those run
    later, not at import time. A `def`'s decorators and default-argument
    expressions DO run at import time, so those are visited before the body
    is pruned.
    """
    yield node
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        for decorator in node.decorator_list:
            yield from _iter_import_time_nodes(decorator)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    yield from _iter_import_time_nodes(default)
        return
    if isinstance(node, ast.Lambda):
        return
    for child in ast.iter_child_nodes(node):
        yield from _iter_import_time_nodes(child)


def module_level_filesystem_writes(path: Path) -> list[int]:
    """Line numbers of filesystem-mutating calls this module makes at import.

    Two shapes are caught: a direct write call at module scope (inside an
    `if`/`try`/`with`/`for` is still module scope — only a `def`/`class`/
    `lambda` body is not), and a module-scope call to a function *defined in
    this same module* whose own body writes — the `_ensure_dir()` pattern
    that made `app.db.cve_session` fail alongside `app.api.assets` and
    `app.api.static_spa`, and that a scan limited to direct calls would miss.
    """
    tree = _parse(path)

    functions_that_write: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _contains_fs_write(node):
            functions_that_write.add(node.name)

    found: list[int] = []
    for top_level_node in tree.body:
        for node in _iter_import_time_nodes(top_level_node):
            if _is_fs_write_call(node):
                found.append(node.lineno)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in functions_that_write
            ):
                found.append(node.lineno)
    return sorted(set(found))


def static_files_calls_missing_check_dir_false(path: Path) -> list[int]:
    """Line numbers of `StaticFiles(...)` calls that do not pass `check_dir=False`.

    `StaticFiles.__init__` defaults to `check_dir=True`, which stats the
    directory during construction — at import time, for any mount built at
    module scope or from `app.main`'s straight-line construction. A directory
    this process cannot create must not be able to stop the application from
    importing; `check_dir=False` defers that check to the first request,
    where a missing directory is a 404, not an ImportError.
    """
    found: list[int] = []
    for node in ast.walk(_parse(path)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "StaticFiles"
        ):
            continue
        has_false = any(
            kw.arg == "check_dir"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is False
            for kw in node.keywords
        )
        if not has_false:
            found.append(node.lineno)
    return sorted(found)
