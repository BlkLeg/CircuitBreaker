"""Tier 2's suites have exactly one definition each, and every caller uses it.

Design D1 keeps the three suites in separate reusable workflows, and in exchange
P1 is enforced here: the workflow step and the `make` target both call the same
scripts/ci script, and neither may re-inline the command. The failure this
prevents is a laptop run and a CI run that differ in the flags they pass. Nobody
sees that until one of them goes red and the other does not.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MAKEFILE = REPO_ROOT / "Makefile"
BROWSER_SCRIPT = "scripts/ci/tier2-browser.sh"
AGENT_SCRIPT = "scripts/ci/tier2-agent-journey.sh"


def _load(name: str) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _run_blocks(workflow: dict) -> list[str]:
    blocks: list[str] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            if isinstance(step, dict) and "run" in step:
                blocks.append(str(step["run"]))
    return blocks


def _recipe(target: str) -> str:
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n|#[^\n]*\n|\n)*)", text, re.M)
    assert match, f"no {target} target in the Makefile"
    return match.group(1)


def test_browser_workflow_calls_the_script_and_inlines_nothing():
    runs = _run_blocks(_load("browser-e2e.yml"))
    assert any(BROWSER_SCRIPT in r for r in runs), f"browser-e2e.yml never calls {BROWSER_SCRIPT}"
    inlined = [r for r in runs if "playwright test" in r]
    assert not inlined, f"browser-e2e.yml re-inlines the suite; call {BROWSER_SCRIPT}: {inlined}"


def test_composed_workflow_calls_the_script_and_inlines_nothing():
    runs = _run_blocks(_load("composed-e2e.yml"))
    assert any(AGENT_SCRIPT in r for r in runs), f"composed-e2e.yml never calls {AGENT_SCRIPT}"
    inlined = [r for r in runs if "test_agent_e2e.py" in r]
    assert not inlined, f"composed-e2e.yml re-inlines the journey; call {AGENT_SCRIPT}: {inlined}"


def test_e2e_local_calls_the_script_and_inlines_nothing():
    recipe = _recipe("e2e-local")
    assert AGENT_SCRIPT in recipe
    assert "test_agent_e2e.py" not in recipe, "e2e-local re-inlines the pytest command"


def test_agent_script_seed_matches_the_workflow():
    """The script defaults CB_E2E_SEED for the laptop; composed-e2e.yml pins it for
    CI (test_ci_evidence_retention.py requires that). The two must be one value."""
    script = (REPO_ROOT / AGENT_SCRIPT).read_text(encoding="utf-8")
    match = re.search(r'CB_E2E_SEED="\$\{CB_E2E_SEED:-(\d+)\}"', script)
    assert match, f"{AGENT_SCRIPT} no longer defaults CB_E2E_SEED"
    step = next(
        s for s in _load("composed-e2e.yml")["jobs"]["composed-journey"]["steps"]
        if AGENT_SCRIPT in str(s.get("run", ""))
    )
    assert str(step["env"]["CB_E2E_SEED"]) == match.group(1)


@pytest.mark.parametrize("shard", ["1/2; rm -rf /", "1", "a/b", "1/2 3/4"])
def test_browser_script_rejects_a_malformed_shard_before_doing_anything(shard):
    result = subprocess.run(
        ["bash", str(REPO_ROOT / BROWSER_SCRIPT), *shard.split(" ")],
        capture_output=True, text=True, cwd=REPO_ROOT, env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 2, result.stderr
    assert "shard" in result.stderr.lower()


def test_browser_script_forces_the_ci_reporter():
    """playwright.config.ts writes junit.xml only when process.env.CI is set."""
    assert 'export CI="${CI:-1}"' in (REPO_ROOT / BROWSER_SCRIPT).read_text(encoding="utf-8")
