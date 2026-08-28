"""A function-local import of a module already imported at file scope makes that
name local for the WHOLE function — including every line above the import.

Found by Tier 3 (ADR 0005 Phase 2), four layers into a packaged boot:

    File "start.py", line 353, in main
    UnboundLocalError: cannot access local variable 'os'

`start.py` imports os at line 6. `main()` re-imported it inside
`if args.worker_type:`, so in API mode — the branch that does not run — `os` was
unbound at line 353. That line is

    os.environ["CB_AUTO_MIGRATE"] = "false"

whose own comment cites `(#87 / #81)`. It is the guard added to stop workers
re-running migrations against a partially initialised app. It had never once
executed: the packaged API server raised UnboundLocalError before reaching
uvicorn.

Nothing caught it because nothing ran the file. `make dev` starts
`uvicorn app.main:app` directly, the test suites import `app.main`, and
`start.py` is only ever the entrypoint of the frozen binary — which no gate
booted until this one.

The rule is narrow on purpose: a local import that shadows nothing is a
legitimate style (deferring a heavy import, breaking a cycle), and `asyncio` and
`logging` in that same block are exactly that. Only shadowing is the bug.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tracked_python_sources() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "apps/backend/src/**/*.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [REPO_ROOT / p for p in out]


def _module_level_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _shadowing_imports(tree: ast.Module, module_names: set[str]) -> list[tuple[str, int]]:
    """Only CONDITIONAL shadowing imports — the ones that can leave a name unbound.

    A local import sitting at the top of a function body rebinds the name before
    anything uses it, which is harmless and a legitimate way to defer a heavy
    import or break a cycle; the repo does it in many places. The bug is an
    import nested inside an `if`/`try`/loop: Python still makes the name local
    for the whole function, but the binding only happens when that branch runs.
    Every use outside the branch is then an UnboundLocalError waiting for the
    other path to be taken -- which is exactly how start.py's `os` survived.
    """
    found: list[tuple[str, int]] = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        top_level = {id(stmt) for stmt in func.body}
        for node in ast.walk(func):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if id(node) in top_level:
                continue  # rebinds before any use; not the failure mode
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if bound in module_names:
                    found.append((f"{func.name}(): {bound}", node.lineno))
    return found


def test_no_function_local_import_shadows_a_module_level_one():
    offenders: list[str] = []
    for path in _tracked_python_sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        module_names = _module_level_names(tree)
        for what, lineno in _shadowing_imports(tree, module_names):
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{rel}:{lineno}: {what}")

    assert not offenders, (
        "a function-local import of a name already imported at module scope "
        "makes that name local for the entire function, so every use above it "
        "raises UnboundLocalError. Delete the local import:\n  "
        + "\n  ".join(sorted(offenders))
    )
