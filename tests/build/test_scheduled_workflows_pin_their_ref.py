"""A scheduled workflow runs the default branch's copy of itself.

`.github/workflows/e2e.yml` redirects its scheduled run to `dev` with
`ref: ${{ github.event_name == 'schedule' && 'dev' || '' }}`, because `main`
trails the integration branch. That redirect never executed for nine-plus
consecutive nightlies up to 2026-09-19: a `schedule` event loads the workflow
file from the **default branch**, and `main`'s copy still had a bare
`actions/checkout@v5`. Every red nightly characterised three-week-old `main`
rather than the code the fixes went into.

The failure is silent. Nothing in the run log says "this is the default
branch's copy" — the tell is the checkout line, which nobody reads, and a
run manifest that records `GITHUB_SHA` rather than the checked-out ref.

So the guard is static and mechanical: a workflow that can be triggered by
`schedule` either pins a ref on every checkout, or says in one comment that
default-branch execution is intentional. Both are legitimate. Silence is not,
because silence is indistinguishable from the bug.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
MARKER = "# scheduled-ref: default-branch-intentional"


def _scheduled_workflows() -> list[Path]:
    """Workflow files carrying a `schedule:` trigger."""
    found: list[Path] = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        # yaml parses the bare `on:` key as the boolean True, which is a YAML 1.1
        # quirk and exactly why this is read from the parsed document rather than
        # grepped: `on:` and `"on":` must behave identically.
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        triggers = document.get("on", document.get(True))
        if isinstance(triggers, dict) and "schedule" in triggers:
            found.append(path)
    return found


def _checkout_steps(document: dict) -> list[dict]:
    """Every actions/checkout step in the document, across all jobs."""
    steps: list[dict] = []
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and str(step.get("uses", "")).startswith("actions/checkout"):
                steps.append(step)
    return steps


def test_at_least_one_scheduled_workflow_exists() -> None:
    """Guards against the guard passing vacuously if the parser breaks."""
    assert _scheduled_workflows(), (
        "No workflow with a `schedule:` trigger was found. Either the repo has "
        "none — in which case delete this suite — or the parser above no longer "
        "recognises the trigger, in which case this whole file is passing for "
        "the wrong reason."
    )


def test_scheduled_workflows_pin_a_ref_or_declare_intent() -> None:
    offenders: list[str] = []
    for path in _scheduled_workflows():
        text = path.read_text(encoding="utf-8")
        if MARKER in text:
            continue
        document = yaml.safe_load(text)
        steps = _checkout_steps(document)
        unpinned = [step for step in steps if "ref" not in (step.get("with") or {})]
        if unpinned:
            offenders.append(f"{path.name} ({len(unpinned)} of {len(steps)} checkouts unpinned)")
    assert not offenders, (
        "These workflows can be triggered by `schedule` but check out without an "
        f"explicit ref: {offenders}. A scheduled run loads this file from the "
        "DEFAULT branch, so an unpinned checkout tests the default branch "
        "whatever the newest copy of this file says. That silently characterised "
        "three-week-old `main` for nine consecutive nightlies.\n\n"
        "Fix by either pinning the ref:\n"
        "    - uses: actions/checkout@v5\n"
        "      with:\n"
        "        ref: ${{ github.event_name == 'schedule' && 'dev' || '' }}\n"
        f"or, if default-branch execution is deliberate, adding this comment:\n"
        f"    {MARKER}"
    )
