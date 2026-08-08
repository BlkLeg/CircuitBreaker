"""The scan-type vocabulary and where each type may execute (Slice 4 §3, D-6).

Discovery gained an execution location before it had a vocabulary: `scan_types`
was an unvalidated `list[str]` on every request schema and execution did bare
membership tests. With an agent as a second executor that is no longer enough —
plan §3 requires that server-only types (`nmap`, `arp`, `docker`, OPNsense …)
are never dispatched to an agent, and there is no way to express that rule
without naming the set each location can run.

Validation is deliberately **write-only**. Rows written before this module
existed may hold any string at all, and a read path that validated them would
turn a stale profile into a 500 on `GET`. Nothing here is called from a
response model or a job-execution read.
"""

from __future__ import annotations

from collections.abc import Iterable

# Everything the in-process server scanner knows how to run today. Derived from
# the membership tests in `services/discovery_service.py` and the job rows the
# prober, LLDP and Proxmox services mint, so this set is a description of the
# existing product rather than a new restriction on it.
SERVER_SCAN_TYPES = frozenset(
    {
        "nmap",
        "arp",
        "snmp",
        "http",
        "docker",
        "opnsense",
        "deep_dive",
        "proxmox",
        "lldp",
    }
)

# What an agent may be asked for. Deliberately one focused type: an agent
# performs bounded connect-based discovery on its own segment and bundles no
# scanner, so there is nothing else it could honestly offer.
AGENT_SCAN_TYPES = frozenset({"agent_connect"})

ALL_SCAN_TYPES = SERVER_SCAN_TYPES | AGENT_SCAN_TYPES


def validate_scan_types(
    types: Iterable[str] | None,
    *,
    scan_agent_id: int | None,
) -> list[str]:
    """Return the normalized scan types, or raise `ValueError` with the reason.

    `scan_agent_id` is the execution location: `None` is the Circuit Breaker
    server, an id is that agent. The two vocabularies are disjoint, so the
    location fully determines which types are legal — which is why this cannot
    be a plain per-field validator on `scan_types`.
    """
    if types is None:
        return []

    normalized: list[str] = []
    for entry in types:
        if not isinstance(entry, str):
            raise ValueError(f"Invalid scan type {entry!r}: expected a string")
        if entry not in ALL_SCAN_TYPES:
            raise ValueError(
                f"Unknown scan type {entry!r}. Known types: {', '.join(sorted(ALL_SCAN_TYPES))}"
            )
        # Collapse duplicates in first-seen order: `discovery_service` compares
        # the list by equality in places (`scan_types == ["docker"]`), so a
        # repeated entry would silently change how a job executes.
        if entry not in normalized:
            normalized.append(entry)

    if scan_agent_id is None:
        agent_only = [t for t in normalized if t in AGENT_SCAN_TYPES]
        if agent_only:
            raise ValueError(
                f"Scan type(s) {', '.join(agent_only)} require an agent execution "
                "location; set scan_agent_id."
            )
        return normalized

    server_only = [t for t in normalized if t in SERVER_SCAN_TYPES]
    if server_only:
        raise ValueError(
            f"Scan type(s) {', '.join(server_only)} cannot run on an agent. "
            f"Agent scan types: {', '.join(sorted(AGENT_SCAN_TYPES))}."
        )
    if not normalized:
        # An empty list is a legal no-op for the server, but an agent dispatch
        # with nothing to run would occupy a lease and a concurrency slot to
        # produce a summary and no findings.
        raise ValueError(
            f"An agent scan must request at least one of: {', '.join(sorted(AGENT_SCAN_TYPES))}."
        )
    return normalized
