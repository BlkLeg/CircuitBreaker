"""A `needs:` edge that names no job silently kills the whole workflow.

`post-publish` was committed with `needs: [version, publish]`. No job in
`release.yml` has the id `publish` — the publishing job's id is `release`;
`publish` was only its display `name:` ("Publish Release"), which is what
misled the plan that added it. GitHub Actions rejects a workflow whose
`needs:` references an unknown job id and refuses to run the ENTIRE
workflow, not just the offending job — so this would have blocked every
future release, not just skipped verification of one.

`yaml.safe_load` only checks that the file is valid YAML; it has nothing to
say about whether `needs:` points at a job that exists. 688 green tests in
this suite said nothing about it, because none of them looked at job-graph
references before this one. This is exactly the failure mode this whole
workstream exists to close: a gate that passes by not asking.

So this guard is static and mechanical, across every workflow file: every
`needs:` entry, in either the string form (`needs: build`) or the list form
(`needs: [build, test]`), must resolve to a job id declared in the same
file's `jobs:` mapping.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


def _workflows() -> list[Path]:
    return sorted(WORKFLOW_DIR.glob("*.yml"))


def _needs_edges(path: Path) -> list[tuple[str, str]]:
    """(job_id, needed_job_id) pairs declared by every job in `path`."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return []
    jobs = document.get("jobs") or {}
    edges: list[tuple[str, str]] = []
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        needs = job.get("needs")
        if needs is None:
            continue
        if isinstance(needs, str):
            needed = [needs]
        elif isinstance(needs, list):
            needed = [str(item) for item in needs]
        else:
            continue
        for needed_id in needed:
            edges.append((str(job_id), needed_id))
    return edges


def test_at_least_one_needs_edge_exists() -> None:
    """Guards against the checks below passing vacuously if the parser breaks."""
    total = sum(len(_needs_edges(path)) for path in _workflows())
    assert total >= 5, (
        f"Only found {total} `needs:` edges across {WORKFLOW_DIR}/*.yml. "
        "Either the workflows genuinely lost their job dependencies, or the "
        "parser above no longer recognises `needs:` in one of its forms — in "
        "either case the checks in this file are not exercising anything."
    )


def test_every_needs_entry_resolves_to_a_declared_job() -> None:
    offenders: list[str] = []
    for path in _workflows():
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        declared = set((document.get("jobs") or {}).keys())
        for job_id, needed_id in _needs_edges(path):
            if needed_id not in declared:
                offenders.append(
                    f"{path.name}: job {job_id!r} needs {needed_id!r}, which is "
                    f"not a declared job id in that file (declared: {sorted(declared)})"
                )
    assert not offenders, (
        "These jobs `needs:` a job id that does not exist in the same "
        "workflow file:\n  " + "\n  ".join(offenders) + "\n\n"
        "GitHub Actions rejects the ENTIRE workflow when a `needs:` entry "
        "does not resolve, not just the offending job — this is a "
        "release-blocking defect, not a lint warning. This is exactly how "
        "post-publish shipped with `needs: [version, publish]` when the "
        "publishing job's id is `release` (`publish` was only its display "
        "name): yaml.safe_load parses it fine, and nothing else in this "
        "suite looked at job-graph references."
    )
