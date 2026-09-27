"""Tier 2's suites have exactly one definition each, and every caller uses it.

Design D1 keeps the three suites in separate reusable workflows, and in exchange
P1 is enforced here: the workflow step and the `make` target both call the same
scripts/ci script, and neither may re-inline the command. The failure this
prevents is a laptop run and a CI run that differ in the flags they pass. Nobody
sees that until one of them goes red and the other does not.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MAKEFILE = REPO_ROOT / "Makefile"
BROWSER_SCRIPT = "scripts/ci/tier2-browser.sh"
AGENT_SCRIPT = "scripts/ci/tier2-agent-journey.sh"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))
from tier2_gate import KNOWN_SUITES  # noqa: E402

_GATED = re.compile(r"contains\(fromJSON\(needs\.plan\.outputs\.suites\),\s*'([a-z0-9-]+)'\)")


def _triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True)) or {}


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


def test_the_html_reporter_cannot_clear_the_junit_report():
    """playwright.config.ts: the HTML reporter empties its outputFolder when it
    writes. When it shared playwright-report/ with junit.xml, every CI run lost
    its JUnit report, silently. Tier 2 triage reads that file."""
    config = (REPO_ROOT / "apps" / "frontend" / "playwright.config.ts").read_text(encoding="utf-8")
    junit = re.search(r"\['junit',\s*\{\s*outputFile:\s*'([^']+)'", config)
    html = re.search(r"\['html',\s*\{[^}]*outputFolder:\s*'([^']+)'", config)
    assert junit, "no junit reporter with an outputFile in playwright.config.ts"
    assert html, "the html reporter must name its own outputFolder"
    junit_path = Path(junit.group(1))
    html_folder = Path(html.group(1))
    assert html_folder not in junit_path.parents and html_folder != junit_path.parent, (
        f"html outputFolder {html_folder} would clear {junit_path}"
    )


def test_verify_composed_runs_both_suites_and_is_documented():
    text = MAKEFILE.read_text(encoding="utf-8")
    line = re.search(r"^verify-composed:([^\n]*)$", text, re.M)
    assert line, "no verify-composed target"
    deps, _, help_text = line.group(1).partition("##")
    assert set(deps.split()) == {"verify-composed-browser", "verify-composed-agent"}
    assert "Tier 2" in help_text, "verify-composed must say what it is in `make help`"


def test_verify_composed_browser_calls_the_script():
    assert BROWSER_SCRIPT in _recipe("verify-composed-browser")


def test_verify_composed_agent_honours_the_register_or_runs_the_real_suite():
    recipe = _recipe("verify-composed-agent")
    assert "quarantine_notice.py" in recipe
    assert '"Composed Agent E2E / composed-journey"' in recipe
    assert "$(MAKE) e2e-local" in recipe


def test_local_quarantine_default_matches_the_workflow():
    """composed-e2e.yml defaults `quarantined` to true, so a laptop must default to
    the same. Otherwise `make verify-composed` starts a 75-minute suite that is
    known red, or skips one that CI runs."""
    workflow = _load("composed-e2e.yml")
    triggers = workflow.get("on", workflow.get(True))
    ci_default = bool(triggers["workflow_call"]["inputs"]["quarantined"]["default"])
    match = re.search(r"^CB_COMPOSED_QUARANTINED\s*\?=\s*(\d)\s*$", MAKEFILE.read_text(encoding="utf-8"), re.M)
    assert match, "Makefile has no `CB_COMPOSED_QUARANTINED ?= 0|1`"
    assert (match.group(1) == "1") == ci_default


def test_tier2_is_named_and_triggered_as_the_design_says():
    workflow = _load("tier2.yml")
    assert workflow["name"] == "Tier 2 (composed)"
    triggers = _triggers(workflow)
    assert set(triggers) >= {"pull_request", "schedule", "workflow_dispatch", "workflow_call"}
    assert triggers["schedule"] == [{"cron": "0 3 * * *"}]


def test_every_suite_job_is_gated_on_its_own_name_and_the_sets_agree():
    jobs = _load("tier2.yml")["jobs"]
    gated = {}
    for job_id, job in jobs.items():
        match = _GATED.search(str(job.get("if", "")))
        if match:
            gated[job_id] = match.group(1)
    assert all(job_id == suite for job_id, suite in gated.items()), gated
    assert set(gated.values()) == set(KNOWN_SUITES), (
        f"tier2.yml gates {sorted(gated.values())} but tier2_gate.py knows {sorted(KNOWN_SUITES)}"
    )


def test_result_job_needs_the_plan_and_every_suite_and_always_runs():
    result = _load("tier2.yml")["jobs"]["result"]
    assert set(result["needs"]) == {"plan", *KNOWN_SUITES}
    assert "always()" in str(result["if"])


def test_tier2_passes_the_planned_ref_to_every_suite():
    jobs = _load("tier2.yml")["jobs"]
    for suite in KNOWN_SUITES:
        assert jobs[suite]["with"]["ref"] == "${{ needs.plan.outputs.ref }}", suite


def test_tier2_runs_serially_without_cancelling():
    concurrency = _load("tier2.yml")["concurrency"]
    assert concurrency["cancel-in-progress"] is False


def test_the_nightly_has_exactly_one_home():
    """One cron cannot live in two files: both would run the composed suite."""
    assert "schedule" not in _triggers(_load("e2e.yml"))


def test_the_composed_journey_is_still_scheduled():
    """AGT-01: the composed journey runs on a schedule. Moving the cron must not drop it."""
    tier2 = _load("tier2.yml")
    assert "schedule" in _triggers(tier2)
    assert tier2["jobs"]["composed"]["uses"] == "./.github/workflows/composed-e2e.yml"


def test_browser_e2e_checks_out_the_ref_it_was_given():
    workflow = _load("browser-e2e.yml")
    assert _triggers(workflow)["workflow_call"]["inputs"]["ref"]["default"] == ""
    checkouts = [
        s for s in workflow["jobs"]["browser-e2e"]["steps"]
        if str(s.get("uses", "")).startswith("actions/checkout")
    ]
    assert checkouts and all(s["with"]["ref"] == "${{ inputs.ref }}" for s in checkouts)


def test_notify_watches_tier2():
    watched = _triggers(_load("notify.yml"))["workflow_run"]["workflows"]
    assert "Tier 2 (composed)" in watched


def test_tier2_runs_before_a_tag_when_it_changes():
    """release.yml depends on tier2.yml, so its own graph must run pre-tag
    (test_release_paths_run_before_the_tag.py). A path filter keeps that to the
    pull requests that change it."""
    paths = set(_triggers(_load("tier2.yml"))["pull_request"]["paths"])
    assert paths == {".github/workflows/tier2.yml", "scripts/ci/tier2_gate.py"}


def _tier2_callers() -> dict[str, dict]:
    callers = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job_id, job in (_load(path.name).get("jobs") or {}).items():
            if str((job or {}).get("uses", "")) == "./.github/workflows/tier2.yml":
                callers[f"{path.name}:{job_id}"] = job
    return callers


def test_the_release_path_calls_tier2_and_not_browser_e2e_directly():
    for name in ("release.yml", "release-dry-run.yml"):
        jobs = _load(name)["jobs"]
        assert jobs["tier2"]["uses"] == "./.github/workflows/tier2.yml", name
        direct = [j for j, job in jobs.items() if str(job.get("uses", "")).endswith("browser-e2e.yml")]
        assert not direct, f"{name} still calls browser-e2e.yml directly from {direct}"


def test_every_tier2_caller_passes_real_suites():
    callers = _tier2_callers()
    assert callers, "nothing calls tier2.yml"
    for where, job in callers.items():
        raw = (job.get("with") or {}).get("suites", "")
        if raw == "":
            continue
        suites = json.loads(raw)
        assert suites and set(suites) <= set(KNOWN_SUITES), f"{where} passes {suites}"


def test_the_release_does_not_gate_on_the_composed_journey():
    """Maintainer decision 2026-09-27 (A2 plan): the release is not gated on the
    composed journey. `suites` is passed explicitly, because the tier's default
    includes composed, so omitting it would silently start gating."""
    for name in ("release.yml", "release-dry-run.yml"):
        raw = _load(name)["jobs"]["tier2"]["with"]["suites"]
        assert json.loads(raw) == ["browser"], f"{name} passes {raw}"


def test_tier2_callers_grant_read_only():
    for where, job in _tier2_callers().items():
        # actions: read, because composed-e2e.yml's rerun guard reads earlier verdict
        # artifacts (test_reusable_workflow_permissions.py checks the whole chain).
        assert job.get("permissions") == {"actions": "read", "contents": "read"}, where


def test_release_waits_for_tier2():
    assert "tier2" in _load("release.yml")["jobs"]["release"]["needs"]
    assert "tier2" in _load("release-dry-run.yml")["jobs"]["summary"]["needs"]


# ── deselection and its local-only escape hatch ────────────────────────────
NO_DESELECT = "CB_E2E_NO_DESELECT"


def test_no_workflow_mentions_the_local_no_deselect_hatch():
    """CI always deselects tests with live register rows (maintainer decision 2).
    CB_E2E_NO_DESELECT exists so a developer can deliberately run them on a
    laptop; wired into a workflow it would become the force switch that
    decision rules out."""
    offenders = [
        path.name for path in sorted(WORKFLOWS.iterdir())
        if path.is_file() and NO_DESELECT in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"{NO_DESELECT} is local-only, but appears in {offenders}"


def test_e2e_local_passes_the_no_deselect_hatch_through():
    assert re.search(rf"-e {NO_DESELECT}(\s|$)", _recipe("e2e-local")), (
        f"e2e-local runs the script in a container; without `-e {NO_DESELECT}` the hatch never reaches it"
    )


def _collect(tmp_path: Path, **env: str) -> tuple[str, str]:
    """Run the journey script with --collect-only and return (last stdout line, log)."""
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    docker = stub / "docker"
    docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    docker.chmod(0o755)
    diagnostics = tmp_path / "diagnostics"
    result = subprocess.run(
        [str(REPO_ROOT / AGENT_SCRIPT), "--collect-only", "-q", f"--junitxml={tmp_path / 'junit.xml'}"],
        capture_output=True, text=True, check=False, cwd=REPO_ROOT,
        env={
            "PATH": f"{stub}:{Path(sys.executable).parent}:/usr/bin:/bin",
            "CB_E2E_DIAGNOSTICS_DIR": str(diagnostics),
            **env,
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    log = (diagnostics / "composed-journey.log").read_text(encoding="utf-8")
    return result.stdout.strip().splitlines()[-1], log


def test_the_journey_deselects_live_register_rows_and_logs_it(tmp_path):
    from composed_rerun_guard import REGISTER, _today, quarantined_tests

    live = quarantined_tests(REGISTER, _today())
    summary, log = _collect(tmp_path)
    if live:
        assert f"({len(live)} deselected)" in summary, summary
        assert "quarantined, deselected:" in log, "the deselect notice must reach composed-journey.log"
    else:
        assert "deselected" not in summary, summary


def test_the_local_hatch_runs_every_test_and_says_so(tmp_path):
    summary, log = _collect(tmp_path, **{NO_DESELECT: "1"})
    assert "deselected" not in summary, summary
    assert NO_DESELECT in log, "the hatch must announce itself in composed-journey.log"
