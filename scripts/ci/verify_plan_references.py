#!/usr/bin/env python3
"""Check that an implementation plan's named references resolve against the tree.

Every defect found in the 2026-09-20 installer/release plans had one shape: a
thing in an existing system was *named* without being *read*. A job id inferred
from a display name. A CLI flag invented for a parser. A file path that had
moved. None were caught by review of the plan; one reached a commit and would
have failed every future Release workflow, because `yaml.safe_load` proves a
file parses and says nothing about whether `needs:` points at a job that exists.

So this resolves the references a plan makes, mechanically, before anyone is
dispatched to implement it.

WHAT IT CATCHES
  * a `Modify:` / `Read:` path in a task's Files block that does not exist
  * a `Create:` path that already exists (the plan is stale, or the work landed)
  * a `needs:` entry inside an embedded workflow snippet naming a job that the
    real workflow does not declare
  * a `--flag` passed to a repo Python script whose argparse does not declare
    it, unless the plan says it adds that flag

WHAT IT DOES NOT CATCH, and must never be trusted to
  * semantic errors in a value that exists: a real URL with the wrong prefix, a
    real unit file that is the wrong one of two, a dependency set that is
    incomplete. Two of the five defects this tool was written after were of that
    kind, and no static check would have found them. Reading the code is still
    the only thing that does.
  * anything inside prose. Only structured Files blocks and fenced code are read.

Usage:
    verify_plan_references.py plans/*.md          # exits 1 on any unresolved reference
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# A task's Files block: "- Create: `path`" / "- Modify: `path:12-34`" / "- Test: `path`"
_FILES_LINE = re.compile(
    r"^\s*-\s*(Create|Modify|Test|Read for reference|Read first)\s*:\s*(.+)$",
    re.IGNORECASE,
)
_BACKTICKED = re.compile(r"`([^`\s]+)`")
_FENCE = re.compile(r"^```")
_NEEDS = re.compile(r"^\s*needs:\s*(.+)$")
_SCRIPT_FLAGS = re.compile(r"(scripts/[\w/\-]+\.py)((?:\s+--[\w-]+)+)")
_FLAG = re.compile(r"--[\w-]+")


@dataclass(frozen=True)
class Finding:
    """One unresolved reference.

    Attributes:
        plan: Plan file the reference was found in.
        line: 1-indexed line number.
        kind: Short category, e.g. "missing-path".
        detail: What did not resolve and why it matters.
    """

    plan: str
    line: int
    kind: str
    detail: str


_PATH_SUFFIXES = (
    ".py", ".sh", ".md", ".yml", ".yaml", ".csv", ".json", ".toml",
    ".service", ".conf", ".txt", ".jsx", ".js", ".ini",
)


def _looks_like_path(token: str) -> bool:
    """True for a repo path, false for a symbol name cited on the same line.

    A Files line names the file and then the symbols inside it, so not every
    backticked token on that line is a path. Requiring a separator or a known
    suffix is what keeps a symbol name like build_parser from being reported as
    a missing file -- the tool's own first false-positive class, found by
    running it against the plans it was written for.
    """
    return "/" in token or token.endswith(_PATH_SUFFIXES)


def _strip_line_range(raw: str) -> str:
    """`app/x.py:12-34` -> `app/x.py`; a trailing :N or :N-M is a citation."""
    return re.sub(r":\d+(-\d+)?$", "", raw)


def _declared_creates(text: str) -> set[str]:
    created: set[str] = set()
    for raw in text.splitlines():
        match = _FILES_LINE.match(raw)
        if match and match.group(1).lower() == "create":
            for path in _BACKTICKED.findall(match.group(2)):
                created.add(_strip_line_range(path))
    return created


def _check_paths(plan: Path, text: str, created_elsewhere: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        match = _FILES_LINE.match(raw)
        if not match:
            continue
        verb = match.group(1).lower()
        for cited in _BACKTICKED.findall(match.group(2)):
            path = _strip_line_range(cited)
            if any(ch in path for ch in "*<>"):
                continue  # a glob or a placeholder the plan tells you to fill in
            if not _looks_like_path(path):
                continue  # a symbol name cited beside the file it lives in
            target = REPO_ROOT / path
            if verb == "create":
                if target.exists():
                    findings.append(
                        Finding(
                            plan.name,
                            number,
                            "already-landed",
                            f"{path} is listed as Create: but already exists — "
                            "this task has most likely already been implemented",
                        )
                    )
            elif not target.exists():
                if path in created_elsewhere:
                    continue  # an earlier plan in this set creates it
                findings.append(
                    Finding(
                        plan.name,
                        number,
                        "missing-path",
                        f"{path} is listed as {verb.title()}: but does not exist",
                    )
                )
    return findings


def _workflow_jobs(name: str) -> set[str] | None:
    """Job ids declared by a real workflow, or None if it is not in the tree."""
    path = REPO_ROOT / ".github" / "workflows" / name
    if not path.exists():
        return None
    try:
        import yaml
    except ModuleNotFoundError:  # pragma: no cover - dev dependency is present
        return None
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return None
    jobs = document.get("jobs")
    return set(jobs) if isinstance(jobs, dict) else None


def _check_needs(plan: Path, text: str) -> list[Finding]:
    """A `needs:` in an embedded snippet must name a job the workflow declares.

    The workflow a snippet belongs to is taken from the nearest preceding mention
    of a `.github/workflows/<name>.yml` path, which is how these plans are
    written: the file is named, then the snippet follows.
    """
    findings: list[Finding] = []
    current: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        named = re.search(r"\.github/workflows/([\w.-]+\.yml)", raw)
        if named:
            current = named.group(1)
        match = _NEEDS.match(raw)
        if not (match and current):
            continue
        declared = _workflow_jobs(current)
        if declared is None:
            continue
        value = match.group(1).strip()
        try:
            names = ast.literal_eval(value) if value.startswith("[") else [value]
        except (ValueError, SyntaxError):
            names = [part.strip() for part in value.strip("[]").split(",") if part.strip()]
        for candidate in names:
            candidate = str(candidate).strip().strip("'\"")
            if not candidate or "$" in candidate:
                continue
            # A job the plan itself adds to that workflow is legitimate.
            if candidate in declared or re.search(rf"^\s*{re.escape(candidate)}:\s*$", text, re.M):
                continue
            findings.append(
                Finding(
                    plan.name,
                    number,
                    "unknown-job",
                    f"needs: {candidate!r} — {current} declares no such job "
                    f"(it has {sorted(declared)}). GitHub fails the ENTIRE "
                    "workflow on an unknown needs target.",
                )
            )
    return findings


def _script_flags(script: str) -> set[str] | None:
    """Flags a repo script's argparse declares, or None if it is not in the tree."""
    path = REPO_ROOT / script
    if not path.exists():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return None
    flags: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    if argument.value.startswith("--"):
                        flags.add(argument.value)
    return flags


def _check_script_flags(plan: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        for script, tail in _SCRIPT_FLAGS.findall(raw):
            declared = _script_flags(script)
            if declared is None:
                continue
            for flag in _FLAG.findall(tail):
                if flag in declared:
                    continue
                # The plan may be the thing that adds it.
                if re.search(rf"[Aa]dd(s|ing)?\b[^\n]*`{re.escape(flag)}`", text):
                    continue
                findings.append(
                    Finding(
                        plan.name,
                        number,
                        "unknown-flag",
                        f"{script} is invoked with {flag}, which its argparse does "
                        f"not declare (it has {sorted(declared)}), and no step in "
                        "this plan says it is added",
                    )
                )
    return findings


def verify(plan: Path, created_elsewhere: set[str] | None = None) -> list[Finding]:
    """Every unresolved reference in one plan."""
    text = plan.read_text(encoding="utf-8")
    return (
        _check_paths(plan, text, created_elsewhere or set())
        + _check_needs(plan, text)
        + _check_script_flags(plan, text)
    )


def main(argv: list[str] | None = None) -> int:
    """Verify each plan named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("plans", nargs="+", help="Plan markdown files to verify.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also fail on already-landed Create: paths (default: report only).",
    )
    args = parser.parse_args(argv)

    paths = [Path(name) for name in args.plans]
    # Files any plan in this set creates: a later plan may legitimately modify one.
    created_elsewhere: set[str] = set()
    for path in paths:
        created_elsewhere |= _declared_creates(path.read_text(encoding="utf-8"))

    findings: list[Finding] = []
    for path in paths:
        findings.extend(verify(path, created_elsewhere))

    blocking = [f for f in findings if f.kind != "already-landed"]
    landed = [f for f in findings if f.kind == "already-landed"]

    for finding in blocking:
        print(f"{finding.plan}:{finding.line}: [{finding.kind}] {finding.detail}")
    for finding in landed:
        print(f"{finding.plan}:{finding.line}: [{finding.kind}] {finding.detail}")

    if blocking or (args.strict and landed):
        count = len(blocking) + (len(landed) if args.strict else 0)
        print(f"\n{count} unresolved reference(s).", file=sys.stderr)
        return 1
    print(
        f"All references resolve across {len(paths)} plan(s)"
        + (f" ({len(landed)} already-landed note(s))." if landed else ".")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
