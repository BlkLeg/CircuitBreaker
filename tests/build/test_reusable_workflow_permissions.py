"""A called workflow's jobs never ask for more than the job that calls them grants.

GitHub validates this when it loads a workflow: every job in a reusable workflow
must have effective permissions that are a subset of the calling job's, all the
way down a chain of nested calls. A violation is not a red job. The CALLING
workflow fails to start at all, with nothing in the run list to click on.

The incident (Tier 2 slice A2, final review, 2026-09-27): composed-e2e.yml's
`rerun-guard` job asked for `actions: read` so it could read earlier verdict
artifacts, while all four paths into it (e2e.yml, tier2.yml, and through
tier2.yml the release and the release dry run) granted only `contents: read`.
Every one of those workflows would have failed at load. A wiring test even
pinned the callers to `{"contents": "read"}`, locking the bug in.

CLAUDE.md rule 5: dependencies pinned in two places move together, and "when a
bump breaks a pairing like this, add the guard rather than only fixing the
instance". A caller's grant and its callee's request are such a pair. This is
the guard: it parses every workflow, follows every local
`uses: ./.github/workflows/X.yml`, and recurses through nested calls.

Effective permissions of a job are its own `permissions:` block, or else its
workflow's top-level `permissions:`. Scopes are ordered none < read < write; a
scope a mapping does not name is `none`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
LOCAL_PREFIX = "./.github/workflows/"

LEVELS = {"none": 0, "read": 1, "write": 2}
UNNAMED = "<every unnamed scope>"


@dataclass(frozen=True)
class Grant:
    """A permissions block, normalised: a level for every scope."""

    default: int
    scopes: Mapping[str, int] = field(default_factory=dict)

    def level(self, scope: str) -> int:
        """The level this grant gives `scope`."""
        return self.scopes.get(scope, self.default)


def parse_grant(raw: object) -> Grant:
    """Normalise a `permissions:` value. `{}` grants nothing; `read-all` / `write-all` grant every scope."""
    if isinstance(raw, str):
        if raw == "read-all":
            return Grant(LEVELS["read"])
        if raw == "write-all":
            return Grant(LEVELS["write"])
        raise ValueError(f"unknown permissions shorthand {raw!r}")
    if isinstance(raw, Mapping):
        scopes: dict[str, int] = {}
        for scope, value in raw.items():
            if value not in LEVELS:
                raise ValueError(f"scope {scope!r} has unknown level {value!r}")
            scopes[str(scope)] = LEVELS[value]
        return Grant(LEVELS["none"], scopes)
    raise ValueError(f"permissions must be a mapping or a shorthand string, not {raw!r}")


def excess_scopes(callee: Grant, caller: Grant) -> list[str]:
    """Scopes where `callee` asks for more than `caller` grants, sorted. Empty means subset."""
    names = set(callee.scopes) | set(caller.scopes)
    excess = sorted(name for name in names if callee.level(name) > caller.level(name))
    if callee.default > caller.default:
        excess.append(UNNAMED)
    return excess


def _level_name(grant: Grant, scope: str) -> str:
    level = grant.default if scope == UNNAMED else grant.level(scope)
    return next(name for name, value in LEVELS.items() if value == level)


def _load(path: Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{path.name} is not a YAML mapping"
    return document


def _workflows() -> dict[str, dict]:
    paths = sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])
    return {path.name: _load(path) for path in paths}


def _effective(workflow: Mapping[str, object], job: Mapping[str, object]) -> Grant | None:
    """The job's own block, else the workflow's top-level one, else None (unknown)."""
    if "permissions" in job:
        return parse_grant(job["permissions"])
    if "permissions" in workflow:
        return parse_grant(workflow["permissions"])
    # No block at either level means GitHub's repository/organisation default
    # applies, which is a setting outside this tree. Guessing it would make this
    # guard assert something it cannot know, so the caller is skipped instead.
    # test_every_workflow_declares_top_level_permissions keeps that case empty.
    return None


def violations(workflows: Mapping[str, Mapping[str, object]]) -> list[str]:
    """Every (caller, callee job, scope) where a local reusable-workflow call asks for more than it is granted."""
    found: list[str] = []

    def walk(root: str, bound: Grant, callee_file: str, chain: tuple[str, ...]) -> None:
        if callee_file in chain:
            found.append(f"{root}: reusable-workflow cycle through {' -> '.join((*chain, callee_file))}")
            return
        callee = workflows.get(callee_file)
        if callee is None:
            found.append(f"{root} calls {LOCAL_PREFIX}{callee_file}, which does not exist")
            return
        for job_id, job in (callee.get("jobs") or {}).items():
            job = job or {}
            grant = _effective(callee, job)
            # A job with no permissions block, in a workflow with no top-level
            # one either, inherits the CALLER's grant (GitHub's own rule) — it
            # is not "unknowable" the way the very first caller in the chain
            # can be (test_a_caller_without_any_permissions_block_is_skipped_
            # not_guessed). There is nothing to compare against `bound` in
            # that case (the job IS `bound`, so it can never exceed it), but
            # its own `uses:` still has to be walked: skipping straight to the
            # next job here silently stopped the walk one level early and let
            # a deeper violation through undetected.
            if grant is not None:
                for scope in excess_scopes(grant, bound):
                    asked, given = _level_name(grant, scope), _level_name(bound, scope)
                    via = " -> ".join((*chain, callee_file))
                    found.append(
                        f"{root} (via {via}) calls {callee_file}:{job_id}, which asks for "
                        f"{scope}: {asked} but the caller grants {scope}: {given}"
                    )
            uses = str(job.get("uses", ""))
            if uses.startswith(LOCAL_PREFIX):
                walk(root, bound, uses[len(LOCAL_PREFIX):], (*chain, callee_file))

    for name, workflow in workflows.items():
        for job_id, job in (workflow.get("jobs") or {}).items():
            job = job or {}
            uses = str(job.get("uses", ""))
            if not uses.startswith(LOCAL_PREFIX):
                continue
            bound = _effective(workflow, job)
            if bound is None:
                continue
            walk(f"{name}:{job_id}", bound, uses[len(LOCAL_PREFIX):], (name,))
    return found


# ── ordering and subset logic, on synthetic dicts ───────────────────────────
@pytest.mark.parametrize(
    ("callee", "caller", "excess"),
    [
        ({"contents": "read"}, {"contents": "read"}, []),
        ({"contents": "read"}, {"contents": "write"}, []),
        ({"contents": "write"}, {"contents": "read"}, ["contents"]),
        ({"contents": "read"}, {"contents": "none"}, ["contents"]),
        ({"actions": "read", "contents": "read"}, {"contents": "read"}, ["actions"]),
        ({}, {}, []),
        ({"contents": "none"}, {}, []),
        ({"id-token": "write"}, {"id-token": "write", "contents": "read"}, []),
    ],
)
def test_excess_scopes_orders_none_read_write(callee, caller, excess):
    assert excess_scopes(parse_grant(callee), parse_grant(caller)) == excess


def test_shorthands_grant_every_scope():
    assert excess_scopes(parse_grant({"packages": "write"}), parse_grant("write-all")) == []
    assert excess_scopes(parse_grant({"packages": "write"}), parse_grant("read-all")) == ["packages"]
    assert excess_scopes(parse_grant("read-all"), parse_grant({"contents": "read"})) == ["<every unnamed scope>"]
    assert excess_scopes(parse_grant({}), parse_grant("read-all")) == []


@pytest.mark.parametrize("raw", ["read", {"contents": "admin"}, None, ["contents"]])
def test_an_unknown_permissions_value_is_an_error(raw):
    with pytest.raises(ValueError):
        parse_grant(raw)


def test_violations_names_caller_callee_and_scope_and_recurses():
    tree = {
        "top.yml": {
            "permissions": {"contents": "read"},
            "jobs": {"call": {"uses": "./.github/workflows/mid.yml"}},
        },
        "mid.yml": {
            "permissions": {"contents": "read"},
            "jobs": {
                "ok": {"steps": []},
                "call": {"uses": "./.github/workflows/leaf.yml"},
            },
        },
        "leaf.yml": {
            "permissions": {"contents": "read"},
            "jobs": {"guard": {"permissions": {"actions": "read", "contents": "read"}}},
        },
    }
    found = violations(tree)
    assert any(
        "top.yml:call" in line and "leaf.yml:guard" in line and "actions: read" in line and "actions: none" in line
        for line in found
    ), found
    assert any(line.startswith("mid.yml:call") and "leaf.yml:guard" in line for line in found), found
    tree["top.yml"]["jobs"]["call"]["permissions"] = {"actions": "read", "contents": "read"}
    tree["mid.yml"]["jobs"]["call"]["permissions"] = {"actions": "read", "contents": "read"}
    assert violations(tree) == []


def test_a_no_grant_intermediate_job_still_recurses_into_its_own_calls():
    """GitHub's rule: a job with no permissions block inherits its workflow's
    top-level block; if that is also absent, it gets the caller's grant. Before
    this fix, `walk` hit `continue` the instant an intermediate job's own
    `_effective` grant was None — before reaching that job's `uses:` line —
    which silently stopped the walk one level early and let a deeper violation
    through undetected. `mid.yml`'s `call` job here has no permissions block of
    its own AND `mid.yml` has no top-level block either, so its grant is
    unknowable; that must not stop `leaf.yml`'s excess `actions: read` (over
    `top.yml`'s `contents: read`-only bound) from being caught."""
    tree = {
        "top.yml": {
            "permissions": {"contents": "read"},
            "jobs": {"call": {"uses": "./.github/workflows/mid.yml"}},
        },
        "mid.yml": {
            "jobs": {"call": {"uses": "./.github/workflows/leaf.yml"}},
        },
        "leaf.yml": {
            "permissions": {"contents": "read"},
            "jobs": {"guard": {"permissions": {"actions": "read", "contents": "read"}}},
        },
    }
    found = violations(tree)
    assert any(
        "top.yml:call" in line and "leaf.yml:guard" in line and "actions: read" in line and "actions: none" in line
        for line in found
    ), found


def test_a_caller_without_any_permissions_block_is_skipped_not_guessed():
    tree = {
        "top.yml": {"jobs": {"call": {"uses": "./.github/workflows/leaf.yml"}}},
        "leaf.yml": {"permissions": "write-all", "jobs": {"j": {}}},
    }
    assert violations(tree) == []


# ── the real tree ───────────────────────────────────────────────────────────
def test_every_workflow_declares_top_level_permissions():
    """Keeps the 'unknown default' skip above empty for this repository."""
    missing = [name for name, workflow in _workflows().items() if "permissions" not in workflow]
    assert not missing, f"workflows without a top-level `permissions:` block: {missing}"


def test_the_tree_has_reusable_workflow_calls():
    """Guards against this suite passing vacuously if the parser stops finding calls."""
    calls = [
        f"{name}:{job_id}"
        for name, workflow in _workflows().items()
        for job_id, job in (workflow.get("jobs") or {}).items()
        if str((job or {}).get("uses", "")).startswith(LOCAL_PREFIX)
    ]
    assert len(calls) >= 4, calls


def test_no_reusable_workflow_asks_for_more_than_its_caller_grants():
    found = violations(_workflows())
    assert not found, (
        "GitHub refuses to start a workflow whose called jobs exceed the calling "
        "job's permissions. Grant the scope on the caller job (with a comment "
        "saying why) or drop it from the callee:\n  " + "\n  ".join(found)
    )
