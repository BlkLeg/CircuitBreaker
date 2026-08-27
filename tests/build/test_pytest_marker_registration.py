# tests/build/test_pytest_marker_registration.py
"""R5: every custom pytest mark must be registered in the config that governs it.

The repo-root pytest.ini carries `filterwarnings = error`, so an unregistered
mark is not a warning — it is a collection failure. On 2026-08-27 that took the
composed agent journey from twelve tests to zero, and it was invisible because
e2e.yml runs against main while the filterwarnings block lives on dev.

Registration is checked rather than the warning being suppressed, per that
file's own rule: fix ours instead.

Marks are found with an AST walk rather than a regex over raw text: pytest
recognises marks written two ways — the decorator form (`@pytest.mark.NAME`,
on a function or a class) and the module-level form (`pytestmark =
pytest.mark.NAME`, or a list of them). A regex over source text sees neither
distinction reliably: it is blind to the module-level form entirely, and it
can "find" a mark name that only appears in a comment or a docstring. The AST
sees code, not prose, and tells the two idioms apart cleanly.
"""

from __future__ import annotations

import ast
import configparser
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Marks provided by pytest itself or by a plugin the suites depend on.
_BUILTIN = {
    "parametrize", "skip", "skipif", "xfail", "usefixtures", "filterwarnings",
    "timeout",  # pytest-timeout
    "asyncio",  # pytest-asyncio
}


def _tracked_python_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [REPO_ROOT / p for p in out]


def _registered_in_root_ini() -> set[str]:
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "pytest.ini", encoding="utf-8")
    raw = parser.get("pytest", "markers", fallback="")
    return {line.split(":")[0].strip() for line in raw.splitlines() if line.strip()}


def _registered_in_backend() -> set[str]:
    data = tomllib.loads(
        (REPO_ROOT / "apps/backend/pyproject.toml").read_text(encoding="utf-8")
    )
    entries = data["tool"]["pytest"]["ini_options"].get("markers", [])
    return {entry.split(":")[0].strip() for entry in entries}


def _mark_name(node: ast.expr) -> str | None:
    """Return NAME if `node` is `pytest.mark.NAME` or `pytest.mark.NAME(...)`."""
    if isinstance(node, ast.Call):
        node = node.func
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    ):
        return node.attr
    return None


def _marks_in_source(source: str) -> set[str]:
    """Every `pytest.mark.NAME` this module applies, decorator or module-level."""
    tree = ast.parse(source)
    found: set[str] = set()

    # Decorator form: @pytest.mark.NAME / @pytest.mark.NAME(...), on functions,
    # async functions and classes, at any nesting depth.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                mark = _mark_name(decorator)
                if mark is not None:
                    found.add(mark)

    # Module-level form: pytestmark = pytest.mark.NAME(...), or a list of them.
    # Only pytest.mark.* actually takes effect here, so only module-level
    # assignments to `pytestmark` are considered.
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets):
            continue
        candidates = stmt.value.elts if isinstance(stmt.value, ast.List) else [stmt.value]
        for candidate in candidates:
            mark = _mark_name(candidate)
            if mark is not None:
                found.add(mark)

    return found


def test_every_custom_mark_is_registered_by_its_governing_config():
    root_registered = _registered_in_root_ini()
    backend_registered = _registered_in_backend()

    unregistered: list[str] = []
    unparseable: list[str] = []
    for path in _tracked_python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        # apps/backend runs from its own directory under its own config; every
        # other suite is collected under the repo-root pytest.ini.
        governing = (
            backend_registered
            if rel.startswith("apps/backend/")
            else root_registered
        )
        try:
            marks = _marks_in_source(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            # A file the scan cannot parse is a file it silently stops
            # covering — the same class of bug this test exists to catch, so
            # it is surfaced as a failure rather than skipped quietly.
            unparseable.append(f"{rel}: {exc}")
            continue
        for mark in marks:
            if mark in _BUILTIN or mark in governing:
                continue
            unregistered.append(f"{rel}: pytest.mark.{mark}")

    assert not unparseable, (
        "could not parse these tracked Python files, so the marker scan did not "
        "cover them:\n  " + "\n  ".join(sorted(unparseable))
    )
    assert not unregistered, (
        "unregistered pytest marks — `filterwarnings = error` turns these into "
        "collection failures:\n  " + "\n  ".join(sorted(set(unregistered)))
    )


def test_e2e_mark_means_the_same_thing_in_both_configs():
    """One mark, one meaning, whichever config is in force."""
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "pytest.ini", encoding="utf-8")
    root_raw = parser.get("pytest", "markers")
    root_e2e = next(l.strip() for l in root_raw.splitlines() if l.strip().startswith("e2e:"))

    data = tomllib.loads(
        (REPO_ROOT / "apps/backend/pyproject.toml").read_text(encoding="utf-8")
    )
    backend_e2e = next(
        e for e in data["tool"]["pytest"]["ini_options"]["markers"]
        if e.startswith("e2e:")
    )
    assert root_e2e == backend_e2e, (
        f"root pytest.ini says {root_e2e!r}, backend says {backend_e2e!r}"
    )


def test_scanner_finds_module_level_pytestmark():
    """pytestmark = pytest.mark.security is the form the regex-based scanner
    used to miss entirely. apps/backend/tests/test_worker_audit.py's only mark
    comes from this form — its scan must find it."""
    source = (
        REPO_ROOT / "apps/backend/tests/test_worker_audit.py"
    ).read_text(encoding="utf-8")
    assert "security" in _marks_in_source(source)


def test_scanner_ignores_marks_named_only_in_comments_or_docstrings():
    source = '''
"""This module's tests are all @pytest.mark.security, mentioned here only in
prose — not a real mark. See also pytestmark = pytest.mark.slow, likewise
prose."""

# pytest.mark.notreal is also just a comment.


def test_something():
    assert True
'''
    assert _marks_in_source(source) == set()


def test_scanner_finds_pytestmark_list_form_and_decorator_form_together():
    source = """
import pytest

pytestmark = [pytest.mark.security, pytest.mark.slow(reason="why not")]


@pytest.mark.e2e
class TestThing:
    @pytest.mark.asyncio
    async def test_one(self):
        assert True
"""
    assert _marks_in_source(source) == {"security", "slow", "e2e", "asyncio"}
