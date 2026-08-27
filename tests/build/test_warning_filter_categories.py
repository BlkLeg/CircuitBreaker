"""A warning filter whose category does not match is not a filter.

`make test` died at collection on 2026-08-27 with

    StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is
    deprecated; install `httpx2` instead.

even though apps/backend/pyproject.toml carries an `ignore:` entry for exactly
that message. Two things were wrong at once, and each alone was enough:

* `StarletteDeprecationWarning` subclasses **UserWarning**, not
  DeprecationWarning. The entry ends `:DeprecationWarning`, so the category
  never matched and the filter had been inert since starlette 1.x renamed it.
  A suppression that silently stops applying is worse than none, because the
  comment above it still claims coverage.
* `make test-backend` runs `pytest ../../tests/integration` from apps/backend,
  and pytest takes rootdir from the argument — so the **repo-root pytest.ini**
  governs that run, not apps/backend/pyproject.toml. The backend's filters were
  never in force for it. Root pytest.ini carries a bare `error`, which promotes
  a UserWarning at import time into a collection failure.

These tests check the filters against the classes actually raised, so a
re-parenting upstream fails here rather than in someone's terminal.
"""

from __future__ import annotations

import configparser
import re
import tomllib
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_STARLETTE_MESSAGE = "Using `httpx` with `starlette.testclient` is deprecated"


def _root_filters() -> list[str]:
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "pytest.ini", encoding="utf-8")
    raw = parser.get("pytest", "filterwarnings", fallback="")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _backend_filters() -> list[str]:
    data = tomllib.loads(
        (REPO_ROOT / "apps/backend/pyproject.toml").read_text(encoding="utf-8")
    )
    return data["tool"]["pytest"]["ini_options"]["filterwarnings"]


def _category_of(entry: str) -> str:
    """The category field of an `action:message:category[:module[:line]]` spec."""
    parts = entry.split(":")
    return parts[2] if len(parts) > 2 else ""


def _starlette_entry(filters: list[str]) -> str:
    matches = [f for f in filters if _STARLETTE_MESSAGE in f]
    assert matches, (
        "no filter covers the starlette testclient warning; without one, "
        "`filterwarnings = error` turns importing fastapi.testclient into a "
        "collection failure"
    )
    return matches[0]


def test_root_config_covers_the_starlette_testclient_warning():
    """The root pytest.ini is what governs `make test-backend`'s integration
    run, so the suppression has to exist there — not only in the backend's."""
    _starlette_entry(_root_filters())


def test_every_starlette_suppression_names_a_category_that_actually_matches():
    """The bug: `:DeprecationWarning` on a warning that is a UserWarning."""
    from starlette.exceptions import StarletteDeprecationWarning

    for label, filters in (
        ("pytest.ini", _root_filters()),
        ("apps/backend/pyproject.toml", _backend_filters()),
    ):
        entry = _starlette_entry(filters)
        category = _category_of(entry)
        if not category:
            continue  # bare message match applies to every category
        resolved = getattr(warnings, category, None) or getattr(
            __builtins__, category, None
        )
        if resolved is None:
            resolved = eval(category)  # noqa: S307 - names come from our own config
        assert issubclass(StarletteDeprecationWarning, resolved), (
            f"{label} suppresses the starlette testclient warning under "
            f"{category}, but StarletteDeprecationWarning is a "
            f"{StarletteDeprecationWarning.__mro__[1].__name__}. The filter "
            f"never matches, so the suppression does nothing."
        )


def test_importing_the_test_client_survives_the_root_config():
    """The end-to-end property: the import that broke `make test` must not
    raise under the filters the root config actually installs."""
    filters = _root_filters()
    with warnings.catch_warnings():
        warnings.resetwarnings()
        for entry in filters:
            action, _, rest = entry.partition(":")
            if action == "error" and not rest:
                warnings.simplefilter("error")
                continue
            parts = entry.split(":")
            message = parts[1] if len(parts) > 1 else ""
            category_name = parts[2] if len(parts) > 2 else ""
            category = Warning
            if category_name:
                category = eval(category_name)  # noqa: S307 - our own config
            warnings.filterwarnings(
                action, message=re.escape(message), category=category
            )
        import importlib

        import starlette.testclient

        importlib.reload(starlette.testclient)
