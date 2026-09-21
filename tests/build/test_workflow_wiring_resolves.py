"""Every reusable-workflow call and artifact hand-off resolves, statically.

Three wiring mistakes cost a full CI round trip each — roughly forty minutes —
and none of them is visible by reading one file:

  * a caller passing an input the callee does not declare, or omitting one it
    requires;
  * a caller passing a secret the callee never asks for, which silently does
    nothing;
  * a job downloading an artifact name no job in its graph uploads, which fails
    only once the build above it has finished.

The third is the expensive one and the one this repository has most recently
had to reason about: ``artifact-smoke.yml`` downloads
``${{ inputs.artifact_prefix }}-${{ matrix.arch }}``, and its three callers
produce those artifacts under three different names — ``packages-<arch>`` from
``build.yml`` for the release and the dry run, ``dev-packages-amd64`` from
``dev-ci.yml`` for the integration branch. A mismatch between any caller and
the gate is a download that 404s after a ten-minute build.

Resolved here rather than trusted, by substituting the caller's literal
``with:`` values into the callee's artifact names and requiring a producer for
each result.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

EXPRESSION = re.compile(r"\$\{\{\s*(.+?)\s*\}\}")


def _load(path: Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document if isinstance(document, dict) else {}


def _triggers(document: dict) -> dict:
    raw = document.get("on", document.get(True))
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return dict.fromkeys(raw)
    if isinstance(raw, str):
        return {raw: None}
    return {}


def _workflows() -> list[Path]:
    return sorted(
        path for pattern in ("*.yml", "*.yaml") for path in WORKFLOW_DIR.glob(pattern)
    )


def _calls(document: dict) -> list[tuple[str, dict]]:
    """(job name, job) for every job invoking a local reusable workflow."""
    found = []
    for name, job in (document.get("jobs") or {}).items():
        if isinstance(job, dict) and isinstance(job.get("uses"), str):
            if job["uses"].startswith("./.github/workflows/"):
                found.append((name, job))
    return found


def test_every_reusable_call_supplies_the_inputs_the_callee_declares() -> None:
    """No undeclared inputs, and no missing required ones."""
    offences: list[str] = []

    for caller_path in _workflows():
        caller = _load(caller_path)
        for job_name, job in _calls(caller):
            callee_path = REPO_ROOT / job["uses"].removeprefix("./")
            if not callee_path.exists():
                offences.append(
                    f"{caller_path.name}: job {job_name!r} calls {job['uses']}, "
                    "which does not exist"
                )
                continue

            callee = _load(callee_path)
            callee_triggers = _triggers(callee)
            # `in`, not `.get(...) is None`: a bare `workflow_call:` with no
            # inputs parses as None, which is a declared trigger with nothing to
            # configure — not an absent one.
            if "workflow_call" not in callee_triggers:
                offences.append(
                    f"{caller_path.name}: job {job_name!r} calls "
                    f"{callee_path.name}, which has no `workflow_call` trigger"
                )
                continue

            declared = (callee_triggers.get("workflow_call") or {}).get("inputs") or {}
            supplied = job.get("with") or {}

            for key in sorted(set(supplied) - set(declared)):
                offences.append(
                    f"{caller_path.name}: job {job_name!r} passes input {key!r} "
                    f"to {callee_path.name}, which does not declare it"
                )
            for key, spec in sorted(declared.items()):
                if isinstance(spec, dict) and spec.get("required") and key not in supplied:
                    offences.append(
                        f"{caller_path.name}: job {job_name!r} omits required input "
                        f"{key!r} of {callee_path.name}"
                    )

    assert not offences, "reusable-workflow inputs do not resolve:\n  " + "\n  ".join(
        offences
    )


def test_every_reusable_call_supplies_only_secrets_the_callee_declares() -> None:
    """A secret the callee never declares is silently ignored.

    Which is worse than an error: the build succeeds, the artifact is produced,
    and it is unsigned.
    """
    offences: list[str] = []

    for caller_path in _workflows():
        caller = _load(caller_path)
        for job_name, job in _calls(caller):
            callee_path = REPO_ROOT / job["uses"].removeprefix("./")
            if not callee_path.exists():
                continue
            secrets = job.get("secrets")
            if not isinstance(secrets, dict):
                # `secrets: inherit` is a string, and passes everything.
                continue
            call_trigger = _triggers(_load(callee_path)).get("workflow_call") or {}
            declared = call_trigger.get("secrets") or {}
            for key in sorted(set(secrets) - set(declared)):
                offences.append(
                    f"{caller_path.name}: job {job_name!r} passes secret {key!r} to "
                    f"{callee_path.name}, which does not declare it — it will be dropped"
                )

    assert not offences, "reusable-workflow secrets do not resolve:\n  " + "\n  ".join(
        offences
    )


def _uploads(document: dict) -> list[str]:
    """Every artifact name template a workflow's jobs upload."""
    names = []
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            uses = step.get("uses") or ""
            if uses.startswith("actions/upload-artifact"):
                name = (step.get("with") or {}).get("name")
                if isinstance(name, str):
                    names.append(name)
    return names


def _downloads(document: dict) -> list[tuple[str, str, dict]]:
    """(job name, name-or-pattern, job) for every download-artifact step."""
    found = []
    for job_name, job in (document.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            uses = step.get("uses") or ""
            if uses.startswith("actions/download-artifact"):
                with_ = step.get("with") or {}
                target = with_.get("name") or with_.get("pattern")
                if isinstance(target, str):
                    found.append((job_name, target, job))
    return found


def _matrix_arches(job: dict, call_inputs: dict) -> list[str]:
    """The `arch` values a job's matrix expands to, given a caller's inputs."""
    matrix = ((job.get("strategy") or {}).get("matrix")) or {}
    if "include" in matrix:
        return [row["arch"] for row in matrix["include"] if "arch" in row]
    arch = matrix.get("arch")
    if isinstance(arch, list):
        return list(arch)
    if isinstance(arch, str):
        expression = EXPRESSION.search(arch)
        if expression:
            body = expression.group(1)
            from_json = re.fullmatch(r"fromJSON\(\s*inputs\.([A-Za-z_][\w-]*)\s*\)", body)
            if from_json:
                raw = call_inputs.get(from_json.group(1))
                if isinstance(raw, str):
                    return list(json.loads(raw))
                if isinstance(raw, list):
                    return list(raw)
    return []


def _resolve(template: str, call_inputs: dict, arch: str) -> str | None:
    """A concrete artifact name, or None when something stays unresolved."""

    def substitute(match: re.Match[str]) -> str:
        body = match.group(1)
        input_ref = re.fullmatch(r"inputs\.([A-Za-z_][\w-]*)", body)
        if input_ref:
            value = call_inputs.get(input_ref.group(1))
            return str(value) if value is not None else "\0"
        if body == "matrix.arch":
            return arch
        return "\0"

    resolved = EXPRESSION.sub(substitute, template)
    return None if "\0" in resolved else resolved


def test_every_gate_downloads_an_artifact_its_caller_uploads() -> None:
    """The artifact-smoke hand-off resolves for every caller.

    The check is deliberately concrete rather than general: it substitutes each
    caller's literal `with:` values into the gate's download names and requires
    a producer in that caller's own graph. A general "some workflow uploads
    something like this" check would pass on exactly the mismatch that matters.
    """
    offences: list[str] = []
    checked = 0

    for caller_path in _workflows():
        caller = _load(caller_path)
        caller_uploads = set(_uploads(caller))

        for job_name, job in _calls(caller):
            callee_path = REPO_ROOT / job["uses"].removeprefix("./")
            if not callee_path.exists():
                continue
            callee = _load(callee_path)
            call_inputs = job.get("with") or {}

            # Artifacts produced by any reusable workflow this caller also
            # invokes count as available: release.yml's `build` uploads what
            # its `artifact-smoke` downloads.
            available = set(caller_uploads)
            for _, sibling in _calls(caller):
                sibling_path = REPO_ROOT / sibling["uses"].removeprefix("./")
                if sibling_path.exists():
                    available |= set(_uploads(_load(sibling_path)))

            for consumer, template, consumer_job in _downloads(callee):
                arches = _matrix_arches(consumer_job, call_inputs) or [""]
                for arch in arches:
                    wanted = _resolve(template, call_inputs, arch)
                    if wanted is None:
                        continue
                    checked += 1
                    producible = any(
                        _resolve(upload, call_inputs, arch) == wanted
                        or upload == wanted
                        for upload in available
                    )
                    if not producible:
                        offences.append(
                            f"{caller_path.name}: job {job_name!r} calls "
                            f"{callee_path.name}, whose job {consumer!r} downloads "
                            f"{wanted!r} — and nothing in this workflow's graph "
                            f"uploads it. Available: {sorted(available)}"
                        )

    assert checked, (
        "no artifact hand-off was resolved, so this test proved nothing. The "
        "expression shapes it understands have probably changed."
    )
    assert not offences, "artifact hand-offs that cannot resolve:\n  " + "\n  ".join(
        offences
    )


def test_every_needs_edge_names_a_job_that_exists() -> None:
    """A `needs:` on a renamed job silently never runs the dependent.

    GitHub rejects the workflow, but only when the event that would run it
    fires — which for a release job is a tag, and by then the tag exists.
    """
    offences: list[str] = []
    for path in _workflows():
        jobs = _load(path).get("jobs") or {}
        for name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            needs = job.get("needs")
            needed = {needs} if isinstance(needs, str) else set(needs or [])
            for dependency in sorted(needed - set(jobs)):
                offences.append(
                    f"{path.name}: job {name!r} needs {dependency!r}, which is not a "
                    "job in that workflow"
                )
    assert not offences, "unresolvable needs edges:\n  " + "\n  ".join(offences)
