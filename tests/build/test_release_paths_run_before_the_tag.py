"""No gate a release depends on may run for the first time during a release.

This is the class of failure behind both of the last two releases, and it is
not a bug in any one workflow — it is a property of the graph.

v0.4.2 published a binary containing no application. Every blocking gate was
green, because the only execution any of them performed was ``--version``,
which resolves from an embedded file and exits before the application is
imported.

v0.4.3 then added the job that would have caught it — ``artifact-smoke.yml``'s
``deb-boot`` — and that job died in ``Initialize containers`` on both
architectures, because its Postgres service container read a password a later
step minted (see ``test_service_containers_resolve_at_job_setup.py``). The YAML
was wrong in a way no review caught and no run could catch, because
``artifact-smoke.yml`` was reachable **only** from ``release.yml``, which runs
only on a tag. The first execution of the gate was the release it was supposed
to gate.

So the property asserted here is structural rather than textual: every reusable
workflow ``release.yml`` depends on must also be called by at least one
workflow that triggers on ``push`` or ``pull_request``. A gate that only a tag
can start is a gate whose own defects are discovered by a tag.

An exception has to be declared, owned and dated in
``specs/1.0.0/release-control/tag-only-gates.csv`` — the same shape as the
quarantine register, and for the same reason: "we know, and here is who is
fixing it by when" is an answer; silence is not.
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
RELEASE_CONTROL = REPO_ROOT / "specs/1.0.0/release-control"
EXCEPTIONS = RELEASE_CONTROL / "tag-only-gates.csv"
OWNER_MAP = RELEASE_CONTROL / "owner-map.md"

RELEASE_WORKFLOW = WORKFLOW_DIR / "release.yml"

# Triggers that a contributor can cause before a tag exists. `schedule` is
# deliberately absent: a nightly run is not "before the tag" for a change
# landing today, and a scheduled workflow loads its definition from the default
# branch, so it does not exercise the ref under review either.
PRE_TAG_EVENTS = frozenset({"push", "pull_request"})


def _load(path: Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document if isinstance(document, dict) else {}


def _triggers(document: dict) -> dict:
    # PyYAML parses a bare `on:` key as the boolean True.
    raw = document.get("on", document.get(True))
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return dict.fromkeys(raw)
    if isinstance(raw, str):
        return {raw: None}
    return {}


def _called_workflows(document: dict) -> set[str]:
    """The reusable workflows this document invokes, by file name."""
    called: set[str] = set()
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        uses = job.get("uses")
        if isinstance(uses, str) and uses.startswith("./.github/workflows/"):
            called.add(Path(uses).name)
    return called


def _workflows() -> list[Path]:
    return sorted(
        path for pattern in ("*.yml", "*.yaml") for path in WORKFLOW_DIR.glob(pattern)
    )


def _pre_tag_callers() -> dict[str, set[str]]:
    """workflow file name -> the pre-tag workflows that call it."""
    callers: dict[str, set[str]] = {}
    for path in _workflows():
        document = _load(path)
        triggers = _triggers(document)
        if not (PRE_TAG_EVENTS & set(triggers)):
            continue
        # A `push` restricted to tags is a tag trigger wearing a push's name.
        push = triggers.get("push")
        events = set(triggers)
        if isinstance(push, dict) and "tags" in push and "branches" not in push:
            events.discard("push")
        if not (PRE_TAG_EVENTS & events):
            continue
        for name in _called_workflows(document):
            callers.setdefault(name, set()).add(path.name)
    return callers


def _exceptions() -> dict[str, dict[str, str]]:
    if not EXCEPTIONS.exists():
        return {}
    with EXCEPTIONS.open(encoding="utf-8", newline="") as handle:
        return {row["workflow"]: row for row in csv.DictReader(handle)}


def test_release_calls_at_least_one_reusable_workflow() -> None:
    """The premise: this test has something to check."""
    called = _called_workflows(_load(RELEASE_WORKFLOW))
    assert called, (
        "release.yml calls no reusable workflow. If the release was inlined, "
        "this test needs rewriting against whatever replaced it rather than "
        "quietly passing."
    )


def test_every_release_gate_also_runs_before_the_tag() -> None:
    """Each workflow release.yml depends on is also reachable pre-tag."""
    callers = _pre_tag_callers()
    exceptions = _exceptions()
    today = datetime.now(UTC).date()

    offences: list[str] = []
    for name in sorted(_called_workflows(_load(RELEASE_WORKFLOW))):
        if callers.get(name):
            continue

        row = exceptions.get(name)
        if row is None:
            offences.append(
                f"{name}: called by release.yml and by nothing that runs on a "
                "push or a pull request. Its first execution for any given "
                "change is the release. Call it from ci.yml or dev-ci.yml, or "
                f"declare it in {EXCEPTIONS.name} with an owner, a tracking "
                "item and an expiry."
            )
            continue

        for field in ("owner", "reason", "tracking", "expires"):
            if not (row.get(field) or "").strip():
                offences.append(f"{name}: exception row is missing {field}")
        expires = (row.get("expires") or "").strip()
        if expires:
            try:
                expiry = date.fromisoformat(expires)
            except ValueError:
                offences.append(f"{name}: expires {expires!r} is not an ISO date")
            else:
                if expiry < today:
                    offences.append(
                        f"{name}: exception expired on {expiry.isoformat()}. Either "
                        "wire it into a pre-tag workflow or renew the row with a "
                        "stated reason."
                    )

    assert not offences, "release gates that only a tag can start:\n  " + "\n  ".join(
        offences
    )


def test_the_installed_artifact_gate_runs_on_the_integration_branch() -> None:
    """Named explicitly, because this is the one that cost two releases.

    The general rule above would be satisfied by any pre-tag caller. This
    pins the specific arrangement: the workflow that installs and boots a
    built candidate runs on both the integration branch and the branch
    releases are cut from.
    """
    callers = _pre_tag_callers().get("artifact-smoke.yml", set())
    for required in ("dev-ci.yml", "ci.yml"):
        assert required in callers, (
            f"artifact-smoke.yml is not called by {required}. The installed-"
            "artifact gate has to run where changes land, not only where they "
            f"are published. Current pre-tag callers: {sorted(callers) or 'none'}"
        )


def test_exception_rows_describe_a_workflow_release_actually_depends_on() -> None:
    """The register cannot accumulate rows for workflows that moved on."""
    called = _called_workflows(_load(RELEASE_WORKFLOW))
    stale = sorted(set(_exceptions()) - called)
    assert not stale, (
        f"{EXCEPTIONS.name} excuses {stale}, which release.yml no longer calls. "
        "Remove the rows."
    )


def test_exception_owners_are_named_in_the_owner_map() -> None:
    """An owner who is not in the owner map is not an owner."""
    if not _exceptions():
        return
    owner_text = OWNER_MAP.read_text(encoding="utf-8")
    unknown = sorted(
        {
            row["owner"].strip()
            for row in _exceptions().values()
            if row.get("owner") and row["owner"].strip() not in owner_text
        }
    )
    assert not unknown, (
        f"{EXCEPTIONS.name} names owners absent from {OWNER_MAP.name}: {unknown}"
    )
