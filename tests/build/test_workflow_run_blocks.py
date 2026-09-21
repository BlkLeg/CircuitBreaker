"""Multi-line `run:` steps must use a block scalar, never a plain scalar.

This guards a failure that cost the v0.4.2 release. The image job had:

    run: shred -u /tmp/agent-signing-key 2>/dev/null || rm -f /tmp/agent-signing-key
      DIGEST=$(python3 -c "...")
      mkdir -p /tmp/digests
      touch "/tmp/digests/${DIGEST#sha256:}"

Without a leading `|`, YAML folds those continuation lines onto the first one
with spaces. The whole body became a single command line, so a SUCCESSFUL
`shred` short-circuited the `||` and the digest was never written — and the
step still exited 0. The break only surfaced one step later, as
`No files were found with the provided path: /tmp/digests/*`, on a tag push,
which is the one trigger no pre-merge gate exercises.

A folded plain scalar is never what a multi-line shell body wants, so this is
a shape check over the raw YAML source rather than a check on any one step.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

_RUN_KEY = re.compile(r"^(?P<indent>\s*)(?:-\s+)?run:\s*(?P<value>\S.*)$")
_NEXT_KEY = re.compile(r"^\s*(?:-\s+)?[A-Za-z_][\w-]*:(?:\s|$)")


def _folded_run_blocks(path: Path) -> list[tuple[int, str, list[str]]]:
    """Return (line_no, first_line, continuation_lines) for each folded run:.

    A `run:` whose value starts with a block indicator (`|`, `>`, and their
    chomping/indentation variants) is fine. Anything else that carries
    continuation lines is a plain scalar being silently joined.
    """
    lines = path.read_text().splitlines()
    findings: list[tuple[int, str, list[str]]] = []

    for index, line in enumerate(lines):
        match = _RUN_KEY.match(line)
        if match is None:
            continue

        value = match.group("value").strip()
        if value.startswith(("|", ">")):
            continue

        key_column = len(match.group("indent"))
        continuations: list[str] = []
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                break
            indent = len(candidate) - len(candidate.lstrip())
            if indent <= key_column or _NEXT_KEY.match(candidate):
                break
            continuations.append(candidate.strip())

        if continuations:
            findings.append((index + 1, value, continuations))

    return findings


def _workflows() -> list[Path]:
    return sorted(
        p for p in WORKFLOW_DIR.iterdir() if p.suffix in {".yml", ".yaml"}
    )


def test_workflow_directory_is_present():
    """A rename must fail loudly rather than silently checking nothing."""
    assert WORKFLOW_DIR.is_dir(), f"{WORKFLOW_DIR} is missing"
    assert _workflows(), f"no workflow files found under {WORKFLOW_DIR}"


@pytest.mark.parametrize("workflow", _workflows(), ids=lambda p: p.name)
def test_multiline_run_uses_a_block_scalar(workflow: Path):
    findings = _folded_run_blocks(workflow)
    if not findings:
        return

    report = []
    for line_no, first, continuations in findings:
        folded = " ".join([first, *continuations])
        report.append(
            f"{workflow.relative_to(REPO_ROOT)}:{line_no}\n"
            f"    run: {first}\n"
            + "".join(f"      + {c}\n" for c in continuations)
            + f"    YAML folds this to a single command:\n      {folded}\n"
            f"    Use 'run: |' so each line runs as its own command."
        )

    pytest.fail(
        "Multi-line `run:` written as a plain scalar; YAML joins the lines "
        "into one command:\n\n" + "\n\n".join(report)
    )
