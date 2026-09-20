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
    """Workflow files carrying a `schedule:` trigger.

    Globs both `*.yml` and `*.yaml` — GitHub Actions accepts either extension
    for a workflow file, and a `.yaml` workflow with a `schedule:` trigger is
    exactly as capable of silently characterising a stale default branch as a
    `.yml` one.
    """
    found: list[Path] = []
    for pattern in ("*.yml", "*.yaml"):
        for path in sorted(WORKFLOW_DIR.glob(pattern)):
            # yaml parses the bare `on:` key as the boolean True, which is a YAML
            # 1.1 quirk and exactly why this is read from the parsed document
            # rather than grepped: `on:` and `"on":` must behave identically.
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                continue
            triggers = document.get("on", document.get(True))
            if isinstance(triggers, dict) and "schedule" in triggers:
                found.append(path)
    return sorted(found)


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


def _reusable_workflow_calls(document: dict) -> list[dict]:
    """Every job that calls a reusable workflow via a job-level `uses:`.

    A job shaped this way (`jobs.<id>.uses: ./.github/workflows/other.yml`)
    has no `steps` at all, so `_checkout_steps` never sees it — but it still
    checks out whatever the CALLED workflow's own checkout step resolves to,
    on the schedule-triggered run's default-branch checkout of the CALLING
    workflow. A `uses:` that is itself a relative local path with no `ref:`
    input pinning the call is exactly the same class of blind spot as an
    unpinned `actions/checkout`.
    """
    jobs: list[dict] = []
    for job in (document.get("jobs") or {}).values():
        if isinstance(job, dict) and "uses" in job:
            jobs.append(job)
    return jobs


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

        # A job-level `uses:` (a reusable-workflow call) has no `steps`, so
        # `_checkout_steps` never sees it — but a local `./`-relative call
        # always runs at the caller's ref, so whatever the called workflow's
        # own checkout resolves to is exactly as unpinned as the caller's
        # would be. An external `owner/repo/...@ref` call pins its own ref via
        # `@ref` and is out of scope here.
        for job in _reusable_workflow_calls(document):
            uses = str(job.get("uses", ""))
            if not uses.startswith("./") and not uses.startswith("../"):
                continue
            called_path = (path.parent / uses).resolve()
            if not called_path.exists():
                offenders.append(
                    f"{path.name} calls reusable workflow {uses!r} which does not exist"
                )
                continue
            called_text = called_path.read_text(encoding="utf-8")
            if MARKER in called_text:
                continue
            called_document = yaml.safe_load(called_text)
            called_steps = _checkout_steps(called_document)
            called_unpinned = [
                step for step in called_steps if "ref" not in (step.get("with") or {})
            ]
            if called_unpinned:
                offenders.append(
                    f"{called_path.name} (called by {path.name} via job-level `uses:`, "
                    f"{len(called_unpinned)} of {len(called_steps)} checkouts unpinned)"
                )
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
