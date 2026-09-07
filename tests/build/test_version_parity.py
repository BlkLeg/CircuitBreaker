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
sync_versions = _MODULE.sync_versions


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


# --- sync mode -------------------------------------------------------------
#
# The registry above already knows every place a version lives and how to find
# it in each. Checking against that registry and *writing* to it are the same
# problem, so they share it — a second list of locations maintained by hand is
# the drift this gate exists to catch, one level up.


def test_sync_rewrites_every_manifest_and_doc(tree: Path, doc_tree: Path) -> None:
    """One canonical edit to VERSION, and everything else follows."""
    for src in doc_tree.rglob("*"):
        if src.is_file() and src.name != "VERSION":
            dest = tree / src.relative_to(doc_tree)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src.read_text())
    (tree / "VERSION").write_text("1.2.4\n")

    changed = sync_versions(tree)

    assert check_parity(tree) == []
    assert check_doc_versions(tree) == []
    # Two manifests plus four prose references.
    assert len(changed) == 6
    assert all("1.2.4" in line for line in changed)


def test_sync_is_idempotent(tree: Path) -> None:
    (tree / "VERSION").write_text("1.2.4\n")
    assert sync_versions(tree) != []
    assert sync_versions(tree) == []


def test_sync_preserves_the_rest_of_a_manifest(tree: Path) -> None:
    """A package.json is hand-maintained; rewriting it wholesale would reflow it."""
    manifest = tree / "package.json"
    manifest.write_text(
        '{\n  "name": "circuitbreaker",\n  "version": "1.2.3",\n'
        '  "private": true,\n  "dependencies": {"left-pad": "1.2.3"}\n}\n'
    )
    (tree / "VERSION").write_text("1.2.4\n")

    sync_versions(tree)

    text = manifest.read_text()
    assert '"version": "1.2.4"' in text
    # A dependency that happens to pin the same string is not this project's
    # version and must be left exactly where it is.
    assert '"left-pad": "1.2.3"' in text
    assert text.endswith("}\n")


def test_sync_leaves_a_reworded_doc_for_a_human(doc_tree: Path) -> None:
    """Sync fixes what is mechanical. A changed sentence is not."""
    (doc_tree / "README.md").write_text("> 1.2.3. Audited to a fare-thee-well.\n")
    (doc_tree / "VERSION").write_text("1.2.4\n")

    sync_versions(doc_tree)

    problems = check_doc_versions(doc_tree)
    assert len(problems) == 1
    assert "no longer matches" in problems[0]


def test_sync_honours_an_expected_override(tree: Path) -> None:
    """The release workflow's tag wins, exactly as it does for the check."""
    sync_versions(tree, expected="9.9.9")
    assert collect_versions(tree)["package.json"] == "9.9.9"
    assert (tree / "VERSION").read_text().strip() == "9.9.9"


# --- lockfiles -------------------------------------------------------------
#
# A package-lock.json carries the project's own version twice, and neither
# copy was registered. The root lockfile had drifted two releases behind
# package.json before anything looked at it, which is the exact failure GOV-09
# describes: a hand-edited version that is not VERSION.


@pytest.fixture
def lock_tree(tree: Path) -> Path:
    """`tree` plus the two lockfiles, in the shape npm writes them."""
    (tree / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "circuitbreaker",
                "version": "1.2.3",
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "circuitbreaker", "version": "1.2.3"},
                    # A dependency that happens to pin the same string. It is
                    # not this project's version and must never be touched.
                    "node_modules/left-pad": {"version": "1.2.3"},
                },
            },
            indent=2,
        )
        + "\n"
    )
    frontend_lock = tree / "apps" / "frontend" / "package-lock.json"
    frontend_lock.write_text(
        json.dumps(
            {
                "name": "frontend",
                "version": "1.2.3",
                "lockfileVersion": 3,
                "packages": {"": {"name": "frontend", "version": "1.2.3"}},
            },
            indent=2,
        )
        + "\n"
    )
    return tree


def test_lockfiles_are_collected(lock_tree: Path) -> None:
    versions = collect_versions(lock_tree)
    assert versions["package-lock.json"] == "1.2.3"
    assert versions["apps/frontend/package-lock.json"] == "1.2.3"


def test_detects_lockfile_drift(lock_tree: Path) -> None:
    """The drift that shipped: package.json bumped, its lockfile left behind."""
    lock = lock_tree / "package-lock.json"
    lock.write_text(lock.read_text().replace('"version": "1.2.3"', '"version": "1.0.0"', 1))
    problems = check_parity(lock_tree)
    assert len(problems) == 1
    assert "package-lock.json" in problems[0]


def test_sync_rewrites_both_lockfile_copies_and_nothing_else(lock_tree: Path) -> None:
    (lock_tree / "VERSION").write_text("1.2.4\n")

    sync_versions(lock_tree)

    assert check_parity(lock_tree) == []
    lock = json.loads((lock_tree / "package-lock.json").read_text())
    assert lock["version"] == "1.2.4"
    assert lock["packages"][""]["version"] == "1.2.4"
    assert lock["packages"]["node_modules/left-pad"]["version"] == "1.2.3"


def test_sync_keeps_a_lockfile_in_npms_own_formatting(lock_tree: Path) -> None:
    """npm writes JSON.stringify(obj, null, 2) + newline. Match it, or every
    sync produces a 600 KB diff nobody can review."""
    lock = lock_tree / "apps" / "frontend" / "package-lock.json"
    before = lock.read_text()
    (lock_tree / "VERSION").write_text("1.2.4\n")

    sync_versions(lock_tree)

    after = lock.read_text()
    assert after == before.replace("1.2.3", "1.2.4")
