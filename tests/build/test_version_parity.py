"""GOV-09: VERSION is the only hand-edited version; everything else derives from it."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts/check_version_parity.py"
_SPEC = importlib.util.spec_from_file_location("check_version_parity", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

collect_versions = _MODULE.collect_versions
check_parity = _MODULE.check_parity


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "VERSION").write_text("1.2.3\n")
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "circuitbreaker", "version": "1.2.3", "private": True})
    )
    frontend = tmp_path / "apps" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package.json").write_text(json.dumps({"name": "frontend", "version": "1.2.3"}))
    return tmp_path


def test_collects_every_known_version_source(tree: Path) -> None:
    assert collect_versions(tree) == {
        "VERSION": "1.2.3",
        "package.json": "1.2.3",
        "apps/frontend/package.json": "1.2.3",
    }


def test_parity_holds_when_all_agree(tree: Path) -> None:
    assert check_parity(tree) == []


def test_detects_frontend_drift(tree: Path) -> None:
    (tree / "apps" / "frontend" / "package.json").write_text(
        json.dumps({"name": "frontend", "version": "1.2.2"})
    )
    problems = check_parity(tree)
    assert len(problems) == 1
    assert "apps/frontend/package.json" in problems[0]
    assert "1.2.2" in problems[0]


def test_detects_tag_drift(tree: Path) -> None:
    problems = check_parity(tree, expected="1.2.4")
    assert any("expected 1.2.4" in p for p in problems)


def test_expected_matching_version_is_clean(tree: Path) -> None:
    assert check_parity(tree, expected="1.2.3") == []


def test_real_repository_has_parity() -> None:
    """The gate must be green on the tree it ships in, or it lands red."""
    assert check_parity(_ROOT) == []
