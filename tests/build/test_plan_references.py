"""Every implementation plan's named references must resolve against the tree.

Five defects were found in the 2026-09-20 installer/release plans, and all five
had one shape: a thing in an existing system was *named* without being *read*.
A job id inferred from a display name (`publish`, when the id is `release`) —
that one reached a commit and would have failed every future Release workflow,
because GitHub rejects an unknown `needs:` target and refuses to run the whole
file. A CLI flag invented for a parser that never declared it. Health routes
placed at the root when they are mounted under a `/api/v1` prefix.

Review of the plan prose caught none of them. `yaml.safe_load` caught none of
them either: it proves a file parses and says nothing about whether the things
it names exist. This suite resolves those references mechanically, before
anyone is dispatched to implement a plan.

Scope, stated because a check trusted past its reach is worse than no check:
this finds a reference that does not RESOLVE. It cannot find a reference that
resolves to the wrong thing — a real URL with a wrong prefix, a real unit file
that is the wrong one of two, an incomplete dependency set. Two of the five
defects were exactly that, and reading the code is still the only thing that
catches them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLANS_DIR = REPO_ROOT / "plans"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

from verify_plan_references import (  # noqa: E402
    _declared_creates,
    _looks_like_path,
    verify,
)


def _plans() -> list[Path]:
    return sorted(PLANS_DIR.glob("2026-09-20-step*.md"))


def test_the_plan_set_is_present() -> None:
    """Guards against every assertion below passing vacuously."""
    plans = _plans()
    assert plans, (
        f"No 2026-09-20-step*.md plans under {PLANS_DIR}. If they were renamed, "
        "update this glob — a reference checker that checks nothing is worse "
        "than none, because it reports green."
    )


@pytest.mark.parametrize("plan", _plans(), ids=lambda p: p.name)
def test_every_reference_in_the_plan_resolves(plan: Path) -> None:
    created_elsewhere: set[str] = set()
    for other in _plans():
        created_elsewhere |= _declared_creates(other.read_text(encoding="utf-8"))

    blocking = [f for f in verify(plan, created_elsewhere) if f.kind != "already-landed"]
    assert not blocking, "\n".join(
        f"{f.plan}:{f.line}: [{f.kind}] {f.detail}" for f in blocking
    )


def test_a_symbol_name_is_not_mistaken_for_a_path() -> None:
    """The checker's own first false positive, pinned so it cannot return.

    A Files line names the file and then the symbols inside it, so the first
    version reported build_parser, main and cb_fail as missing files.
    """
    assert _looks_like_path("apps/backend/src/app/start.py")
    assert _looks_like_path("install.sh")
    assert not _looks_like_path("build_parser")
    assert not _looks_like_path("cb_fail")
    assert not _looks_like_path("t3::start_and_wait_ready")


def test_an_unknown_workflow_job_is_reported(tmp_path: Path) -> None:
    """The defect that reached a commit, pinned as a regression test."""
    plan = tmp_path / "fake-plan.md"
    plan.write_text(
        "Touches `.github/workflows/release.yml`.\n\n"
        "```yaml\n"
        "  post-publish:\n"
        "    needs: [version, publish]\n"
        "```\n",
        encoding="utf-8",
    )
    findings = verify(plan)
    unknown = [f for f in findings if f.kind == "unknown-job"]
    assert unknown, (
        "A plan naming needs: [version, publish] against release.yml was not "
        "reported, but release.yml declares no job called 'publish' — its id is "
        "'release'. This is the exact defect that shipped."
    )
    assert "publish" in unknown[0].detail
