#!/usr/bin/env python3
"""Tier 2's two decisions that must not live in workflow YAML.

`plan` turns the caller's inputs into the list of suites to run and the ref they
check out. `result` turns `toJSON(needs)` into one verdict for the tier.

Both are here rather than inline in tier2.yml so they can be tested: a dispatch
that names a suite Tier 2 does not have must fail and name it, not run zero
suites and report green, and a selected suite that ends `skipped` must fail the
tier, because a skipped job reads as satisfied to every consumer of a run.

Pure: environment and argv in, stdout and $GITHUB_OUTPUT out. Runs on the
runner's system Python (3.10 on ubuntu-22.04).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence

# The call-job ids in tier2.yml are these names exactly, and
# tests/build/test_tier2_wiring.py fails if a suite job is added there without
# being added here, or the reverse. "mono" joins in slice A3.
KNOWN_SUITES: tuple[str, ...] = ("browser", "composed", "mono")
DEFAULT_SUITES: tuple[str, ...] = ("browser", "composed", "mono")

# `schedule` fires only from the default branch's copy of the workflow, and
# `main` trails the integration branch, so the nightly tests `dev` (design D2).
SCHEDULED_REF = "dev"

# A branch, tag or SHA, and nothing that could end an output line or reach a shell.
_REF = re.compile(r"[A-Za-z0-9._/-]{0,255}")


class PlanError(ValueError):
    """The inputs name something Tier 2 cannot run."""


def parse_suites(raw: str) -> list[str]:
    """Return the requested suites, sorted and de-duplicated. Empty input means the default set."""
    text = raw.strip()
    if not text:
        return sorted(DEFAULT_SUITES)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanError(f"suites must be a JSON array of names, got {text!r} ({exc.msg})") from exc
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise PlanError(f"suites must be a non-empty JSON array of strings, got {text!r}")
    unknown = sorted(set(value) - set(KNOWN_SUITES))
    if unknown:
        raise PlanError(f"unknown suite(s) {unknown}; Tier 2 knows {list(KNOWN_SUITES)}")
    return sorted(set(value))


def resolve_ref(event_name: str, requested: str) -> str:
    """Return the ref the suites check out: `dev` on a schedule, otherwise the requested ref."""
    if event_name == "schedule":
        return SCHEDULED_REF
    if not _REF.fullmatch(requested):
        raise PlanError(f"ref {requested!r} is not a plain branch, tag or SHA")
    return requested


def judge(results: Mapping[str, Mapping[str, object]], suites: Sequence[str]) -> list[str]:
    """Return one problem per job whose result contradicts the plan. An empty list means Tier 2 passed."""
    plan = results.get("plan", {}).get("result")
    if plan != "success":
        return [f"plan: {plan}"]
    problems: list[str] = []
    for suite in KNOWN_SUITES:
        outcome = results.get(suite, {}).get("result")
        expected = "success" if suite in suites else "skipped"
        if outcome != expected:
            problems.append(f"{suite}: {outcome} (expected {expected})")
    return problems


def _plan() -> int:
    try:
        suites = parse_suites(os.environ.get("SUITES", ""))
        ref = resolve_ref(os.environ.get("EVENT_NAME", ""), os.environ.get("REF", ""))
    except PlanError as exc:
        print(f"::error::Tier 2 plan: {exc}")
        return 1
    lines = [f"suites={json.dumps(suites, separators=(',', ':'))}", f"ref={ref}"]
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("".join(f"{line}\n" for line in lines))
    for line in lines:
        print(line)
    return 0


def _result() -> int:
    results = json.loads(os.environ["RESULTS"])
    raw_suites = os.environ.get("SUITES", "")
    suites: list[str] = json.loads(raw_suites) if raw_suites else []
    for job, detail in sorted(results.items()):
        print(f"{job}: {detail.get('result')}")
    problems = judge(results, suites)
    for problem in problems:
        print(f"::error::Tier 2 did not pass: {problem}")
    if not problems:
        print(f"Tier 2 green: {', '.join(suites)}")
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the `plan` or `result` subcommand and return its exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("plan", "result"))
    args = parser.parse_args(argv)
    return _plan() if args.command == "plan" else _result()


if __name__ == "__main__":
    sys.exit(main())
