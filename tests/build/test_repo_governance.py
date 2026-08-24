"""GOV-10, GOV-11, GOV-14, GOV-16: the repository's governance surface.

These are file-shape tests, not behaviour tests: GitHub only surfaces a security
policy, issue forms and a PR template from fixed paths, and packaging metadata
only helps if every manifest tells the same story.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SLUG = "BlkLeg/CircuitBreaker"
ISSUE_TEMPLATES = ROOT / ".github" / "ISSUE_TEMPLATE"
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"

MANIFEST_NAMES = {"package.json", "pyproject.toml", "nfpm.yaml", "PKGBUILD"}
# The manifests that existed when this test was written. Discovery must keep
# finding all of them; it may legitimately find more.
EXPECTED_MANIFESTS = {
    "PKGBUILD",
    "apps/backend/pyproject.toml",
    "apps/frontend/package.json",
    "nfpm.yaml",
    "package.json",
}
# GOV-16: "CODEOWNERS for security, migrations, packaging, agent protocol and
# release workflows". One representative tracked path per area.
GOV16_AREAS = {
    "security": ["apps/backend/src/app/security/endpoint_policy.json"],
    "migrations": ["apps/backend/migrations/env.py"],
    "packaging": ["packaging/", "nfpm.yaml", "PKGBUILD"],
    "agent protocol": [
        "apps/agent/internal/frame/frame.go",
        "apps/backend/src/app/schemas/agent_frame.py",
    ],
    "release workflows": [".github/workflows/release.yml"],
}


def _security_text() -> str:
    return (ROOT / "SECURITY.md").read_text(encoding="utf-8")


def _root_manifest() -> dict:
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))


def test_root_security_policy_exists():
    """GOV-11: GitHub only surfaces SECURITY.md from the root, .github/ or docs/."""
    assert (ROOT / "SECURITY.md").exists(), "GOV-11 requires a root SECURITY.md"


def test_security_policy_names_a_real_reporting_channel():
    text = _security_text()
    assert "security/advisories" in text or "@" in text, "no reporting channel named"
    assert "example.com" not in text, "placeholder contact in SECURITY.md"


def test_security_policy_uses_the_real_repository_slug():
    """A wrong-cased slug still 404s once GitHub's redirect chain is bypassed."""
    text = _security_text()
    for url in re.findall(r"https://github\.com/[^\s)\]]+", text):
        assert url.startswith(f"https://github.com/{SLUG}"), f"wrong repo slug: {url}"


def test_security_policy_relative_links_resolve():
    """A dead relative link here turns the repo-wide link check red."""
    text = _security_text()
    for target in re.findall(r"\]\((?!https?:|mailto:|#)([^)#\s]+)", text):
        assert (ROOT / target).exists(), f"SECURITY.md links to missing {target}"


def test_issue_and_pr_templates_are_at_paths_github_recognises():
    assert ISSUE_TEMPLATES.is_dir()
    assert any(ISSUE_TEMPLATES.glob("*.yml"))
    assert (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").exists()


def test_issue_forms_are_valid_yaml_with_the_fields_github_requires():
    yaml = pytest.importorskip("yaml")
    forms = [p for p in ISSUE_TEMPLATES.glob("*.yml") if p.name != "config.yml"]
    assert forms, "no issue form templates"
    for form in forms:
        data = yaml.safe_load(form.read_text(encoding="utf-8"))
        assert data.get("name"), f"{form.name} has no name"
        assert data.get("description"), f"{form.name} has no description"
        assert data.get("body"), f"{form.name} has no body"


def test_issue_template_config_routes_security_reports_privately():
    """GOV-11/GOV-16: a blank issue must not be the path of least resistance."""
    text = (ISSUE_TEMPLATES / "config.yml").read_text(encoding="utf-8")
    assert f"https://github.com/{SLUG}/security/advisories/new" in text
    for url in re.findall(r"https://github\.com/[^\s)\]]+", text):
        assert url.startswith(f"https://github.com/{SLUG}"), f"wrong repo slug: {url}"


def test_backend_has_no_contradictory_poetry_version():
    """GOV-10: VERSION is canonical; a stale [tool.poetry] version contradicts it."""
    data = tomllib.loads((ROOT / "apps" / "backend" / "pyproject.toml").read_text())
    poetry = data.get("tool", {}).get("poetry", {})
    assert "version" not in poetry, "stale [tool.poetry] version contradicts VERSION"
    assert "authors" not in poetry, "placeholder [tool.poetry] authors remain"
    assert "name" not in poetry, "[tool.poetry] name duplicates [project] name"
    assert "description" not in poetry, "[tool.poetry] description duplicates [project]"
    assert poetry.get("package-mode") is False, "poetry lock still needs package-mode = false"


def test_backend_version_still_derives_from_the_version_file():
    data = tomllib.loads((ROOT / "apps" / "backend" / "pyproject.toml").read_text())
    assert data["tool"]["hatch"]["version"]["path"] == "../../VERSION"


def test_root_npm_test_does_not_fail_by_design():
    """GOV-14: a documented root command must not exit 1 on purpose."""
    scripts = _root_manifest()["scripts"]
    assert "exit 1" not in scripts.get("test", ""), "root npm test still fails by design"


def test_root_npm_test_delegates_to_a_script_that_exists():
    """Delegating to a missing script would swap one broken command for another."""
    command = _root_manifest()["scripts"]["test"]
    assert "apps/frontend" in command, "root npm test should run the frontend suite"
    frontend = json.loads(
        (ROOT / "apps" / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    assert "test" in frontend["scripts"], "apps/frontend has no test script to delegate to"


def _tracked_manifests() -> list[Path]:
    """Every packaging manifest git tracks, so a new one cannot slip past unchecked.

    Enumerating from `git ls-files` rather than a hand-written list is the point:
    the previous version of this test only read LICENSE and the root package.json
    and so passed while two of four manifests declared no license at all.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    tracked = [Path(name) for name in out.split("\0") if name]
    return sorted(
        path
        for path in tracked
        if path.name in MANIFEST_NAMES and "node_modules" not in path.parts
    )


def _declared_license(path: Path) -> str | None:
    """The license each manifest format declares, or None if it declares none."""
    text = (ROOT / path).read_text(encoding="utf-8")
    if path.name == "package.json":
        return json.loads(text).get("license")
    if path.name == "pyproject.toml":
        # PEP 639 allows a bare SPDX string; PEP 621 used a {text = ...} table.
        declared = tomllib.loads(text).get("project", {}).get("license")
        if isinstance(declared, dict):
            return declared.get("text")
        return declared
    if path.name == "nfpm.yaml":
        yaml = pytest.importorskip("yaml")
        return yaml.safe_load(text).get("license")
    if path.name == "PKGBUILD":
        # Bash array literal: license=('MIT')
        match = re.search(r"^license=\((.*)\)", text, re.MULTILINE)
        return match.group(1).strip("'\"") if match else None
    raise AssertionError(f"no license reader for {path.name}")


def test_every_tracked_manifest_is_discovered():
    """Guard the guard: if discovery silently returns nothing, the audit below is a no-op."""
    found = {str(path) for path in _tracked_manifests()}
    missing = EXPECTED_MANIFESTS - found
    assert not missing, f"manifest discovery missed known manifests: {sorted(missing)}"


def test_license_metadata_agrees():
    """GOV-11: LICENSE and EVERY packaging manifest must say the same thing."""
    assert "MIT" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    disagreeing = {
        str(path): _declared_license(path)
        for path in _tracked_manifests()
        if _declared_license(path) != "MIT"
    }
    assert not disagreeing, f"manifests do not declare MIT: {disagreeing}"


def _codeowner_rules() -> list[tuple[str, str]]:
    """(pattern, owners) for each rule line in CODEOWNERS."""
    rules = []
    for line in CODEOWNERS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, _, owners = line.partition(" ")
        rules.append((pattern, owners.strip()))
    return rules


def test_codeowners_covers_every_area_gov16_names():
    """GOV-16: security, migrations, packaging, agent protocol and release workflows."""
    patterns = [pattern for pattern, _ in _codeowner_rules()]
    for area, required in GOV16_AREAS.items():
        for path in required:
            assert any(
                pattern == path or (pattern.endswith("/") and path.startswith(pattern))
                for pattern in patterns
            ), f"GOV-16 area {area!r} is not covered by CODEOWNERS: {path}"


def test_every_codeowners_rule_points_at_a_path_that_exists():
    """GitHub silently ignores a rule matching nothing, so it owns nothing."""
    for pattern, owners in _codeowner_rules():
        assert owners.startswith("@"), f"CODEOWNERS rule {pattern!r} names no owner"
        assert (ROOT / pattern.rstrip("/")).exists(), f"CODEOWNERS rule matches nothing: {pattern}"
