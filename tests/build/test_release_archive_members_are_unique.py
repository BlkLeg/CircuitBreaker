"""The release tarball carries each path once, and no build-host bytecode.

`create_archive` walked `bundle_dir.rglob("*")` and handed every result to
`tarfile.add()`. That call recurses into a directory by default, so each
directory was written once as its whole subtree and then again, entry by entry,
as the loop reached its children; nested directories compounded it. The v0.4.3
bundle shipped **4012 members for 864 distinct paths** and weighed 189 MiB
against a true 123 MiB — every duplicate a second compressed copy of the same
bytes, sent down the wire of every `curl | bash` install.

It extracted correctly only by luck: tar writes members in order, so the later
copy overwrote the earlier one. Two copies of a path in one archive is a
correctness problem waiting for the two to differ, not only a size problem.

The bytecode half is the same defect in a different coat: `share/backend/
migrations/versions/__pycache__` put 131 `.pyc` files compiled by whatever
interpreter ran the build into the artifact. They are stale on any host with a
different Python, and nothing reads them — Alembic imports the `.py` sources.

This builds a miniature bundle with the nesting that triggered it and asserts on
the archive itself rather than on the shape of the source, so a future rewrite of
the loop is held to the outcome rather than to today's spelling of it.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import tarfile
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_native_release.py"


def _load_build_module():
    """Import build_native_release.py by path — scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location("cb_build_native_release", BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_module():
    return _load_build_module()


def _make_bundle(root: Path) -> None:
    """A bundle with the nesting depth that made the duplication compound."""
    (root / "share" / "backend" / "migrations" / "versions").mkdir(parents=True)
    (root / "deploy" / "systemd").mkdir(parents=True)
    (root / "circuit-breaker").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "share" / "VERSION").write_text("0.0.0\n", encoding="utf-8")
    (root / "share" / "backend" / "migrations" / "env.py").write_text("x = 1\n", encoding="utf-8")
    (root / "share" / "backend" / "migrations" / "versions" / "0001_init.py").write_text(
        "y = 2\n", encoding="utf-8"
    )
    (root / "deploy" / "setup.sh").write_text("echo hi\n", encoding="utf-8")
    (root / "deploy" / "systemd" / "app.service").write_text("[Unit]\n", encoding="utf-8")


def test_archive_lists_every_path_exactly_once(build_module, tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _make_bundle(bundle)

    archive_path = build_module.create_archive(
        bundle, "0.0.0", "linux", "amd64", tmp_path / "out"
    )

    with tarfile.open(archive_path) as archive:
        names = archive.getnames()

    duplicates = {name: count for name, count in Counter(names).items() if count > 1}
    assert not duplicates, (
        "the release tarball lists these paths more than once — "
        f"tarfile.add() needs recursive=False: {sorted(duplicates)}"
    )


def test_archive_still_carries_every_file(build_module, tmp_path):
    """recursive=False must not be achieved by dropping entries."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _make_bundle(bundle)

    archive_path = build_module.create_archive(
        bundle, "0.0.0", "linux", "amd64", tmp_path / "out"
    )

    expected = {
        str(path.relative_to(bundle)) for path in bundle.rglob("*") if path.is_file()
    }
    with tarfile.open(archive_path) as archive:
        shipped = {member.name for member in archive.getmembers() if member.isfile()}

    assert shipped == expected, "the archive lost or gained files relative to the bundle"


def test_the_bytecode_filter_drops_caches_and_keeps_sources(build_module):
    ignored = build_module._NO_BYTECODE("irrelevant", ["__pycache__", "a.pyc", "keep.py"])
    assert "__pycache__" in ignored and "a.pyc" in ignored
    assert "keep.py" not in ignored


def test_every_copytree_reading_repo_python_filters_bytecode():
    """The two stagers that read .py trees out of the repo pass the filter.

    Only these two copy Python sources straight from the working tree; the other
    copytree calls read build output (PyInstaller's dist, the frontend bundle,
    the agent binaries) or a bundle directory this function already filtered, so
    demanding the filter of all of them would be noise. Named individually
    rather than counted, so adding an unrelated copytree does not fail the build
    and adding a third *source* stager is a deliberate edit to this list.
    """
    tree = ast.parse(BUILD_SCRIPT.read_text(encoding="utf-8"))
    # Keyed by the source text of the call's first argument, which is what
    # names the tree being staged.
    wanted = {
        "BACKEND_ROOT / 'migrations'": "share/backend/migrations",
        "src": "deploy/",
    }

    seen: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "copytree"
            and node.args
        ):
            continue
        first_arg = ast.unparse(node.args[0])
        if first_arg not in wanted:
            continue
        seen[first_arg] = any(
            keyword.arg == "ignore" and ast.unparse(keyword.value) == "_NO_BYTECODE"
            for keyword in node.keywords
        )

    missing_stagers = sorted(set(wanted) - set(seen))
    assert not missing_stagers, (
        f"these copytree stagers were not found — update this test: {missing_stagers}"
    )
    unfiltered = sorted(wanted[arg] for arg, filtered in seen.items() if not filtered)
    assert not unfiltered, (
        "these stagers copy repo Python without ignore=_NO_BYTECODE, so the "
        f"build host's .pyc files would ship in the release tarball: {unfiltered}"
    )
