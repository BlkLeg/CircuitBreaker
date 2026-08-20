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
check_doc_versions = _MODULE.check_doc_versions


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


@pytest.fixture
def doc_tree(tmp_path: Path) -> Path:
    """A tree carrying every prose reference the registry knows about."""
    (tmp_path / "VERSION").write_text("1.2.3\n")
    (tmp_path / "README.md").write_text(
        "> **Release Candidate Security Notice**\n> 1.2.3. Not fully audited; run on a LAN.\n"
    )
    reports = tmp_path / "SECURITY_REPORTS"
    reports.mkdir()
    (reports / "README.md").write_text(
        "None of them has been re-run against 1.2.3. A finding is closed only if\n"
        "the ledger says so.\n\n"
        "- **Historical** - accurate for its date, not re-verified against 1.2.3.\n"
    )
    manifest = tmp_path / "docs" / "assets" / "screenshots"
    manifest.mkdir(parents=True)
    (manifest / "MANIFEST.md").write_text("Verifying it requires\nrendering the 1.2.3 UI and so on.\n")
    return tmp_path


def test_doc_versions_agree_when_prose_is_current(doc_tree: Path) -> None:
    assert check_doc_versions(doc_tree) == []


def test_detects_stale_release_prose(doc_tree: Path) -> None:
    """The exact drift 0c8c9f3f shipped: VERSION moves, the prose does not."""
    (doc_tree / "VERSION").write_text("1.2.4\n")
    problems = check_doc_versions(doc_tree)
    assert len(problems) == 4
    assert all("1.2.3" in p and "1.2.4" in p for p in problems)


def test_rewording_a_doc_fails_loudly_rather_than_silently_skipping(doc_tree: Path) -> None:
    """A registry that quietly matches nothing is the same as no registry."""
    (doc_tree / "README.md").write_text("> 1.2.3. Audited to a fare-thee-well.\n")
    problems = check_doc_versions(doc_tree)
    assert len(problems) == 1
    assert "README.md" in problems[0]
    assert "no longer matches" in problems[0]


def test_deleting_a_registered_doc_is_reported(doc_tree: Path) -> None:
    (doc_tree / "docs/assets/screenshots/MANIFEST.md").unlink()
    problems = check_doc_versions(doc_tree)
    assert len(problems) == 1
    assert "MANIFEST.md" in problems[0]
    assert "missing" in problems[0]


def test_doc_versions_honour_an_expected_override(doc_tree: Path) -> None:
    """release.yml passes the pushed tag; the prose has to match it too."""
    assert check_doc_versions(doc_tree, expected="1.2.3") == []
    assert len(check_doc_versions(doc_tree, expected="9.9.9")) == 4


def test_real_repository_prose_names_the_shipping_release() -> None:
    assert check_doc_versions(_ROOT) == []
