# tests/build/test_pytest_marker_registration.py
"""R5: every custom pytest mark must be registered in the config that governs it.

The repo-root pytest.ini carries `filterwarnings = error`, so an unregistered
mark is not a warning — it is a collection failure. On 2026-08-27 that took the
composed agent journey from twelve tests to zero, and it was invisible because
e2e.yml runs against main while the filterwarnings block lives on dev.

Registration is checked rather than the warning being suppressed, per that
file's own rule: fix ours instead.
"""

from __future__ import annotations

import configparser
import re
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

_MARK_RE = re.compile(r"@pytest\.mark\.([a-zA-Z_][a-zA-Z0-9_]*)")


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


def test_every_custom_mark_is_registered_by_its_governing_config():
    root_registered = _registered_in_root_ini()
    backend_registered = _registered_in_backend()

    unregistered: list[str] = []
    for path in _tracked_python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        # apps/backend runs from its own directory under its own config; every
        # other suite is collected under the repo-root pytest.ini.
        governing = (
            backend_registered
            if rel.startswith("apps/backend/")
            else root_registered
        )
        for mark in _MARK_RE.findall(path.read_text(encoding="utf-8")):
            if mark in _BUILTIN or mark in governing:
                continue
            unregistered.append(f"{rel}: @pytest.mark.{mark}")

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
