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

START_PY = BACKEND_SRC / "app" / "start.py"


def _uvicorn_target_literal() -> str:
    """The ASGI target string literally handed to uvicorn.run in start.py."""
    tree = ast.parse(START_PY.read_text(encoding="utf-8"), filename=str(START_PY))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "uvicorn"
            and func.attr == "run"
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            return node.args[0].value
    raise AssertionError(
        "No `uvicorn.run(\"<module>:<attr>\", ...)` call with a string literal "
        "was found in start.py. scripts/build_native_release.py's "
        "_collect_asgi_target_hidden_imports requires that literal and raises "
        "SystemExit without it, so the build is already broken if this fires."
    )


def test_asgi_target_constant_matches_what_uvicorn_is_given() -> None:
    from app.start import ASGI_TARGET

    literal = _uvicorn_target_literal()
    assert ASGI_TARGET == literal, (
        f"ASGI_TARGET is {ASGI_TARGET!r} but uvicorn.run is given {literal!r}. "
        "--selftest would verify a different application from the one the "
        "binary serves, which is a gate passing for the wrong reason — exactly "
        "the v0.4.2 shape."
    )


def test_asgi_target_is_in_uvicorn_import_string_form() -> None:
    from app.start import ASGI_TARGET

    module, separator, attribute = ASGI_TARGET.partition(":")
    assert separator and module and attribute, (
        f"ASGI_TARGET {ASGI_TARGET!r} is not in uvicorn's required "
        '"<module>:<attribute>" form.'
    )


BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_native_release.py"


def _dynamic_import_packages() -> set[str]:
    """The `_DYNAMIC_IMPORT_PACKAGES` tuple the build script hides-imports.

    Read from the AST, matching the rest of this module's approach, so this
    suite stays runnable without PyInstaller installed.
    """
    tree = ast.parse(BUILD_SCRIPT.read_text(encoding="utf-8"), filename=str(BUILD_SCRIPT))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_DYNAMIC_IMPORT_PACKAGES" for t in node.targets)
            and isinstance(node.value, ast.Tuple)
        ):
            return {
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
    raise AssertionError(
        "No `_DYNAMIC_IMPORT_PACKAGES = (...)` tuple literal was found in "
        f"{BUILD_SCRIPT.name}. Either it was renamed or this parser is broken."
    )


def test_selftest_probes_every_dynamic_import_package() -> None:
    """--selftest must prove the packaging fix for #104's whole class, not just proxmoxer.

    `_DYNAMIC_IMPORT_PACKAGES` in the build script is what PyInstaller's static
    import graph would otherwise silently drop (gh#104: `proxmoxer.backends`).
    `collect_submodules` at build time puts the files in the bundle; nothing
    proved they are actually importable until `--selftest` probes one submodule
    per package. A package added to the build list with no matching probe here
    is the same "declared, never verified" gap #104 already was.
    """
    from app.startup.selftest import DYNAMIC_IMPORT_PROBES

    packages = _dynamic_import_packages()
    probed = set(DYNAMIC_IMPORT_PROBES)
    missing = packages - probed
    extra = probed - packages
    assert not missing, (
        f"{sorted(missing)} are hidden-imported by the build but --selftest never "
        "probes them. Add a representative submodule to DYNAMIC_IMPORT_PROBES."
    )
    assert not extra, (
        f"DYNAMIC_IMPORT_PROBES names {sorted(extra)}, which the build script does "
        "not hidden-import. Remove the stale probe, or add the package to "
        "_DYNAMIC_IMPORT_PACKAGES."
    )
    for package, probe in DYNAMIC_IMPORT_PROBES.items():
        assert probe.startswith(f"{package}."), (
            f"DYNAMIC_IMPORT_PROBES[{package!r}] = {probe!r} does not name a "
            f"submodule of {package!r}."
        )
