"""Stable workload and result contracts shared by the load generator and tests.

The tier shapes mirror route §5's workload matrix exactly; `tests/build/
test_phase2_baseline_contract.py` pins them against that table so a tier cannot
drift away from the document that defines what "Tier C" means.
"""

from __future__ import annotations

from typing import Any

#: Route §5 workload matrix. `browser_users` and `ws_clients` are the two halves
#: of that table's "Browser users / WS clients" column: a browser user is a
#: paced HTTP client walking the read routes, a WS client is a held stream
#: subscription. They are separate numbers because the table separates them —
#: a browser tab holds more than one stream.
TIERS: dict[str, dict[str, Any]] = {
    "A": {
        "name": "Starter",
        "monitors": 10,
        "interval_seconds": 60,
        "browser_users": 1,
        "ws_clients": 2,
        "topology_entities": 25,
    },
    "B": {
        "name": "Enthusiast",
        "monitors": 50,
        "interval_seconds": 30,
        "browser_users": 2,
        "ws_clients": 5,
        "topology_entities": 150,
    },
    "C": {
        "name": "Advanced",
        "monitors": 200,
        "interval_seconds": 30,
        "browser_users": 5,
        "ws_clients": 10,
        "topology_entities": 500,
    },
}

#: How long a simulated browser user waits between passes over the read routes.
#: The number matters: an unpaced loop measures the server at saturation, which
#: answers "how fast can it go when hammered" and not route §5's question, which
#: is what latency a Tier-C operator sees. Five seconds is roughly a person
#: moving between pages, and it is slow enough that the two defensible targets
#: are measured under the tier's stated load rather than under a stress test.
BROWSER_POLL_INTERVAL_SECONDS = 5.0

#: Every key a result document carries. `run.py` asserts its report matches this
#: set exactly, so a field cannot be added to the JSON without being declared
#: here — and a consumer reading a field that was silently dropped fails loudly.
RESULT_FIELDS = {
    "schema_version",
    "tier",
    "timestamp",
    "git_sha",
    "duration_seconds",
    "routes",
    "event_loop_lag_seconds",
    "monitor_scheduling_lag_seconds",
    "topology_load_p95_seconds",
    "db_pool",
    "ws_clients",
    "errors",
    "retries",
    "targets",
    "unmeasured",
    "notes",
}

#: Axes this harness does not measure, named in every result rather than left
#: to be inferred from their absence (plan ruling R-B). Synthetic Noise-protocol
#: agents are a from-scratch cryptographic client build; until that exists, no
#: baseline here says anything about the agent-ingest path.
UNMEASURED = [
    "synthetic_agents",
    "agent_telemetry_rate",
    "publish_to_websocket_latency",
]

#: Route §5's two defensible targets. Both are Tier C claims — topology load is
#: specified "at 500 entities" and monitor lag "at Tier C" — so a Tier A or B
#: run reports them as not applicable rather than as passing. A nightly job that
#: never runs Tier C therefore evidences neither, which is why the workflow runs
#: all three.
TOPOLOGY_P95_TARGET_SECONDS = 2.0
TOPOLOGY_TARGET_ENTITY_COUNT = 500
MONITOR_LAG_TARGET_TIER = "C"


def evaluate_targets(
    tier: str, topology_p95: float | None, monitor_lag: float | None
) -> dict[str, dict[str, Any]]:
    """Score the two route §5 targets for one run.

    Each target reports `applicable` (does this tier make the claim at all) and
    `passed`, which is `None` when the target does not apply *or* when the run
    failed to measure the number. Those two cases are deliberately not collapsed
    into `False`: a missing measurement is not a failing one, and recording it as
    a failure would make a broken harness look like a regressed product.
    """
    cfg = TIERS[tier]
    topology_applicable = cfg["topology_entities"] == TOPOLOGY_TARGET_ENTITY_COUNT
    monitor_applicable = tier == MONITOR_LAG_TARGET_TIER
    return {
        "topology_load_p95_under_2s_at_500_entities": {
            "applicable": topology_applicable,
            "passed": (
                topology_p95 < TOPOLOGY_P95_TARGET_SECONDS
                if topology_applicable and topology_p95 is not None
                else None
            ),
            "measured": topology_p95,
        },
        "monitor_lag_under_shortest_interval_at_tier_c": {
            "applicable": monitor_applicable,
            "passed": (
                monitor_lag < cfg["interval_seconds"]
                if monitor_applicable and monitor_lag is not None
                else None
            ),
            "measured": monitor_lag,
        },
    }
