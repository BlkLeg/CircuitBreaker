"""A `services:` container cannot read anything a step produces.

`artifact-smoke.yml`'s `deb-boot` job minted an ephemeral Postgres password in
its first step and handed it to a service container as

    POSTGRES_PASSWORD: ${{ env.CB_DB_PASSWORD }}

GitHub creates service containers during **job setup**, before the first step
runs. `CB_DB_PASSWORD` was written only by that step, via `$GITHUB_ENV`, so the
expression expanded to the empty string and `postgres:15` refused to start:
"Database is uninitialized and superuser password is not specified." Both
architectures failed identically in ~20s, in the `Initialize containers` phase,
on the v0.4.3 release tag — after the tag had already been cut.

Nothing a step writes to `$GITHUB_ENV` can ever reach its own job's `services:`
block. The ordering is structural, so the failure is total and permanent rather
than intermittent, and it cannot be reproduced locally: no `make` target starts
a service container. CI on a tag was the only place it could surface.

The idiom the broken job copied is sound where it came from. `dev-ci.yml`'s
smoke job mints the same four secrets and has no `services:` block at all — it
starts its own dependencies in a later step. Copying the minting step without
also copying that arrangement is what produced the bug.

So the guard is static: within a `services:` block, an `${{ env.X }}` reference
must resolve at job-setup time, meaning `X` is defined in a workflow-level or
job-level `env:` map. A `${{ steps.* }}` reference can never resolve there at
all.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

ENV_REFERENCE = re.compile(r"\$\{\{\s*env\.([A-Za-z_][A-Za-z0-9_-]*)\s*\}\}")
STEPS_REFERENCE = re.compile(r"\$\{\{\s*steps\.")


def _workflows() -> list[Path]:
    return sorted(
        path for pattern in ("*.yml", "*.yaml") for path in WORKFLOW_DIR.glob(pattern)
    )


def _env_keys(block: object) -> set[str]:
    """The names an `env:` map defines, or nothing when it is absent."""
    return set(block) if isinstance(block, dict) else set()


def test_service_container_env_references_resolve_at_job_setup() -> None:
    """Every `${{ env.X }}` inside a services block is defined before steps."""
    offences: list[str] = []

    for workflow in _workflows():
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        workflow_env = _env_keys(document.get("env"))

        for job_name, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict) or not job.get("services"):
                continue
            available = workflow_env | _env_keys(job.get("env"))
            rendered = yaml.safe_dump(job["services"])

            for name in sorted(set(ENV_REFERENCE.findall(rendered))):
                if name not in available:
                    offences.append(
                        f"{workflow.name}: job {job_name!r} passes "
                        f"${{{{ env.{name} }}}} to a service container, but "
                        f"{name} is not in a workflow-level or job-level env "
                        "map. If a step sets it, the container has already "
                        "been created by then and the value is the empty "
                        "string."
                    )

    assert not offences, (
        "service containers are created during job setup, before any step "
        "runs:\n  " + "\n  ".join(offences)
    )


def test_service_containers_never_reference_step_outputs() -> None:
    """A `${{ steps.* }}` reference in a services block can never resolve."""
    offences: list[str] = []

    for workflow in _workflows():
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue

        for job_name, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict) or not job.get("services"):
                continue
            if STEPS_REFERENCE.search(yaml.safe_dump(job["services"])):
                offences.append(
                    f"{workflow.name}: job {job_name!r} references a step "
                    "output from a service container. No step has run when "
                    "the container is created. Start the dependency in a "
                    "step instead, as dev-ci.yml's smoke job does."
                )

    assert not offences, "unresolvable service container references:\n  " + "\n  ".join(
        offences
    )
