"""Presentation only: approved terminal gallery populated from native evidence."""

import argparse
import json
import os
import re
import shutil
import sys
import textwrap
from datetime import datetime, timezone

PALETTE = {
    "heading": 209,
    "active": 141,
    "pass": 142,
    "fail": 203,
    "warn": 172,
    "skipped": 245,
    "muted": 245,
}


def paint(text, role, color):
    return (
        f"\033[38;5;{PALETTE.get(role, PALETTE['muted'])}m{text}\033[0m"
        if color
        else text
    )


def wrap(text, width, indent=""):
    return "\n".join(
        textwrap.wrap(
            str(text), max(1, width), subsequent_indent=indent, replace_whitespace=False
        )
        or [""]
    )


def doctor(rows, *, width=80, color=False, unicode=True):
    counts = {
        s: sum(r.get("status") == s for r in rows)
        for s in ("pass", "fail", "warn", "skipped")
    }
    unknown = sum(r.get("status") not in counts for r in rows)
    lines = [
        (
            f"{counts['pass']} passed · {counts['fail']} failed\n{counts['warn']} warnings · {counts['skipped']} skipped"
            if width < 60
            else f"{counts['pass']} passed · {counts['fail']} failed · {counts['warn']} warnings · {counts['skipped']} skipped"
        ),
        "",
        "CHECKS",
    ]
    steps = []
    if unknown:
        lines.insert(1, f"{unknown} unknown result(s)")
    for row in rows:
        status = row.get("status", "skipped")
        label = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skipped": "SKIP"}.get(
            status, "UNKNOWN"
        )
        name = {
            ("identity", "present"): "Install identity",
            ("diagnostics", "admin"): "Admin diagnostics",
        }.get((row.get("component"), row.get("check")), row.get("check", "unknown"))
        evidence = str(row.get("evidence") or "No evidence reported")
        if width >= 90:
            lines.append(
                paint(f"  {label:<5}", status, color)
                + wrap(f"{name:<32}  {evidence}", width - 9, " " * 34)
            )
        else:
            lines.append(paint(f"  {label:<5}", status, color) + wrap(name, width - 9))
            lines.append(wrap("         " + evidence, width - 1, "         "))
        if status != "pass" and row.get("remediation"):
            steps.append(str(row["remediation"]))
    if steps:
        lines += ["", "NEXT STEPS"]
        lines.extend(
            wrap(f"  {i}. {s}", width - 1, "     ")
            for i, s in enumerate(dict.fromkeys(steps), 1)
        )
    code = 1 if counts["fail"] else 0
    lines += [
        "",
        f"No repairs made · Exit {code}",
        wrap("More: cb doctor --json · cb diag bundle", width - 1),
    ]
    text = "\n".join(lines)
    return text if unicode else text.replace("·", "-")


def status(rows, *, width=80, color=False):
    app = [r for r in rows if r[0] not in ("nginx", "nginx.service")]
    shared = [r for r in rows if r not in app]
    lines = [
        f"{sum(r[1] == 'active' for r in app)} / {len(app)} app units active · {sum(r[1] == 'active' for r in shared)} shared service(s) active",
        "Service state only; run cb doctor for readiness checks.",
    ]
    for title, units in [("APP SERVICES", app), ("SHARED SERVICES", shared)]:
        if not units:
            continue
        lines += ["", paint(title, "heading", color)]
        if width >= 110:
            lines.append(f"  {'Unit':<44} {'State':<12} Active since")
        for unit, state, since in units:
            if width >= 110:
                lines.append(
                    f"  {unit:<44} "
                    + paint(
                        f"{state:<12}", "pass" if state == "active" else "fail", color
                    )
                    + f" {since}"
                )
            else:
                lines += [
                    wrap("  " + unit, width - 1),
                    wrap(f"    {state} · active since {since}", width - 1),
                ]
    return "\n".join(
        wrap(line, width - 1) if "\033" not in line else line for line in lines
    )


# Only recognized records are aligned. Everything else, including tracebacks,
# blank lines and unterminated records, retains its contents and ordering.
STRUCTURED = re.compile(
    r"^(?P<time>\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[.,]\d+)?(?:Z|[+-]\d\d:\d\d)?)\s+(?P<level>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\s+(?P<component>\S+)\s+(?P<message>.*)$"
)


def log_record(raw, *, width=100, color=False):
    if raw.startswith("{"):
        try:
            record = json.loads(raw)
            if (
                isinstance(record.get("MESSAGE"), str)
                and "__REALTIME_TIMESTAMP" in record
            ):
                seconds, micros = divmod(int(record["__REALTIME_TIMESTAMP"]), 1000000)
                stamp = (
                    datetime.fromtimestamp(seconds, timezone.utc)
                    .replace(microsecond=micros)
                    .isoformat(timespec="microseconds")
                )
                level = {
                    "0": "CRITICAL",
                    "1": "CRITICAL",
                    "2": "CRITICAL",
                    "3": "ERROR",
                    "4": "WARN",
                    "5": "INFO",
                    "6": "INFO",
                    "7": "DEBUG",
                }.get(str(record.get("PRIORITY")), "?")
                component = (
                    record.get("_SYSTEMD_UNIT")
                    or record.get("SYSLOG_IDENTIFIER")
                    or "?"
                )
                parts = record["MESSAGE"].split("\n")
                prefix = (
                    f"{stamp} {level:<7} {component} "
                    if width < 80
                    else f"{stamp:<32} {level:<7} {component:<26} "
                )
                role = (
                    "fail"
                    if level in ("ERROR", "CRITICAL")
                    else "warn"
                    if level == "WARN"
                    else "muted"
                )
                colored = prefix.replace(
                    level.ljust(7), paint(level.ljust(7), role, color), 1
                )
                return (
                    colored
                    + ("\n" + " " * len(prefix)).join(parts)
                    + ("\n" if raw.endswith("\n") else "")
                )
        except (ValueError, TypeError, OverflowError, OSError):
            pass
    match = STRUCTURED.fullmatch(raw.rstrip("\n"))
    if not match:
        return raw
    stamp, level, component, message = match.group(
        "time", "level", "component", "message"
    )
    role = (
        "fail"
        if level in ("ERROR", "CRITICAL")
        else "warn"
        if level in ("WARN", "WARNING")
        else "muted"
    )
    if width < 80:
        return f"{stamp} {paint(level, role, color)} {component} {message}" + (
            "\n" if raw.endswith("\n") else ""
        )
    return (
        f"{stamp:<29} {paint(level.ljust(7), role, color)} {component:<26} {message}"
        + ("\n" if raw.endswith("\n") else "")
    )


def logs(source, target, *, width=100, color=False):
    # Bounded reads avoid holding an unbounded application line in memory.
    # An oversized record passes through in chunks; no bytes are dropped.
    partial = False
    while True:
        raw = source.readline(65536)
        if not raw:
            return
        oversized = len(raw) == 65536 and not raw.endswith("\n")
        target.write(
            raw if partial or oversized else log_record(raw, width=width, color=color)
        )
        target.flush()
        partial = not raw.endswith("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("surface", choices=["doctor", "logs", "status"])
    args = parser.parse_args()
    width = shutil.get_terminal_size().columns
    color = (
        sys.stdout.isatty()
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM") != "dumb"
    )
    if args.surface == "doctor":
        print(
            doctor(
                json.load(sys.stdin),
                width=width,
                color=color,
                unicode=os.environ.get("CB_ASCII") != "1"
                and os.environ.get("LC_ALL") != "C",
            )
        )
    elif args.surface == "status":
        rows = [line.rstrip("\n").split("\t", 2) for line in sys.stdin]
        print(status([r for r in rows if len(r) == 3], width=width, color=color))
    else:
        logs(sys.stdin, sys.stdout, width=width, color=color)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
