"""GOV-12: a tracked-file policy test that prevents recurrence.

Removing the junk once is not the requirement — the requirement is that it
cannot come back. Each rule below corresponds to something that was actually
found tracked in this repository, not a hypothetical.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def tracked_files() -> list[str]:
    """Every path in the git index, repo-root-relative."""
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()


def test_no_shell_quoting_accidents_are_tracked():
    """Files literally named for a curl/shell flag: -H, -d, =1.9.0."""
    offenders = [
        f for f in tracked_files() if re.fullmatch(r"-{1,2}[A-Za-z]|=.+", Path(f).name)
    ]
    assert not offenders, f"shell-quoting accidents tracked: {offenders}"


def test_generated_site_output_is_not_tracked():
    """GOV-08: docs/ is canonical; site/ is MkDocs build output."""
    offenders = [f for f in tracked_files() if f.startswith("site/")]
    assert not offenders, f"{len(offenders)} generated site/ files tracked"


def test_no_user_uploads_are_tracked():
    """Profile images are user data, not source."""
    offenders = [f for f in tracked_files() if "data/uploads/" in f]
    assert not offenders, f"user uploads tracked: {offenders[:5]}"


def test_no_env_files_are_tracked():
    """Even documented test-only credentials belong in a template, not a .env."""
    offenders = [f for f in tracked_files() if Path(f).name == ".env"]
    assert not offenders, f".env files tracked: {offenders}"


def test_agent_e2e_env_template_is_tracked():
    """The harness still needs its variable names documented somewhere.

    Untracking `apps/agent/e2e/.env` only counts as hygiene if the template
    that replaced it survives — otherwise the next person cannot run the
    suite at all (the base compose file's ``${VAR:?...}`` guards fail).
    """
    assert "apps/agent/e2e/.env.example" in tracked_files()


def test_no_ide_or_tool_output_is_tracked():
    patterns = (".idea/", "eslint_output.json", ".DS_Store")
    offenders = [f for f in tracked_files() if any(p in f for p in patterns)]
    assert not offenders, f"IDE/tool output tracked: {offenders}"


def test_root_npm_manifest_stays_private():
    """NPM-02: the repository root must never be publishable."""
    manifest = json.loads((ROOT / "package.json").read_text())
    assert manifest.get("private") is True, "root package.json must remain private"
