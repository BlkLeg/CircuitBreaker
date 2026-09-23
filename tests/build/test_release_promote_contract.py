"""release.yml publishes a candidate as a draft and promotes it without rebuilding.

D8 of docs/superpowers/specs/2026-09-22-installer-and-release-design.md. The
draft is what makes 'the tag is last' true: GitHub creates the tag when the
draft is published, and nothing before that step may create one.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
TEXT = RELEASE.read_text(encoding="utf-8")
DOC = yaml.safe_load(TEXT)
JOBS = DOC["jobs"]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")


def _steps(job: str) -> str:
    return "\n".join(str(step.get("run", "")) for step in JOBS[job]["steps"])


def test_dispatch_takes_a_channel_and_a_tag_push_never_builds() -> None:
    inputs = DOC[True]["workflow_dispatch"]["inputs"] if True in DOC else DOC["on"]["workflow_dispatch"]["inputs"]
    assert inputs["channel"]["options"] == ["candidate", "stable"]
    for name, job in JOBS.items():
        if name == "tag-verify":
            continue
        assert "github.event_name == 'workflow_dispatch'" in str(job.get("if", "")), (
            f"{name} may run on a tag push; only tag-verify may (a tag must be the result of a release, never its cause)"
        )


def test_the_candidate_release_is_a_draft_at_the_commit_it_was_built_from() -> None:
    run = _steps("release")
    assert re.search(r"gh release create .*--draft", run, re.S)
    assert '--target "${GITHUB_SHA}"' in run
    assert "candidate.json" in run
    assert "--draft=false" not in run


def test_promote_publishes_the_draft_and_rebuilds_nothing() -> None:
    assert "promote-verify" in JOBS["promote"]["needs"]
    verify = _steps("promote-verify")
    assert "candidate.json" in verify and "isDraft" in verify
    assert '"${GITHUB_SHA}"' in verify, "the promoted ref must be the candidate's commit"
    run = _steps("promote")
    assert "docker buildx imagetools create" in run and "@sha256:" in run
    assert "gh release edit" in run and "--draft=false" in run
    for job in ("promote-verify", "promote"):
        assert JOBS[job].get("uses") is None
        assert "build_native_release" not in _steps(job) and "docker buildx build" not in _steps(job)
    assert "build" not in JOBS["promote"]["needs"]


def test_the_composed_e2e_is_dispatched_after_publication() -> None:
    assert "gh workflow run e2e.yml" in _steps("post-publish")


def test_make_targets_dispatch_rather_than_tag() -> None:
    assert "release-candidate:" in MAKEFILE and "release-promote:" in MAKEFILE
    assert "release-tag:" not in MAKEFILE and "release-retag:" not in MAKEFILE and "release-local:" not in MAKEFILE
    assert "gh workflow run release.yml" in MAKEFILE
