#!/usr/bin/env python3
"""Drive a bounded HTTP + WebSocket baseline and emit one non-blocking JSON report.

Route §5 stage 1: this is measurement, never a gate. It records what it saw,
including when it saw nothing, and the caller decides what that means. Two rules
follow from that and are worth stating because both were broken once:

* **A number that could not be measured is `null`, never a default.** The
  scrape URL was wrong for the first revision of this script, so every metric
  came back empty and the reports looked complete while carrying no server-side
  data at all. `scrape_metrics` now fails loudly into `errors` and the report
  says which fields it could not fill.
* **Load that did not happen is not reported as load.** WebSocket clients are
  confirmed connected by reading the stream's own handshake frame; a rejected
  subscription is counted, not slept through.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
# Imported after the `sys.path` bootstrap above, which is what makes
# `scripts.loadgen` importable when this file is run directly as a script.
from scripts.loadgen.config import (
    BROWSER_POLL_INTERVAL_SECONDS,
    RESULT_FIELDS,
    TIERS,
    UNMEASURED,
    evaluate_targets,
)

#: The read routes a browser user walks. `/graph/topology` is first among
#: equals: it is the source of the topology-load target, and the only route
#: here whose p95 is scored rather than merely recorded.
ROUTES = (
    "/api/v1/capabilities",
    "/api/v1/discovery/status",
    "/api/v1/agents/presence",
    "/api/v1/graph/topology",
    "/api/v1/monitors/overview",
)
TOPOLOGY_ROUTE = "/api/v1/graph/topology"

WS_ROUTES = (
    "/api/v1/topology/stream",
    "/api/v1/monitors/stream",
    "/api/v1/agents/stream",
    "/api/v1/discovery/stream",
    "/api/v1/telemetry/stream",
)

#: `app.api.metrics` is mounted at the `/api/v1/metrics` prefix *and* declares
#: its route as `/metrics`, so the scrape path carries the segment twice. This
#: is documented in docs/metrics.md as a trap, and this script fell into it:
#: `GET /api/v1/metrics` is a 404, which read as "no metrics" rather than as an
#: error and left every server-side field null in every report.
METRICS_PATH = "/api/v1/metrics/metrics"

#: How long to wait for a stream's first frame before calling the subscription
#: failed. The handshake is local and immediate; anything slower is a fault.
WS_HANDSHAKE_TIMEOUT_SECONDS = 10.0

HTTP_TIMEOUT_SECONDS = 15.0


def percentile(values: list[float], quantile: float) -> float | None:
    """Nearest-rank percentile of *values*, or `None` when there is no sample."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1)
    return ordered[max(0, index)]


def gauge_value(metrics_text: str, metric_name: str) -> float | None:
    """The value of an unlabelled gauge in Prometheus exposition text.

    Matches on `name` followed by a space so a metric cannot be confused with
    another whose name it prefixes — `circuitbreaker_event_loop_lag_seconds`
    and `circuitbreaker_event_loop_lag_seconds_hist` differ only in a suffix.
    """
    prefix = f"{metric_name} "
    for line in metrics_text.splitlines():
        if line.startswith("#") or not line.startswith(prefix):
            continue
        try:
            return float(line.rsplit(" ", 1)[1])
        except (IndexError, ValueError):
            continue
    return None


def histogram_quantile(metrics_text: str, metric_name: str, quantile: float) -> float | None:
    """Interpolation-free quantile estimate from a Prometheus histogram.

    The total observation count comes from the `+Inf` bucket, which is the only
    bucket guaranteed to hold every sample. An earlier revision used the largest
    *finite* bucket as the total; every observation above that bucket was then
    missing from the denominator, the rank threshold came out too low, and the
    function returned a bucket below the true quantile — biased low in exactly
    the slow-tail case a p99 exists to expose.
    """
    buckets: list[tuple[float, float]] = []
    total: float | None = None
    for line in metrics_text.splitlines():
        if line.startswith("#") or not line.startswith(f"{metric_name}_bucket"):
            continue
        match = re.search(r'le="([^"]+)"', line)
        if match is None:
            continue
        try:
            count = float(line.rsplit(" ", 1)[1])
        except (IndexError, ValueError):
            continue
        if match.group(1) == "+Inf":
            total = count
        else:
            buckets.append((float(match.group(1)), count))

    if not buckets or total is None or total <= 0:
        return None
    buckets.sort()
    threshold = total * quantile
    for upper_bound, cumulative in buckets:
        if cumulative >= threshold:
            return upper_bound
    # Every finite bucket is below the threshold: the quantile falls in the
    # open-ended +Inf bucket, and the largest finite edge is the tightest
    # lower bound this exposition can support.
    return buckets[-1][0]


class RunState:
    """Mutable tallies shared by the concurrent drivers.

    A small object rather than `nonlocal` closures: three coroutine families
    write to these counters, and a plain attribute makes it obvious at each
    call site which shared thing is being mutated.
    """

    def __init__(self) -> None:
        self.timings: dict[str, list[float]] = defaultdict(list)
        self.errors = 0
        self.ws_connected = 0
        self.ws_rejected = 0
        self.notes: list[str] = []

    def note(self, message: str) -> None:
        """Record a defect in the *run* — as distinct from a slow server."""
        if message not in self.notes:
            self.notes.append(message)


def websocket_base(base_url: str) -> str:
    """`http(s)://host` → `ws(s)://host`, with any trailing slash removed."""
    trimmed = base_url.rstrip("/")
    if trimmed.startswith("https://"):
        return "wss://" + trimmed[len("https://") :]
    if trimmed.startswith("http://"):
        return "ws://" + trimmed[len("http://") :]
    return trimmed


async def hold_stream(uri: str, token: str, duration: float, state: RunState) -> None:
    """Subscribe to one WS stream, confirm it was accepted, and hold it open.

    Every authenticated stream in this app answers a successful handshake with
    `{"status": "connected"}` and a rejected one with `{"error": ...}` followed
    by a 1008 close. Reading that first frame is what makes this a load client
    rather than an open socket: without it a run whose token was refused sleeps
    through the whole window and reports its WS load as delivered.
    """
    import websockets

    try:
        async with websockets.connect(
            uri, additional_headers={"Cookie": f"cb_session={token}"}
        ) as connection:
            raw = await asyncio.wait_for(
                connection.recv(), timeout=WS_HANDSHAKE_TIMEOUT_SECONDS
            )
            try:
                first_frame = json.loads(raw)
            except json.JSONDecodeError:
                first_frame = {}
            if isinstance(first_frame, dict) and first_frame.get("error"):
                state.ws_rejected += 1
                state.errors += 1
                state.note(f"stream {uri} refused the subscription: {first_frame['error']}")
                return
            state.ws_connected += 1
            await asyncio.sleep(duration)
    except TimeoutError:
        state.ws_rejected += 1
        state.errors += 1
        state.note(
            f"stream {uri} sent no handshake frame within "
            f"{WS_HANDSHAKE_TIMEOUT_SECONDS:.0f}s"
        )
    except (OSError, websockets.WebSocketException) as exc:
        state.ws_rejected += 1
        state.errors += 1
        state.note(f"stream {uri} failed: {type(exc).__name__}")


async def browser_user(client: Any, duration: float, state: RunState) -> None:
    """One simulated operator walking the read routes at a human cadence.

    Paced rather than looping flat out, so the recorded p95 is the latency at
    the tier's stated concurrency and not the latency of the server under a
    stress test. Each pass fires the route set concurrently — that is what a
    page load does — then waits out the remainder of the interval.
    """
    import httpx

    deadline = time.monotonic() + duration

    async def hit(route: str) -> None:
        started = time.perf_counter()
        try:
            response = await client.get(route)
            if response.status_code >= 400:
                state.errors += 1
                state.note(f"{route} answered {response.status_code}")
        except httpx.HTTPError as exc:
            state.errors += 1
            state.note(f"{route} raised {type(exc).__name__}")
        state.timings[route].append(time.perf_counter() - started)

    while time.monotonic() < deadline:
        pass_started = time.monotonic()
        await asyncio.gather(*(hit(route) for route in ROUTES))
        remaining = BROWSER_POLL_INTERVAL_SECONDS - (time.monotonic() - pass_started)
        if remaining > 0:
            await asyncio.sleep(min(remaining, max(0.0, deadline - time.monotonic())))


async def scrape_metrics(client: Any, state: RunState) -> str:
    """Prometheus exposition text, or `""` with the failure recorded.

    An empty return is a measurement failure, not an absence of load, and the
    note it leaves is what stops a report full of nulls from reading as a quiet
    success.
    """
    import httpx

    try:
        response = await client.get(METRICS_PATH)
    except httpx.HTTPError as exc:
        state.errors += 1
        state.note(f"metrics scrape raised {type(exc).__name__}; server-side fields are null")
        return ""
    if response.status_code != 200:
        state.errors += 1
        state.note(
            f"metrics scrape returned {response.status_code} from {METRICS_PATH}; "
            "server-side fields are null"
        )
        return ""
    return response.text


async def resolve_git_sha() -> str:
    """The commit under test, from CI's env or from git, else `unknown`."""
    from_env = os.getenv("GITHUB_SHA", "").strip()
    if from_env:
        return from_env
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            "HEAD",
            cwd=ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return "unknown"
    stdout, _ = await process.communicate()
    resolved = stdout.decode().strip()
    return resolved if process.returncode == 0 and resolved else "unknown"


async def drive(args: argparse.Namespace) -> dict[str, Any]:
    """Run one tier's workload and return its result document."""
    import httpx

    tier = TIERS[args.tier]
    state = RunState()
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    ws_base = websocket_base(args.base_url)
    started = time.monotonic()

    stream_tasks = [
        asyncio.create_task(
            hold_stream(
                ws_base + WS_ROUTES[index % len(WS_ROUTES)], args.token, args.duration, state
            )
        )
        for index in range(tier["ws_clients"])
    ]

    async with httpx.AsyncClient(
        base_url=args.base_url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS
    ) as client:
        await asyncio.gather(
            *(browser_user(client, args.duration, state) for _ in range(tier["browser_users"]))
        )
        metrics_text = await scrape_metrics(client, state)

    await asyncio.gather(*stream_tasks)

    if state.ws_connected < tier["ws_clients"]:
        state.note(
            f"only {state.ws_connected} of {tier['ws_clients']} WS clients were accepted; "
            "the stream half of this tier's load was not fully applied"
        )

    topology_p95 = percentile(state.timings[TOPOLOGY_ROUTE], 0.95)
    # Not circuitbreaker_monitor_check_lag_seconds: that gauge only counts
    # checks more than two intervals late, so against the 30s Tier C interval
    # it reads 0.0 for every lag the objective is actually about.
    monitor_lag = gauge_value(metrics_text, "circuitbreaker_monitor_scheduling_lag_seconds")

    report: dict[str, Any] = {
        "schema_version": 1,
        "tier": args.tier,
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": await resolve_git_sha(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "routes": {
            route: {
                "p50": percentile(samples, 0.5),
                "p95": percentile(samples, 0.95),
                "p99": percentile(samples, 0.99),
                "count": len(samples),
            }
            for route, samples in state.timings.items()
        },
        "event_loop_lag_seconds": {
            "latest": gauge_value(metrics_text, "circuitbreaker_event_loop_lag_seconds"),
            "p95": histogram_quantile(
                metrics_text, "circuitbreaker_event_loop_lag_seconds_hist", 0.95
            ),
            "p99": histogram_quantile(
                metrics_text, "circuitbreaker_event_loop_lag_seconds_hist", 0.99
            ),
        },
        "monitor_scheduling_lag_seconds": monitor_lag,
        "topology_load_p95_seconds": topology_p95,
        "db_pool": {
            "size": gauge_value(metrics_text, "circuitbreaker_db_pool_size"),
            "checked_out": gauge_value(metrics_text, "circuitbreaker_db_pool_checked_out"),
            "checked_in": gauge_value(metrics_text, "circuitbreaker_db_pool_checked_in"),
            "overflow": gauge_value(metrics_text, "circuitbreaker_db_pool_overflow"),
            "timeouts_total": gauge_value(
                metrics_text, "circuitbreaker_db_pool_timeouts_total"
            ),
        },
        "ws_clients": {
            "requested": tier["ws_clients"],
            "connected": state.ws_connected,
            "rejected": state.ws_rejected,
        },
        "errors": state.errors,
        "retries": 0,
        "targets": evaluate_targets(args.tier, topology_p95, monitor_lag),
        "unmeasured": list(UNMEASURED),
        # Kept apart from `unmeasured`: that list is the axes this harness was
        # never built to cover, which is a property of the design. These are
        # things that went wrong in *this run* — a refused stream, a 404 scrape —
        # and a reader has to be able to tell a deliberate gap from a broken run.
        "notes": state.notes,
    }
    assert RESULT_FIELDS == report.keys(), (
        f"result document does not match the declared contract: "
        f"{RESULT_FIELDS ^ report.keys()}"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=sorted(TIERS), required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.getenv("CB_LOADGEN_TOKEN", ""))
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = asyncio.run(drive(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
