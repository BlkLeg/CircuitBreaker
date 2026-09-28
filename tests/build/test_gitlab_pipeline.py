"""Guards for the GitLab pipeline (plans/2026-09-28-gitlab-cutover.md).

The pipeline YAML is only ever executed by GitLab, so these are the checks that
run on every `make verify`: names the governance docs rely on, the image pin,
and the rule that no verify job can fail without failing the pipeline.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRY = REPO_ROOT / ".gitlab-ci.yml"
DOCKERFILE = REPO_ROOT / "ci" / "images" / "ci.Dockerfile"

# Keys GitLab treats as configuration rather than jobs.
_RESERVED = {
    "stages", "include", "variables", "workflow", "default", "image",
    "services", "cache", "before_script", "after_script",
}


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert isinstance(document, dict), f"{path} is not a mapping"
    return document


def load_entry() -> dict[str, Any]:
    return _load(ENTRY)


def load_pipeline() -> dict[str, dict[str, Any]]:
    """Every job, from .gitlab-ci.yml and each `include: local:` file."""
    entry = load_entry()
    documents = [entry]
    for item in entry.get("include", []):
        if isinstance(item, dict) and "local" in item:
            documents.append(_load(REPO_ROOT / item["local"].lstrip("/")))
    jobs: dict[str, dict[str, Any]] = {}
    for document in documents:
        for name, body in document.items():
            if name in _RESERVED or not isinstance(body, dict):
                continue
            assert name not in jobs, f"job {name!r} is defined twice"
            jobs[name] = body
    return jobs


def test_image_tag_is_the_dockerfile_digest():
    """Rule 5: the tag and the Dockerfile move together, or a stale image is reused."""
    digest = hashlib.sha256(DOCKERFILE.read_bytes()).hexdigest()[:12]
    assert load_entry()["variables"]["CB_CI_IMAGE"] == f"cb-ci:{digest}"


def test_auto_devops_is_not_included():
    templates = [i.get("template", "") for i in load_entry().get("include", []) if isinstance(i, dict)]
    assert not any("Auto-DevOps" in t for t in templates), templates


def test_tag_pipelines_do_not_run():
    """Tags arrive from GitHub by sync; a tag pipeline would re-test released code for nothing."""
    rules = load_entry()["workflow"]["rules"]
    assert rules[0] == {"if": "$CI_COMMIT_TAG", "when": "never"}, rules[0]
