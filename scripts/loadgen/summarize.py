#!/usr/bin/env python3
"""Render a directory of baseline result documents as a Markdown summary.

A separate script rather than a `python -c` one-liner in the workflow, because
the thing this prints is the only part of a nightly run most people will read.
It has to be able to say "this run measured nothing", and a summary that can
only print numbers will silently print `None` three times instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _format_seconds(value: Any) -> str:
    """A duration as milliseconds, or an explicit `not measured`."""
    if not isinstance(value, (int, float)):
        return "not measured"
    return f"{float(value) * 1000:.0f} ms"


def _format_verdict(target: dict[str, Any]) -> str:
    """`pass` / `fail` / `n/a` / `not measured` for one target block."""
    if not target.get("applicable"):
        return "n/a for this tier"
    passed = target.get("passed")
    if passed is None:
        return "**not measured**"
    return "pass" if passed else "**FAIL**"


def summarize(report: dict[str, Any]) -> str:
    """One tier's section of the summary."""
    lines = [f"### Tier {report.get('tier', '?')} — {report.get('git_sha', 'unknown')[:12]}"]

    loop_lag = report.get("event_loop_lag_seconds") or {}
    streams = report.get("ws_clients") or {}
    lines += [
        f"- topology load p95: {_format_seconds(report.get('topology_load_p95_seconds'))}",
        f"- monitor scheduling lag: {_format_seconds(report.get('monitor_scheduling_lag_seconds'))}",
        (
            "- event-loop lag p95 / p99: "
            f"{_format_seconds(loop_lag.get('p95'))} / {_format_seconds(loop_lag.get('p99'))}"
        ),
        (
            f"- WS clients connected: {streams.get('connected', '?')}"
            f"/{streams.get('requested', '?')}"
        ),
        f"- errors: {report.get('errors', '?')}",
    ]

    for name, target in (report.get("targets") or {}).items():
        lines.append(f"- target `{name}`: {_format_verdict(target)}")

    notes = report.get("notes") or []
    if notes:
        lines.append("- run notes:")
        lines += [f"  - {note}" for note in notes]

    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: summarize.py <directory-of-result-json>", file=sys.stderr)
        return 2

    directory = Path(sys.argv[1])
    paths = sorted(directory.glob("*.json"))
    if not paths:
        print(
            f"No baseline results were produced in `{directory}` — the run failed "
            "before any tier completed."
        )
        return 0

    sections: list[str] = []
    for path in paths:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            sections.append(f"### {path.name}\n- unreadable result document: {exc}")
            continue
        sections.append(summarize(report))

    print("\n\n".join(sections))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
