"""Nothing becomes visible until a built candidate has been started.

Two releases established the shape of this failure, and neither was caught by
a test because every test asked about the *code* rather than about the
*graph*.

v0.4.2 published a binary that contained no application. Every gate passed
because the only execution any of them performed was ``--version``, which
resolves from an embedded file and exits before ``app.main`` is imported. ADR
0005 states the rule that follows from it — "a gate may not pass by not
asking" — and this file is that rule written as an executable check rather
than a paragraph.

The three properties:

  1. every job that makes something visible (a GitHub Release, a registry tag)
     depends on the installed-artifact gate;
  2. that gate does not consist solely of identity checks — something in it
     starts the service and asks it a question;
  3. the asset install.sh downloads is an asset the build produces, by name.

The third is the one with no other home. ``install.sh`` builds the tarball
name it fetches from a format string, and ``scripts/build_native_release.py``
builds the name it writes from a different one. Nothing reconciled them, and a
rename on either side is invisible until a user runs the published installer
against a published release.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
RELEASE_WORKFLOW = WORKFLOW_DIR / "release.yml"
SMOKE_WORKFLOW = WORKFLOW_DIR / "artifact-smoke.yml"
INSTALL_SH = REPO_ROOT / "install.sh"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_native_release.py"

# The job release.yml uses to run the installed-artifact contract.
SMOKE_JOB = "artifact-smoke"

# Jobs whose completion makes something publicly visible. Named rather than
# inferred: "publishes" is a judgement about what a step does, and encoding it
# here is what lets the test say so in its failure message.
PUBLISHING_JOBS = {
    "release": "creates the GitHub Release and uploads every asset",
    "image-merge": "creates the registry tags that make the pushed digests pullable",
}


def _release() -> dict:
    return yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))


def _needs(job: dict) -> set[str]:
    needs = job.get("needs")
    if isinstance(needs, str):
        return {needs}
    if isinstance(needs, list):
        return set(needs)
    return set()


def test_every_publishing_job_depends_on_the_artifact_gate() -> None:
    """A release cannot be visible before the candidate has been installed."""
    jobs = _release()["jobs"]
    missing = [
        f"{name} ({why}) does not list {SMOKE_JOB!r} in needs"
        for name, why in PUBLISHING_JOBS.items()
        if SMOKE_JOB not in _needs(jobs[name])
    ]
    assert not missing, (
        "a job that makes a release visible is not gated on the installed-"
        "artifact contract:\n  " + "\n  ".join(missing)
    )


def test_the_publishing_jobs_named_here_still_exist() -> None:
    """The register cannot silently stop describing the workflow.

    Renaming `release` to `publish` would make the test above vacuously true,
    which is the failure mode every allow-list has.
    """
    jobs = set(_release()["jobs"])
    unknown = sorted(set(PUBLISHING_JOBS) - jobs)
    assert not unknown, (
        f"release.yml has no jobs named {unknown}. If they were renamed, update "
        "PUBLISHING_JOBS — the gating assertion above passes trivially without them."
    )


def test_the_artifact_gate_starts_the_service_and_asks_it_something() -> None:
    """The gate executes the application, not just its identity.

    `--version` and `--selftest` are both satisfied by a binary that can never
    serve a request: the first resolves an embedded file, the second imports
    modules. Neither starts a process that listens. What separates a shippable
    artifact from v0.4.2's is that something asked the running service a
    question and got an answer.
    """
    text = SMOKE_WORKFLOW.read_text(encoding="utf-8")

    required = {
        "starts the packaged unit": r"systemctl start circuit-breaker\b",
        "waits for liveness": r"/api/v1/livez",
        "waits for readiness": r"/api/v1/readyz",
        "confirms migrations ran": r"alembic_version",
        "makes an authenticated request": r"/auth/me",
    }
    missing = [name for name, pattern in required.items() if not re.search(pattern, text)]
    assert not missing, (
        "artifact-smoke.yml no longer does the following, so a green run of it "
        f"would not distinguish a working artifact from an empty one: {missing}"
    )


def test_the_artifact_gate_uninstalls_what_it_installed() -> None:
    """Removal is half of "installable", and the half users hit second."""
    text = SMOKE_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"apt-get remove -y circuit-breaker", text), (
        "artifact-smoke.yml no longer removes the package it installed. An "
        "artifact that cannot be uninstalled is not one that can be shipped."
    )


def _installer_tarball_template() -> str:
    """The asset name install.sh CONSTRUCTS, not the one it is handed.

    There are two `tarball_name=` assignments. One is a function parameter
    (`local tarball_name="$2"`); the only one that describes a release asset is
    the one built from the version and the architecture, so the pattern
    requires both to appear in it.
    """
    matches = [
        value
        for value in re.findall(r'tarball_name="([^"]+)"', INSTALL_SH.read_text(encoding="utf-8"))
        if "${CB_VERSION}" in value and "${ARCH}" in value
    ]
    assert len(matches) == 1, (
        "expected exactly one place where install.sh builds a release asset name "
        f"from the version and architecture; found {matches}. If the download "
        "moved, update this test rather than removing it."
    )
    return matches[0]


def _build_archive_template() -> str:
    """The f-string `archive_name()` formats, as a literal template."""
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"def archive_name\(.*?\n(?:.*?\n)*?\s*return f\"([^\"]+)\"", source
    )
    assert match is not None, (
        "scripts/build_native_release.py no longer names archives with an "
        "f-string in archive_name(); update this test to match."
    )
    return match.group(1)


def test_install_sh_downloads_a_name_the_build_produces() -> None:
    """The two format strings describe the same file.

    install.sh builds `circuit-breaker_${CB_VERSION}_linux_${ARCH}.tar.gz`;
    the build writes `circuit-breaker_{version}_{target_os}_{target_arch}.
    {suffix}`. They are separate literals in separate languages, and a rename
    on either side produces a release whose installer 404s — after publication,
    for every user, with every build gate green.
    """
    installer = _installer_tarball_template()
    built = _build_archive_template()

    # Normalise both to one shape: placeholder names differ, the structure must
    # not. `${CB_VERSION}` and `{version}` are the same hole.
    def normalise(template: str) -> str:
        template = re.sub(r"\$\{CB_VERSION\}|\{version\}", "<version>", template)
        template = re.sub(r"\$\{ARCH\}|\{target_arch\}", "<arch>", template)
        template = re.sub(r"\{target_os\}", "linux", template)
        template = re.sub(r"\{suffix\}", "tar.gz", template)
        return template

    assert normalise(installer) == normalise(built), (
        "install.sh downloads an asset the build does not produce.\n"
        f"  install.sh:            {installer}  ->  {normalise(installer)}\n"
        f"  build_native_release:  {built}  ->  {normalise(built)}\n"
        "One of them was renamed. Every `curl | bash` install fails on the next "
        "release until they agree."
    )


def test_no_release_job_is_disabled_or_made_advisory() -> None:
    """A release job may not be turned into a warning.

    `continue-on-error: true` on a release job makes it advisory: it goes red
    and the release proceeds anyway, which is the same outcome as deleting it
    and strictly more misleading, because the job still appears in the run.
    """
    offences = [
        name
        for name, job in _release()["jobs"].items()
        if isinstance(job, dict) and job.get("continue-on-error") is True
    ]
    assert not offences, (
        f"release.yml jobs are advisory rather than blocking: {offences}. A gate "
        "that cannot fail the release is not a gate; remove it or fix it."
    )


def test_the_artifact_gate_covers_both_published_architectures() -> None:
    """release.yml calls the gate for amd64 and arm64.

    The gate's `arches` input defaults to both, and dev-ci narrows it to amd64
    because it builds one. The release must not inherit that narrowing: both
    architectures are published, so both must be installed and booted.
    """
    smoke = _release()["jobs"][SMOKE_JOB]
    passed = (smoke.get("with") or {})
    arches = passed.get("arches")
    assert arches is None, (
        f"release.yml passes arches={arches!r} to the artifact gate. The default "
        "covers both published architectures; overriding it here ships an "
        "architecture nothing installed."
    )
