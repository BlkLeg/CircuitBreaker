"""The release smoke gate must test what users actually download.

`docs/installation/quick-install.md` leads with

    curl -fsSL .../install.sh | bash

which installs the **tarball**. Until this suite existed, artifact-smoke.yml
tested only the .deb, scripts/ci/fleet/matrix.yaml declared four rows all of
which were deb or rpm, and nothing anywhere executed install.sh. The most
prominently documented way to install Circuit Breaker had no automated coverage
at any tier.

This is a policy test, not a functional one: it asserts the gate exists and
names the format, so a future format cannot be added to the build and published
without someone deciding, in a commit, whether it is smoke-tested.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE = REPO_ROOT / ".github" / "workflows" / "artifact-smoke.yml"


def _jobs() -> dict[str, dict]:
    document = yaml.safe_load(SMOKE.read_text(encoding="utf-8"))
    return document["jobs"]


def test_the_deb_is_smoke_tested() -> None:
    assert "deb-install" in _jobs(), "artifact-smoke.yml lost its deb job"


def test_the_tarball_is_smoke_tested() -> None:
    jobs = _jobs()
    assert "tarball-smoke" in jobs, (
        "artifact-smoke.yml has no tarball job. The tarball is what "
        "`curl ... install.sh | bash` installs — the path quick-install.md "
        "leads with — and it is published in every release."
    )


def test_every_smoke_job_executes_the_application() -> None:
    """A gate may not pass by not asking (ADR 0005).

    Two things count as executing the application: `--selftest`, which imports
    the ASGI target and every worker module, and a `/readyz` probe, which is
    strictly stronger because it also proves migrations applied and the
    dependencies resolved. A job doing neither is asserting identity only, and
    every identity check in this workflow passed on v0.4.2.
    """
    for name, job in _jobs().items():
        rendered = yaml.safe_dump(job)
        executes = "--selftest" in rendered or "readyz" in rendered
        assert executes, (
            f"job {name!r} installs or unpacks an artifact but never executes "
            "the application inside it — no --selftest and no /readyz probe. "
            "Every assertion short of that is an identity check, and identity "
            "checks all passed on v0.4.2."
        )
