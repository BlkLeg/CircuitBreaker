"""Docker E2E: the full-system cbi-agent release gate — ONE journey, ONE stack.

`plans/2026-08-04-cbi-agent-e2e-cohesion-review.md`'s "Full-System E2E Release Gate"
section is the spec for this file: its Topology, its 17-step Journey, and its
"Required assertions" list. `plans/2026-08-09-cbi-agent-finalization.md` item 4 is
why it exists.

**What this test adds that `test_agent_e2e.py` structurally cannot.** That file
holds twelve tests and every individual capability is covered by one of them. Each
one, though, stands up its own stack (`_up_server()`) and tears it down again, so
what none of them can observe is that the four slices' states COMPOSE: that a
device agent discovery found and an operator imported can then be monitored from
the agent's own vantage, that the resulting monitor survives the same WAN outage
the telemetry spool does, that a restart of either end reconciles presence,
profiles, schedules and grants while all four slices' state is live at once, and
that disabling a capability mid-scan and then revoking the agent is one continuous
act rather than two independent demonstrations. The single-stack continuity IS the
deliverable. Everything below runs against one `_up_server()` and one `_down()`.

**The central hole this was designed around — journey step 8.** Slice 3's
`test_remote_probe_assignment_execution_and_unavailability` does create ICMP, TCP,
HTTP and DNS monitors with `probe_agent_id`, but against a **hardcoded fixture IP**
(`_PROBE_TARGET_IP`). No test in the suite creates a monitor against a Hardware row
that agent discovery FOUND and an operator IMPORT created. This one makes that
join, in one continuous chain with no literal in the middle of it:

    discovery -> finding -> review queue -> import -> Hardware row
      -> `target_type="hardware", target_id=<that row>`, `probe_agent_id=<that agent>`
      -> monitor state, history, retry, uptime and the alert transitions

Every one of the four monitors takes its address from `hardware["ip_address"]` read
back off the imported row, so a regression that broke the import would break the
monitors rather than leaving them quietly passing against a constant.

**Everything this file leans on, it reuses.** Every helper comes from
`test_agent_e2e` — the harness is that module, and importing it rather than
re-implementing it is what keeps a topology change (a renamed network, a moved
spool path, a new agent service) a one-place edit. Only helpers with no equivalent
there are defined here, and each says why.

**Two mechanisms this gate must respect or it produces false results.**

  (a) `hostinfo.Collect()` runs once per link connection (`internal/link/link.go`),
      so anything about the agent's own network facts — a new subnet, a changed
      address — reaches the server only on the agent's NEXT `hello`. The trigger is
      `docker compose restart cb-agent`, and never `up --force-recreate`: the
      runtime network attachment (and the `--ip` of step 15) lives on the
      container, and a recreate silently undoes the thing under test.

  (b) Every "the backend cannot reach this" assertion is preceded by a POSITIVE
      CONTROL. A bare `assert returncode != 0` is satisfied just as well by a
      missing binary, a dropped capability or a typo as by an absent route, and the
      resulting test passes forever while proving nothing. The pattern is
      `test_e2e_harness_topology_is_pinned_and_two_agents_stay_isolated`'s and it is
      reused verbatim: the backend pings cb-agent's own agent-net address, and `nc`
      hits the backend's own 8443, before any negative probe runs. The same shape is
      applied to two negatives that test has no equivalent of — the agent's own
      `/proc/net/tcp` (no listener) and the agent image's missing scanner binaries
      (`command -v` is demonstrated to work first, against `cb-agent` itself).

**Journey step order, and the one deliberate deviation.** The blocks below map 1:1
onto the spec's 17 steps and are labelled with their numbers. They run in that
order with exactly one swap: **step 17 (upgrade) executes before step 16 (disable
discovery mid-scan, then revoke)**, because revocation is terminal by construction
— `api/ws_agents.py`'s `link_stream` refuses any agent whose status is not
`active`, and `api/agents.py`'s `post_revoke` closes the socket, cancels the probe
runs and closes the discovery dispatches — so an update dispatched to a revoked
agent could never be delivered and step 17 after step 16 would be unrunnable rather
than merely awkward. The blocks keep their spec numbering; only the execution order
differs, and both blocks say so.

**Where a step is not fully expressible against this harness, its block still
exists, is marked, and asserts the part that is.** There is exactly one:

  * **Step 17's forced-rollback half.** The successful upgrade is exercised in full
    here (build, fetch, verify, swap, re-exec, reconnect, `version_changed`, and —
    the property the rollback case shares and the one this gate is really about —
    enrollment and all four slices' historical data surviving a version change).
    The forced rollback is NOT re-implemented, for two independent reasons stated
    at the block. It remains owned by
    `test_agent_e2e.py::test_agent_update_success_and_forced_rollback`, which is
    finalization item 1's own subject.

  * **The "malformed and oversized frames" half of the frame-rejection required
    assertion.** See the block for step 16: the only frame-injection point this
    harness has is the agent's own spool, and the agent re-encodes only frames it
    produced itself, so a malformed or oversized frame cannot be put on the wire
    without minting a Noise session the harness has no mechanism for. What IS
    asserted there is the half that is drivable end to end (stale and
    out-of-grant frames, refused per-frame by every capability handler) plus the
    negative that the agent emitted no malformed frame of its own across the whole
    journey. The unfalsifiable half is delegated to the named unit tests that do
    inject bytes directly.

**Budget.** This is slow by construction — one stack carries the whole journey, and
several steps pay real protocol constants (`internal/link`'s 60s steady-state read
deadline, the 20s heartbeat interval, the monitors' 30s poll, discovery's bootstrap
jitter). Expect 30-40 minutes. Every timeout below is a `_wait_until` ceiling, not
an expectation: a run that gets there sooner pays nothing. No number is bare — each
either comes from an imported harness budget that carries its own derivation, or is
derived at its definition from a protocol constant, an interval or a backoff
progression.

Run explicitly (from this directory), with a timeout that suits it:

    pytest test_agent_release_gate.py -v -m e2e --no-cov -p no:randomly
"""

from __future__ import annotations

import ipaddress
import json
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from itertools import pairwise

import httpx
import pytest

from test_agent_e2e import (
    _AGENT_NET,
    _AGENT_NET_CIDR,
    _AGENT_NET_MOVED_IP,
    _AGENT_SCAN_TYPE,
    _AGENT_SERVICE,
    _BACKEND_HTTPS_PORT,
    _CANCEL_DISCOVERY_CONFIG,
    _DISCOVERY_BOOTSTRAP_BUDGET_S,
    _INITIAL_SCAN_BUDGET_S,
    _LATE_FINDING_BUDGET_S,
    _PARTITION_DETECT_BUDGET_S,
    _PARTITION_DETECT_S,
    _PROBE_FIRST_RESULT_BUDGET_S,
    _PROBE_INTERVAL_S,
    _PROBE_NET,
    _PROBE_NET_CIDR,
    _PROBE_RECONNECT_BUDGET_S,
    _PROBE_TARGET_CLOSED_PORT,
    _PROBE_TARGET_HTTP_PORT,
    _PROBE_TARGET_IP,
    _PROBE_TARGET_NAME,
    _PROBE_TARGET_NEW_IP,
    _PROBE_TARGET_NEW_SERVICE,
    _PROBE_TARGET_SERVICE,
    _PROBE_UNAVAILABLE_BUDGET_S,
    _RECONNECT_BUDGET_S,
    _RECURRING_SCAN_BUDGET_S,
    _SPOOL_DRAIN_BUDGET_S,
    _TOPOLOGY_PROPAGATION_BUDGET_S,
    COMPOSE,
    E2E_DIR,
    _agent_events,
    _agent_host_samples,
    _agent_network_name,
    _agent_route_networks,
    _agent_scan_jobs,
    _agent_status,
    _agent_telemetry,
    _agents,
    _AgentStreamListener,
    _all_profiles,
    _assert_backend_cannot_reach,
    _automatic_scope,
    _backend_sh,
    _bootstrap_admin,
    _capability_violations,
    _change_agent_address,
    _container_ipv4,
    _create_monitor,
    _cut_agent_network,
    _device_key,
    _discovery_profiles,
    _discovery_status,
    _discovery_view,
    _DiscoveryStreamListener,
    _down,
    _enroll_agent,
    _enrolled_event_ids,
    _fetch_install_material,
    _hardware_row,
    _hardware_with_ip,
    _in_any,
    _job_dispatch_state,
    _job_results,
    _monitor,
    _monitor_events,
    _monitor_samples,
    _network_subnet,
    _new_client,
    _parse_ts,
    _probe_eligible_row,
    _probe_runs,
    _put_local_discovery,
    _readiness_states,
    _rename_hardware,
    _result_provenance,
    _review_queue,
    _run_profile_now,
    _scan_job,
    _scan_jobs,
    _session_cookie,
    _set_local_discovery_enabled,
    _spool_frames,
    _spool_fully_delivered,
    _spool_head,
    _system_profile_for,
    _unfinished_agent_jobs,
    _up_fixture_target,
    _up_server,
    _wait_until,
    _wait_until_and_return,
    _write_agent_toml,
)

# ─────────────────────────────────────────────────────────────────────────
# Budgets and constants this gate needs and the harness does not already have
# ─────────────────────────────────────────────────────────────────────────
#
# Everything else is imported above, budgets included, precisely so that a value
# derived once in `test_agent_e2e.py` (the discovery bootstrap window, the initial
# scan window, the reconnect window, the spool drain window) has one definition and
# one derivation. Only numbers with no equivalent there are defined here, and each
# says where it comes from.

# The cadence the SERVER's own approval defaults grant — `_enroll_agent` asserts
# `host_telemetry.config.interval_s == 30` on the approve response, and nothing in
# this test ever changes it, because "no manual agent-side configuration" is one of
# the required assertions and a cadence edit is exactly the kind of setup the claim
# forbids. Restated here because step 4's budget is derived from it and a bare 30
# in a timeout expression would say nothing.
_DEFAULT_TELEMETRY_INTERVAL_S = 30

# Step 4's "within the promised interval". The promised interval is the grant's
# own 30s. Two of them, plus the one-time path that has to complete before the
# first sample can exist at all (link connect, Noise IK handshake, hello/hello.ack,
# `applyHostConfig` constructing the collector, first collection, dispatch_frame,
# AgentHostSample insert). 120s is that with room for scheduling noise, and it is a
# ceiling: a first sample that lands in 35s costs 35s.
_FIRST_SAMPLE_BUDGET_S = _DEFAULT_TELEMETRY_INTERVAL_S * 2 + 60

# How long collection continues INSIDE the WAN cut, measured from the moment the
# agent has observably noticed the partition (`link_state == "disconnected"`), not
# from the cut itself. Frames written before that instant go into a black hole —
# a detached interface produces no FIN and no RST, so the writes succeed into a
# kernel buffer that never drains (see `_cut_agent_network`'s docstring and F-5) —
# so only samples collected AFTER detection are spooled and therefore only they can
# be asserted to arrive. Four 30s intervals: enough that the window provably
# contains more than one sample, so "the backlog was delivered with its original
# collected_at" is a statement about a set rather than about one row.
_WAN_SPOOL_S = _DEFAULT_TELEMETRY_INTERVAL_S * 4

# Step 17's successful upgrade, end to end: the server signs and serves the pinned
# binary, the agent downloads it over the same outbound-only link, verifies the
# sha256, swaps it, re-execs, reconnects, completes a `hello.ack` and reports the
# new version in `status.json`. `test_agent_update_success_and_forced_rollback`
# allows 60s for the version flip on an otherwise idle stack; this one carries four
# slices' worth of live work (a 30s telemetry cadence, five monitors polling every
# 30s, a discovery schedule) on the same container, so the same path is given three
# times that.
_UPDATE_BUDGET_S = 180

# One server-executed nmap scan of a single /32, from "run now" to a terminal job
# status. A single host is seconds of nmap; the budget is dominated by the
# scheduler picking the job up and by the mono container's own load, not by the
# scan. Same order as the harness's other job budgets and well under
# `_INITIAL_SCAN_BUDGET_S`, which has to cover two whole /24 sweeps.
_SERVER_SCAN_BUDGET_S = 300

# How long the journey watches for silence after the revoke. Three full collection
# intervals: the agent is provably collecting right up to the revoke (host
# telemetry is re-enabled and a fresh sample is observed first), so if a revoked
# agent could still deliver anything, three intervals is three chances for it to.
_POST_REVOKE_SILENCE_S = _DEFAULT_TELEMETRY_INTERVAL_S * 3

# `internal/frame/frame.go`'s `controlFrameTypes`, restated. The spool exists for
# host DATA, and link-protocol control traffic plus the heartbeat liveness signal
# must never reach its write path (spec §4.4). This is a deny-list on the Go side
# on purpose — every type NOT named classifies as a data frame, so a future slice's
# data frame needs no code change — and it is restated rather than derived here for
# the same reason `frame_test.go` keeps a hand-written literal: a list derived from
# the thing under test asserts `m` against `m` and proves nothing.
_CONTROL_FRAME_TYPES = frozenset(
    {
        "hello",
        "heartbeat",
        "capability.readiness",
        "uninstall",
        "hello.ack",
        "capabilities.set",
        "probe.assign",
        "probe.cancel",
        "discovery.request",
        "discovery.cancel",
        "key.rotate",
        "update",
        "disconnect",
        "ping",
        "transport.rekey",
    }
)

# `services/agent_link.py`'s `CAPABILITY_FOR_TYPE`, which is the whole of "all
# capability handlers" as far as inbound data frames are concerned: one wire type
# per capability, each gated by `dispatch_frame` on that capability's grant. Step
# 16 withdraws all three while the agent is deaf and then requires one audited
# refusal per delivered frame of each type.
_CAPABILITY_FRAME_TYPES = {
    "host_telemetry": "telemetry.host",
    "remote_probe": "probe.result",
    "local_discovery": "discovery.finding",
}

# Binaries the remote host must NOT need for any of this to work. The slice's
# claim is "no scanner installed": the agent performs bounded connect-based
# discovery from its own segment (`AGENT_SCAN_TYPES` is the single
# `agent_connect`), and `e2e/Dockerfile` installs ca-certificates and nothing
# else. `ip` is in the list because `_agent_route_networks` reads /proc/net/route
# precisely BECAUSE iproute2 is absent — if it ever appears, that helper's premise
# has quietly changed too.
_FORBIDDEN_AGENT_TOOLS = ("nmap", "arp-scan", "masscan", "snmpwalk", "ip", "tcpdump")

# The name an operator gives the imported device. Distinct from the harness's own
# `_OPERATOR_HARDWARE_NAME` because this journey renames for a different reason —
# to prove the four monitors follow the Hardware ROW rather than a name or a
# literal — and sharing the constant would make the two tests' intents look like
# one.
# How long a monitor may hold an in-flight probe run before the reconciliation
# pass writes it off. The slow monitor's check timeout is 100s and
# probe_reconcile expires a run whose deadline passed more than
# RESULT_TIMEOUT_GRACE_S (= agent_probe.LATE_RESULT_GRACE, 30s) ago; the rest is
# room for the reconcile tick and for scheduling noise on a loaded host.
# /proc/net/tcp6 renders addresses as four little-endian 32-bit words, so ::1
# and the v4-mapped 127.0.0.1 do not look like their textual forms.
_LOOPBACK_V6_HEX = frozenset(
    {"00000000000000000000000001000000", "0000000000000000FFFF00000100007F"}
)

# How long to allow for the partitioned agent to finish the in-flight slow check
# and spool its result. The check's own timeout is 100s (the monitor's config,
# against a target that sleeps longer still), so the result is framed at ~100s
# after dispatch; the rest is the collection interval for the host sample that
# has to be there too, plus scheduling noise.
_LATE_RESULT_SPOOL_BUDGET_S = 240

_PROBE_LEASE_EXPIRY_BUDGET_S = 240

_GATE_HARDWARE_NAME = "release-gate-imported-device"


# ─────────────────────────────────────────────────────────────────────────
# Helpers with no equivalent in test_agent_e2e.py
# ─────────────────────────────────────────────────────────────────────────


def _agent_online(client: httpx.Client, agent_id: int) -> bool:
    """The server's live presence view of one agent.

    `GET /agents/presence` rather than `GET /agents/{id}` because presence is a
    Redis key with a 60s TTL refreshed on every heartbeat
    (`agent_registry.mark_presence_connected`), while `status` is the enrollment
    lifecycle column and stays `active` through any outage. Step 11 is about the
    first of those two and would be unfalsifiable against the second.
    """
    presence = client.get("/api/v1/agents/presence").json()
    return any(row["agent_id"] == agent_id and row["online"] for row in presence)


def _agent_believes(expected: dict[str, bool]) -> bool:
    """Does the AGENT's own status.json report exactly these grant values?

    Compared key by key rather than as a whole-dict equality: `internal/status`'s
    `Status.Grants` is a map of every capability the daemon knows about, so an
    equality would break the day a fifth capability is added — for a reason that
    has nothing to do with the three this asserts. Bare booleans, because that is
    what the status file carries (the structured `{enabled, config}` shape is the
    SERVER's view, and `_agent_capabilities` is how this file asks for that one).

    Read from the agent rather than from the server on purpose: every use below is
    asking what the agent BELIEVES, which during a partition is a different
    question from what the database says — and the difference is the whole of
    step 16's argument.
    """
    grants = _agent_status().get("grants", {})
    return {name: grants.get(name) for name in expected} == expected


def _agent_capabilities(client: httpx.Client, agent_id: int) -> dict:
    """The canonical structured capability grant map for one agent.

    `{name: {enabled, config}}` with server-normalized config — the "Canonical
    capability wire shape" Global Constraint — which is what makes a whole-map
    equality assertion meaningful after a restart: a grant that came back with a
    silently defaulted config would compare unequal rather than merely enabled.
    """
    return client.get(f"/api/v1/agents/{agent_id}").json()["capabilities"]


def _set_capability_enabled(
    client: httpx.Client, headers: dict, agent_id: int, capability: str, enabled: bool
) -> dict:
    """Turn one capability on or off with a bare boolean, as the Agent Detail
    toggle does.

    `_set_local_discovery_enabled` exists in the harness for `local_discovery`
    specifically; this is the same call for the other two. A bare boolean rather
    than an `{enabled, config}` object on purpose: `set_capability_grants` keeps
    the stored config either way, so re-enabling restores the same grant instead
    of resetting settings — which is what makes step 16's re-enable of
    `host_telemetry` a resume rather than a reconfiguration.
    """
    resp = client.put(
        f"/api/v1/agents/{agent_id}/capabilities",
        json={"capabilities": {capability: enabled}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["capabilities"][capability]["enabled"] is enabled, body["capabilities"]
    return body


def _tcp_sockets(service: str) -> list[dict]:
    """Every TCP socket in one container's own network namespace, from
    /proc/net/tcp and /proc/net/tcp6.

    Read from /proc rather than with `ss`/`netstat` for the same reason
    `_agent_route_networks` reads /proc/net/route: the agent image carries neither,
    and keeping it that way is part of what is being claimed. This is the direct
    form of "the agent never listens on a remote-subnet port" — `nc` from the
    backend proves nothing is REACHABLE, which a firewall could also explain, while
    this proves nothing is BOUND, which nothing else could.

    Both address columns are hex; the IPv4 form is little-endian, which
    `to_bytes(4, "little")` undoes. `st` is the TCP state: 0A is LISTEN and 01 is
    ESTABLISHED (net/tcp_states.h). IPv6 rows are returned with their remote
    address left as the raw hex — nothing here needs to read it, and the states and
    ports are what the assertions are about.
    """
    raw = subprocess.run(
        [
            *COMPOSE,
            "exec",
            "-T",
            service,
            "sh",
            "-c",
            "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null || true",
        ],
        cwd=E2E_DIR,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    sockets: list[dict] = []
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 4 or not fields[0].endswith(":"):
            continue  # the header line, or a truncated read
        local, remote, state = fields[1], fields[2], fields[3]
        if ":" not in local or ":" not in remote:
            continue
        local_hex, local_port = local.rsplit(":", 1)
        remote_hex, remote_port = remote.rsplit(":", 1)
        is_v4 = len(local_hex) == 8
        sockets.append(
            {
                "state": state.upper(),
                "family": 4 if is_v4 else 6,
                "local_port": int(local_port, 16),
                "remote_port": int(remote_port, 16),
                "local_ip": (
                    str(ipaddress.IPv4Address(int(local_hex, 16).to_bytes(4, "little")))
                    if is_v4
                    else local_hex
                ),
                "remote_ip": (
                    str(ipaddress.IPv4Address(int(remote_hex, 16).to_bytes(4, "little")))
                    if is_v4
                    else remote_hex
                ),
            }
        )
    return sockets


def _agent_shell(command: str) -> subprocess.CompletedProcess:
    """A shell command inside the agent container. Deliberately not `check=True`:
    the callers below are asking whether something FAILS (a scanner binary that is
    not there), which is the whole point."""
    return subprocess.run(
        [*COMPOSE, "exec", "-T", _AGENT_SERVICE, "sh", "-c", command],
        cwd=E2E_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def _routable_listeners(service: str) -> list[dict]:
    """Every LISTENING TCP socket in a container's namespace that something else
    could actually connect to — i.e. every listener except the loopback ones.

    The exclusion is about Docker, not about the agent. The daemon runs its
    embedded DNS resolver inside EVERY container's network namespace, bound to
    127.0.0.11 on a random high TCP port. Verified on this host: a bare
    `docker run -d alpine:3.20 sleep 60`, with no application in it at all, shows
    exactly one LISTEN row — `0B00007F:9953`, which decodes to 127.0.0.11:39251.
    Counting that as an agent listener made this gate fail on its first run
    against a perfectly compliant agent.

    Excluding it costs the contract nothing. "Capabilities never open listeners
    and never require inbound REACHABILITY" is about sockets something can reach;
    a socket bound inside 127.0.0.0/8 is unreachable from any other namespace by
    construction, because the kernel will not route to another netns's loopback.
    A listener on the agent's real interface, on 0.0.0.0 or on ::, is still
    returned here, and that is the only kind that could ever accept a remote
    connection.

    Factored out because this question is asked twice — once at step 2, before
    anything has run, and once at the end, over everything the journey did. The
    two answers have to be computed the same way or the second is a different
    assertion wearing the first one's message.
    """
    listeners = []
    for row in _tcp_sockets(service):
        if row["state"] != "0A":
            continue
        if row["family"] == 4:
            if ipaddress.IPv4Address(row["local_ip"]).is_loopback:
                continue
        elif row["local_ip"].upper() in _LOOPBACK_V6_HEX:
            continue
        listeners.append(row)
    return listeners


def _backend_container() -> str:
    container = subprocess.run(
        [*COMPOSE, "ps", "-q", "circuitbreaker"],
        cwd=E2E_DIR,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert container, "the circuitbreaker container is not running"
    return container


def _hardware_identity(client: httpx.Client, hardware_id: int) -> dict:
    """The columns of an imported Hardware row that a restart, an address change or
    an upgrade must not touch.

    A SUBSET rather than the whole `Hardware` read model, and the exclusions are
    the point: `telemetry_status`, `telemetry_last_polled`, `status` and
    `updated_at` are written by background work (the scheduler's own reachability
    sweep touches `status` for a host the SERVER cannot reach, which is every host
    on the remote subnet), so a whole-row equality would fail for reasons that have
    nothing to do with the claim. What is left is identity and provenance —
    including `source_scan_result_id`, the pointer back to the agent's own finding
    — which is exactly what "historical data was not lost" is about.
    """
    row = _hardware_row(client, hardware_id)
    return {
        key: row.get(key)
        for key in (
            "id",
            "name",
            "ip_address",
            "mac_address",
            "source",
            "source_scan_result_id",
            "discovered_at",
            "created_at",
            "last_seen",
        )
    }


def _topology_nodes(client: httpx.Client) -> list[str]:
    """Every node id in the default topology graph, in the order the graph builds
    them.

    A list rather than a set, deliberately: "no duplicate topology nodes" is one of
    the spec's required assertions, and a set cannot express it. `GET
    /graph/topology`'s default `include` carries hardware, so an imported Hardware
    row is placed as `hw-{id}` (api/graph.py) — which is what step 7's "topology
    placement" means for a device that arrived through discovery.
    """
    resp = client.get("/api/v1/graph/topology")
    resp.raise_for_status()
    return [node["id"] for node in resp.json().get("nodes", [])]


def _uptime(client: httpx.Client, monitor_id: int) -> dict:
    resp = client.get(f"/api/v1/monitors/{monitor_id}/uptime")
    resp.raise_for_status()
    return resp.json()


def _transitions(client: httpx.Client, monitor_id: int) -> list[dict]:
    """One monitor's target-state transitions, OLDEST FIRST.

    Two transformations, both load-bearing. `execution` events are dropped: §7 is
    explicit that they describe the VANTAGE and never the target, and folding the
    two together would make "the agent's outage changed the target's state" look
    true. And the list is reversed, because `/monitors/{id}/events` returns newest
    first — an alert-ordering assertion written against that order reads backwards
    and is very easy to get accidentally right.
    """
    events = [e for e in _monitor_events(client, monitor_id) if e["event_type"] != "execution"]
    return list(reversed(events))


def _create_server_profile(client: httpx.Client, headers: dict, *, name: str, cidr: str) -> dict:
    """An ordinary, operator-created, SERVER-executed discovery profile.

    `scan_agent_id` is omitted, which is the pre-Slice-4 shape every profile in
    every existing installation has (`DiscoveryProfileCreate.scan_agent_id`'s own
    comment says so), and `scan_types` stays at the schema default `["nmap"]` —
    nmap is present in the mono image (Dockerfile.mono), so this exercises the real
    server scanner rather than a stub. It exists to satisfy the required assertion
    that existing server-side discovery paths still work unchanged while an agent
    is doing its own discovery beside them.
    """
    resp = client.post(
        "/api/v1/discovery/profiles",
        json={"name": name, "cidr": cidr, "enabled": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    profile = resp.json()
    assert profile["scan_agent_id"] is None, profile
    return profile


def _assert_positive_controls(agent_ip: str) -> None:
    """The two controls every negative in this file sits behind.

    Reused verbatim from `test_e2e_harness_topology_is_pinned_and_two_agents_stay_isolated`
    because it is the same claim: the backend container drops all caps and adds
    NET_RAW back (repo-root docker-compose.yml), so ICMP is SUPPOSED to work from
    it, demonstrated against cb-agent's own agent-net address — a network the
    backend genuinely is on. `nc` is demonstrated against the backend's own HTTPS
    listener, the one open TCP port it can reach at all. Without both, a loop of
    `assert returncode != 0` is satisfied by a missing binary or a dropped
    capability, and the whole isolation argument evaporates without a single test
    turning red.
    """
    reachable = _backend_sh(f"ping -c 2 -W 2 {agent_ip}")
    assert reachable.returncode == 0, (
        "the backend cannot ICMP a host on a network it IS attached to, so every "
        "'the backend could not reach it' assertion in this test would hold even with "
        f"no isolation at all: {reachable.stdout!r} {reachable.stderr!r}"
    )
    listening = _backend_sh(f"nc -z -w 3 127.0.0.1 {_BACKEND_HTTPS_PORT}")
    assert listening.returncode == 0, (
        "`nc` cannot connect to the backend's own open port, so the TCP half of every "
        f"isolation check below proves nothing: {listening.stdout!r} {listening.stderr!r}"
    )


def _assert_spool_holds_only_data_frames(frames: list[dict]) -> None:
    """"Control/assignment frames are never spooled" (Shared Contracts, Delivery
    semantics), asserted against the actual on-disk queue rather than against the
    Go deny-list that is supposed to produce it.

    `internal/frame`'s `IsDataFrame` is unit-tested, but a wiring mistake in
    `internal/link` — spooling before classifying — would leave that test green and
    put a `capability.readiness` (agent-emitted, and the one with real spooling
    risk behind it) or a heartbeat into the queue. This is the end-to-end check
    that it does not.
    """
    spooled_types = {frame.get("type") for frame in frames}
    leaked = sorted(spooled_types & _CONTROL_FRAME_TYPES)
    assert not leaked, (
        f"control frame type(s) {leaked} are on the agent's outbound spool. The spool "
        "buffers host DATA through an outage; link-protocol control traffic and the "
        "heartbeat liveness signal must never reach its write path (spec §4.4, "
        f"internal/frame's controlFrameTypes). On disk: {sorted(t for t in spooled_types if t)}"
    )


def _spooled_of_type(frames: list[dict], frame_type: str) -> list[dict]:
    return [frame for frame in frames if frame.get("type") == frame_type]


def _undelivered_frames() -> list[dict]:
    """The frames on the agent's spool that it has NOT yet delivered and committed.

    `queue.jsonl` is append-only until compaction (512 entries), so a frame that was
    delivered during an EARLIER outage in this journey is still sitting in the file
    as a consumed prefix — and `queue.head` is how many of those leading lines are
    done with. Counting types over the whole file would therefore count step 10's
    already-delivered backlog again in step 16, and the per-frame refusal assertion
    there would demand more audited rejections than there were frames to reject.
    Slicing at the head marker is what makes "these are the frames that are about to
    be delivered" true rather than approximately true.

    Read as one pair rather than through `_spool_fully_delivered` because the two
    answer different questions: that helper asks whether the backlog is drained,
    this one asks what is in it.
    """
    return _spool_frames()[_spool_head() :]


# ─────────────────────────────────────────────────────────────────────────
# The gate
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.e2e
def test_full_system_release_gate_one_agent_one_continuous_journey():
    """The 17-step release gate, on one stack, in one continuous journey.

    See the module docstring for what this proves that the twelve per-capability
    tests cannot, for the two mechanisms it has to respect, and for the one step it
    cannot fully express and why.
    """
    _up_server()
    try:
        client = _new_client()
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)
        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}
        client.headers.update(headers)

        # The remote subnet's fixture, up before the agent exists so that nothing
        # about it can be a consequence of anything the agent did. Its neighbour
        # (`probe-target-new`) is deliberately NOT started here: step 13's whole
        # subject is a device that appears after the first scan, and it can only
        # mean that if the first scan provably never saw it.
        _up_fixture_target(_PROBE_TARGET_SERVICE)

        # The pinned topology this journey names literals from, read back live from
        # Docker. An `ipam.config` entry Docker declined would otherwise surface
        # half an hour later as an inexplicable scope mismatch.
        assert _network_subnet(_AGENT_NET) == _AGENT_NET_CIDR, (
            f"agent-net is {_network_subnet(_AGENT_NET)}, not the pinned {_AGENT_NET_CIDR}"
        )
        assert _network_subnet(_PROBE_NET) == _PROBE_NET_CIDR, (
            f"probe-net is {_network_subnet(_PROBE_NET)}, not the pinned {_PROBE_NET_CIDR}"
        )

        # Subscribed before the agent exists: the automatic first scan is started by
        # the server on its own jitter and nobody triggers it, so the only way to
        # observe findings ARRIVING (rather than to find them already written) is to
        # be listening before there is anything to listen to.
        discovery_stream = _DiscoveryStreamListener(_session_cookie())
        try:
            # ═════════════════════════════════════════════════════════════════
            # Step 1: generate and run the one-line installer on subnet B
            # ═════════════════════════════════════════════════════════════════
            # `_fetch_install_material` IS step 1's integrity check: it fetches
            # install-agent.sh, reads back the server static key, the TLS pin and
            # the pinned agent version, downloads the binary the script names and
            # asserts its sha256 matches the digest the script pinned — the same
            # check a real install performs, against localhost instead of a real
            # download host.
            install_script = client.get("/install-agent.sh").text
            material = _fetch_install_material(client, headers)
            agent_toml_path = _write_agent_toml(material["server_pk"], material["tls_pin"])
            agent_toml_after_install = agent_toml_path.read_text()
            baked_version = material["baked_version"]

            # ═════════════════════════════════════════════════════════════════
            # Step 2: no interactive question, no local config edit, no scanner
            #         install, no inbound rule
            # ═════════════════════════════════════════════════════════════════
            # Four separate claims, and each is asserted against a different
            # artifact, because each could be false on its own.
            #
            # (a) NO INTERACTIVE QUESTION — a property of the generated script
            #     itself, so it is read out of the script rather than inferred from
            #     the fact that a non-TTY run happened to succeed.
            assert not re.search(r"^\s*read\s", install_script, re.MULTILINE), (
                "install-agent.sh contains a `read` — the installer asks the operator "
                "something, and the slice's claim is one command with no interactive "
                "question"
            )
            # (b) NO SCANNER INSTALL, NO CIDR TYPED — the script must not fetch a
            #     scanner, and must not ask for or hardcode a subnet. Scope is
            #     derived centrally from the facts the agent reports; a CIDR
            #     anywhere in the installer would mean it is not.
            lowered = install_script.lower()
            for forbidden in ("nmap", "arp-scan", "masscan", "snmp"):
                assert forbidden not in lowered, (
                    f"install-agent.sh mentions {forbidden!r} — the remote host is not "
                    "supposed to need a scanner for any of this"
                )
            assert "cidr" not in lowered, (
                "install-agent.sh mentions a CIDR — local scope is derived centrally "
                "from the agent's own reported interfaces and is never typed"
            )
            # (c) The config the installer writes carries a server URL, a static key
            #     and a TLS pin, and NOTHING else. Anything scope-, port-,
            #     subnet- or scanner-shaped in here would be remote-network setup by
            #     another name. `spool_cap_bytes` and `log_level` are agent-local
            #     resource limits, not policy, and are what `_write_agent_toml`
            #     writes; the assertion is about the absence of policy keys.
            for forbidden_key in ("cidr", "subnet", "scope", "scan", "port", "credential"):
                assert forbidden_key not in agent_toml_after_install.lower(), (
                    f"agent.toml contains a {forbidden_key!r} setting: "
                    f"{agent_toml_after_install!r}"
                )
            # ...and the file this harness writes is STRUCTURALLY the file the
            # installer writes, key for key. `_write_agent_toml` stands in for the
            # script's own heredoc (the harness cannot run `useradd` and rewrite
            # /usr/local/bin inside a container it did not build), so without this
            # the whole "no manual configuration" claim would be a claim about a
            # convenience file rather than about the real install path. The keys are
            # read back out of the script itself, so a settings key added to the
            # installer and not to the harness fails here rather than diverging
            # silently.
            heredoc = re.search(
                r"cat > /etc/circuit-breaker/agent\.toml <<EOF\n(.*?)\nEOF", install_script, re.DOTALL
            )
            assert heredoc, (
                "install-agent.sh no longer writes /etc/circuit-breaker/agent.toml with a "
                "heredoc, so this comparison cannot tell whether the harness's config still "
                "matches the installer's"
            )
            installer_keys = {
                line.split("=", 1)[0].strip()
                for line in heredoc.group(1).splitlines()
                if "=" in line
            }
            harness_keys = {
                line.split("=", 1)[0].strip()
                for line in agent_toml_after_install.splitlines()
                if "=" in line
            }
            assert harness_keys == installer_keys, (
                "the config this harness writes and the one install-agent.sh writes have "
                f"different settings: harness={sorted(harness_keys)} "
                f"installer={sorted(installer_keys)}"
            )
            # (d) NO INBOUND RULE. Asserted twice over, later in this step once the
            #     container exists: nothing is BOUND inside the agent's namespace,
            #     and nothing is REACHABLE from the backend. The two are different
            #     claims and only the pair rules out both "it listens but a firewall
            #     saves us" and "it is unreachable today by accident".

            # ═════════════════════════════════════════════════════════════════
            # Step 3: observe the pending agent live, and approve with normal
            #         defaults
            # ═════════════════════════════════════════════════════════════════
            # `_enroll_agent` is exactly this and nothing more: it opens
            # `/agents/stream` BEFORE enrolling, runs the real Go binary's `enroll`,
            # waits for the `enrolled` event to be PUSHED for this agent id (never
            # polling a REST list to notice it), then approves with no
            # `capabilities` body at all — so the server applies its own
            # CAPABILITY_DEFINITIONS defaults, which the helper asserts in full.
            # That assertion is the "normal defaults" half of this step and is not
            # repeated here.
            agent_id, stream = _enroll_agent(client, headers)
            try:
                subprocess.run([*COMPOSE, "up", "-d", _AGENT_SERVICE], check=True, cwd=E2E_DIR)

                # The grants as approved, snapshotted for step 14: "grants reconcile
                # without duplication" across two restarts is a claim about this map
                # still being this map.
                granted_at_approval = _agent_capabilities(client, agent_id)
                assert set(granted_at_approval) == {
                    "host_telemetry",
                    "remote_probe",
                    "local_discovery",
                }, granted_at_approval

                # ═════════════════════════════════════════════════════════════
                # Step 4: online presence and a host telemetry sample within the
                #         promised interval
                # ═════════════════════════════════════════════════════════════
                _wait_until(
                    lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                    timeout=30,
                )
                _wait_until(lambda: _agent_status()["link_state"] == "accepted", timeout=30)
                _wait_until(lambda: _agent_online(client, agent_id), timeout=60)

                # The promised interval is the approval default's own 30s; nothing
                # in this test edits it. See `_FIRST_SAMPLE_BUDGET_S`.
                telemetry = _wait_until_and_return(
                    lambda: _agent_telemetry(client, agent_id)["latest"] is not None
                    and _agent_telemetry(client, agent_id),
                    timeout=_FIRST_SAMPLE_BUDGET_S,
                )
                latest = telemetry["latest"]
                assert latest["summary"]["mem_pct"] is not None, latest
                assert latest["summary"]["uptime_s"] is not None, latest
                assert latest["status"] in ("healthy", "degraded"), latest
                # Collector readiness, which is Slice 2's contract and the thing
                # remote probe and discovery both reuse: the core collector is
                # ready, and the one that genuinely cannot run here (no Docker
                # socket is mounted into cb-agent, and `include_docker` is false in
                # the default grant) reports itself OFF rather than broken.
                states = _readiness_states(telemetry)
                assert states.get("host.core") == "ready", states
                assert states.get("host.docker") == "disabled", states
                # Original timestamp, not arrival time — one half of the "every
                # remote observation is attributable to the correct agent and
                # original timestamp" required assertion, asserted here at its
                # first opportunity and again after the outage in step 12.
                first_sample_at = _parse_ts(latest["collected_at"])
                assert first_sample_at <= datetime.now(timezone.utc), latest

                # The identity every later "it did not re-enroll" assertion is
                # measured against, taken once, here, while nothing has happened to
                # it yet. `device.key` rather than an `agents` row because the row
                # is what the server BELIEVES and this is what the agent actually
                # presents.
                device_key_at_enrollment = _device_key(_AGENT_SERVICE)

                # ---- step 2 (d), now that the container exists ---------------
                container, server_net = _agent_network_name()
                agent_ip = _container_ipv4(container, server_net)
                _assert_positive_controls(agent_ip)

                # NOTHING IS BOUND. The positive control is the backend's own
                # namespace: it must show listeners, or the /proc read below is
                # simply not observing anything.
                backend_listeners = [s for s in _tcp_sockets("circuitbreaker") if s["state"] == "0A"]
                assert backend_listeners, (
                    "the backend container shows no listening TCP socket in /proc/net/tcp, so "
                    "the identical read against the agent below would report 'no listeners' "
                    "whether or not the agent has any"
                )
                agent_sockets = _tcp_sockets(_AGENT_SERVICE)
                agent_listeners = _routable_listeners(_AGENT_SERVICE)
                assert not agent_listeners, (
                    "cb-agent has a LISTENING TCP socket on a non-loopback address — the "
                    "capability contract is that capabilities never open listeners and never "
                    f"require inbound reachability: {agent_listeners}"
                )
                # ...and it holds the outbound tunnel it is supposed to hold. Note
                # what the two halves of this actually license. "No INBOUND
                # connection" is already settled by the listener check above and
                # needs nothing further: a TCP connection cannot be accepted into a
                # namespace with no listening socket, so every ESTABLISHED socket
                # here is by construction one the agent DIALLED. What is left to
                # check is therefore where it dialled TO.
                #
                # That check is deliberately not `all(remote_port == 8443)`. The
                # agent's own discovery is a bounded CONNECT scan (`agent_connect`),
                # so from the moment the bootstrap sweep starts it legitimately holds
                # short-lived outbound sockets to ports 22/53/80/443/... on hosts in
                # its own directly connected subnets, and this read races that sweep.
                # An `all(... == 8443)` here would be an assertion about which
                # millisecond the sample landed in, and it would fail for a reason
                # that has nothing to do with inbound reachability. The honest
                # invariant — and the one a regression would actually break — is that
                # every socket goes either to the canonical server URL or to an
                # address inside the scope the agent was granted, and never anywhere
                # else.
                established = [s for s in agent_sockets if s["state"] == "01"]
                assert established, (
                    "cb-agent has no ESTABLISHED TCP socket at all, yet the server reports it "
                    "connected — this read is not observing the agent's namespace"
                )
                assert any(s["remote_port"] == _BACKEND_HTTPS_PORT for s in established), (
                    "cb-agent holds no connection to the canonical Circuit Breaker agent URL's "
                    f"port, so the link the server thinks it has is not here: {established}"
                )
                strayed = [
                    s
                    for s in established
                    if s["remote_port"] != _BACKEND_HTTPS_PORT
                    and not (
                        s["family"] == 4
                        and _in_any(s["remote_ip"], (_AGENT_NET_CIDR, _PROBE_NET_CIDR))
                    )
                ]
                assert not strayed, (
                    "cb-agent dialled something that is neither the canonical Circuit Breaker "
                    "agent URL nor an address inside its own directly connected scope: "
                    f"{strayed}"
                )

                # NOTHING IS REACHABLE. The backend publishes no route into the
                # agent, so a connect attempt from its only network peer must be
                # refused rather than merely dropped by policy. Six ports, the
                # spread `test_agent_full_lifecycle_enroll_through_revoke_and_reconnect`
                # uses.
                #
                # The LITERAL address, never the `cb-agent` service name that test
                # uses. The positive control above proves the backend can reach
                # `agent_ip` (it pings it) and that `nc` itself works (against
                # 127.0.0.1:8443) — but neither control says anything about whether
                # Docker's embedded DNS still answers for the name. Dialling a name
                # that failed to resolve produces exactly the non-zero exit this loop
                # reads as "isolated", so the whole isolation claim would survive a
                # broken DNS entry untouched. Against `agent_ip` both halves of the
                # negative are covered by a control that was just demonstrated.
                for port in (22, 80, 443, 2019, 8080, 9000):
                    probe = _backend_sh(f"nc -z -w 2 {agent_ip} {port}")
                    assert probe.returncode != 0, (
                        f"circuitbreaker could dial INTO cb-agent ({agent_ip}) on port {port} "
                        "— the agent "
                        "must accept no inbound connection at all"
                    )

                # NO SCANNER INSTALLED, asserted against the running image rather
                # than against the Dockerfile. `command -v` is demonstrated to work
                # first, against the one binary that IS there, so a shell builtin
                # that silently failed could not read as "no scanner present".
                present = _agent_shell("command -v cb-agent")
                assert present.returncode == 0, (
                    "`command -v` cannot find cb-agent inside the agent container, so the "
                    f"absence checks below prove nothing: {present.stdout!r} {present.stderr!r}"
                )
                for tool in _FORBIDDEN_AGENT_TOOLS:
                    found = _agent_shell(f"command -v {tool}")
                    assert found.returncode != 0, (
                        f"{tool!r} is installed in the agent image ({found.stdout.strip()!r}). "
                        "The remote host is supposed to need no scanner and no network "
                        "toolchain; several assertions in this suite (and "
                        "`_agent_route_networks`' use of /proc/net/route) rest on that"
                    )

                # And the premise the whole discovery half of this journey is worth
                # exactly as much as: the backend cannot reach the fixture, over
                # either transport.
                _assert_backend_cannot_reach(_PROBE_TARGET_IP, _PROBE_NET_CIDR)

                # ═════════════════════════════════════════════════════════════
                # Step 5: safe subnet B scope is derived, and one system profile
                #         per directly connected subnet is created
                # ═════════════════════════════════════════════════════════════
                # Nothing below types a CIDR. The only thing that puts these two
                # networks in the server's scope is the interface facts the agent
                # reported in `hello`, derived through the shared network-scope
                # evaluator into `direct_private`.
                _wait_until(
                    lambda: {_AGENT_NET_CIDR, _PROBE_NET_CIDR}
                    <= _automatic_scope(client, agent_id),
                    timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
                )
                scope = _automatic_scope(client, agent_id)
                assert scope == {_AGENT_NET_CIDR, _PROBE_NET_CIDR}, (
                    "the derived scope is not exactly the agent's two directly connected "
                    f"pinned subnets — something other than the agent's own kernel is "
                    f"supplying it: {sorted(scope)}"
                )
                # The agent's own routing table, which is the other half of that
                # sentence: what `hostinfo.Networks()` enumerates on every hello.
                assert _agent_route_networks() == {_AGENT_NET_CIDR, _PROBE_NET_CIDR}, (
                    "the agent's kernel routing table does not match the pinned topology: "
                    f"{sorted(_agent_route_networks())}"
                )
                view = _discovery_view(client, agent_id)
                assert view["granted"] is True and view["eligible"] is True, view
                assert view["paused"] is False and view["globally_paused"] is False, view
                assert view["limits"]["scope_mode"] == "direct_private", view["limits"]

                # D-12: one system-managed profile PER directly connected subnet,
                # which for a container on two networks is two — "exactly one
                # overall" is the thing that cannot hold here and asserting it would
                # be asserting the harness rather than the product.
                _wait_until(
                    lambda: len(_discovery_profiles(client, agent_id)) >= 2,
                    timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
                )
                probe_profile = _system_profile_for(client, agent_id, _PROBE_NET_CIDR)
                agent_net_profile = _system_profile_for(client, agent_id, _AGENT_NET_CIDR)
                profiles_at_bootstrap = _discovery_profiles(client, agent_id)
                assert {p["cidr"] for p in profiles_at_bootstrap} == {
                    _AGENT_NET_CIDR,
                    _PROBE_NET_CIDR,
                }, [(p["cidr"], p["managed_by"]) for p in profiles_at_bootstrap]
                assert all(p["managed_by"] == "system" for p in profiles_at_bootstrap)
                assert all(p["enabled"] and p["paused_at"] is None for p in profiles_at_bootstrap)
                assert probe_profile["scan_types"] == [_AGENT_SCAN_TYPE], probe_profile
                assert probe_profile["nmap_arguments"] is None, probe_profile
                # D-7's derived six-hourly cadence with per-agent jitter. Restated
                # as the literal the server derives, so a cadence that silently
                # became "never" fails here rather than in step 14.
                expected_cron = f"{agent_id % 60} */6 * * *"
                assert probe_profile["schedule_cron"] == expected_cron, probe_profile
                assert agent_net_profile["schedule_cron"] == expected_cron, agent_net_profile

                # ═════════════════════════════════════════════════════════════
                # Step 6: automatic initial discovery, with incremental findings
                #         in the existing job UI
                # ═════════════════════════════════════════════════════════════
                initial_job = _wait_until_and_return(
                    lambda: next(iter(_scan_jobs(client, profile_id=probe_profile["id"])), None),
                    timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
                )
                initial_job_id = initial_job["id"]
                assert initial_job["triggered_by"] == "bootstrap", (
                    "the first scan was not started by the server's own bootstrap pass, so "
                    f"something asked for it and step 6 is not being tested: {initial_job}"
                )
                assert initial_job["scan_agent_id"] == agent_id, initial_job
                assert initial_job["source_type"] == "agent", initial_job
                assert initial_job["target_cidr"] == _PROBE_NET_CIDR, initial_job

                _wait_until(
                    lambda: _scan_job(client, initial_job_id)["status"] == "completed",
                    timeout=_INITIAL_SCAN_BUDGET_S,
                )
                completed = _scan_job(client, initial_job_id)
                assert completed["error_reason"] is None, completed
                assert completed["hosts_found"] >= 1, completed

                # "in the existing job UI" is a claim about a stream an operator
                # watches, not about rows that exist afterwards. `WS
                # /api/v1/discovery/stream` is the channel the Discovery page
                # subscribes to, and the assertion is ORDER on that one channel: a
                # `result_added` naming the fixture arrived BEFORE the job's
                # terminal event. A backend that buffered every finding and wrote
                # them in one batch at the end produces the same final table and
                # cannot produce that order.
                pushed = discovery_stream.snapshot()
                streamed = [
                    e
                    for e in pushed
                    if e.get("type") == "result_added" and e.get("job_id") == initial_job_id
                ]
                terminal = [
                    i
                    for i, e in enumerate(pushed)
                    if e.get("type") == "job_update"
                    and (e.get("job") or {}).get("id") == initial_job_id
                    and (e.get("job") or {}).get("status") == "completed"
                ]
                assert streamed, (
                    "no result_added was pushed for the automatic scan — findings are not "
                    f"reaching the discovery stream at all. Saw: {[e.get('type') for e in pushed]}"
                )
                assert terminal, "no terminal job_update was pushed for the automatic scan"
                assert pushed.index(streamed[0]) < terminal[0], (
                    "every finding was pushed at or after the job's terminal event — an "
                    "operator never saw hosts arrive, which is the whole point of streaming "
                    "findings incrementally rather than writing them in one batch"
                )
                assert _PROBE_TARGET_IP in [
                    (e.get("result") or {}).get("ip_address") for e in streamed
                ], f"{_PROBE_TARGET_IP} was never pushed as an incremental result"

                # ═════════════════════════════════════════════════════════════
                # Step 7: accept a finding; one attributed Hardware record and
                #         topology placement
                # ═════════════════════════════════════════════════════════════
                # Found through the ORDINARY review queue — `GET
                # /discovery/results?status=pending`, no agent parameter, no
                # execution-location filter, which is exactly what
                # `src/api/discovery.js`'s `listPendingResults` asks for. Locating
                # the row through an agent-scoped route would prove the opposite of
                # the "no separate UI path" claim.
                queued = [r for r in _review_queue(client) if r["ip_address"] == _PROBE_TARGET_IP]
                assert len(queued) == 1, (
                    f"expected exactly one pending review row for {_PROBE_TARGET_IP}: {queued}"
                )
                review_row = queued[0]
                assert review_row["scan_job_id"] == initial_job_id, review_row
                assert review_row["merge_status"] == "pending", review_row
                assert review_row["state"] == "new", review_row
                # The agent's own reverse lookup on the remote subnet. Kept because
                # the import names the new Hardware row after it
                # (`discovery_merge`), which is what makes the operator rename below
                # a genuine disagreement between two sources rather than a no-op.
                observed_hostname = review_row["hostname"]
                assert observed_hostname, (
                    "the agent reported no hostname for the fixture. probe-net's resolver is "
                    "Docker's embedded DNS, which answers PTR for containers on a user-defined "
                    f"network; if it has stopped doing so this row needs a fixture that supplies "
                    f"a name some other way: {review_row}"
                )
                open_ports = {
                    p["port"] for p in json.loads(review_row["open_ports_json"] or "[]")
                }
                assert {53, _PROBE_TARGET_HTTP_PORT} <= open_ports, (
                    f"the finding reports open ports {sorted(open_ports)}; the fixture answers "
                    "TCP on 53 (dnsmasq) and 8080 (httpd), both in the grant's port list, and "
                    "only a connect scan from inside probe-net could have seen them"
                )

                assert _hardware_with_ip(client, _PROBE_TARGET_IP) == [], (
                    "a Hardware row for the fixture existed before anyone imported it — the "
                    "scan or the finalizer auto-merged an agent finding, which plan §5 forbids"
                )
                nodes_before_import = _topology_nodes(client)
                merged = client.post(
                    f"/api/v1/discovery/results/{review_row['id']}/merge",
                    json={"action": "accept", "entity_type": "hardware"},
                )
                assert merged.status_code == 200, merged.text

                hardware_rows = _hardware_with_ip(client, _PROBE_TARGET_IP)
                assert len(hardware_rows) == 1, f"import created {len(hardware_rows)} rows"
                hardware = hardware_rows[0]
                hardware_id = hardware["id"]
                assert merged.json().get("entity_id") == hardware_id, merged.json()
                assert not [
                    r for r in _review_queue(client) if r["id"] == review_row["id"]
                ], "the accepted row is still pending in the review queue"
                assert hardware["name"] == observed_hostname, (
                    "the imported row is not named after the hostname the agent reported, so the "
                    f"agent's observation did not reach the inventory at all: {hardware}"
                )
                # The provenance the merge writes onto the row itself
                # (`discovery_merge`, CB-REL-001): this Hardware record points back
                # at the exact ScanResult the agent produced, which is what makes it
                # an ATTRIBUTED record rather than a row that happens to carry the
                # same address.
                assert hardware["source"] == "discovery", hardware
                assert hardware["source_scan_result_id"] == review_row["id"], (
                    "the imported Hardware row does not point back at the agent's finding, so "
                    f"nothing ties the record to the observation that created it: {hardware}"
                )

                # ATTRIBUTED. `scan_results.discovery_agent_id` is the provenance
                # column plan §2 adds and it is deliberately not on the wire
                # (`ScanResultOut` omits it), so this is read straight out of the
                # backend's own database. Both halves are compared — the row's own
                # reporter AND its job's executor — because they are written by two
                # different code paths and a divergence between them is exactly the
                # shape cross-attribution would take.
                provenance = {row["ip_address"]: row for row in _result_provenance()}
                fixture_provenance = provenance[_PROBE_TARGET_IP]
                assert fixture_provenance["discovery_agent_id"] == agent_id, fixture_provenance
                assert fixture_provenance["job_scan_agent_id"] == agent_id, fixture_provenance
                # ...and the imported row is reachable from the finding, so the
                # Hardware record is attributable to the agent transitively rather
                # than by coincidence of address.
                imported_result = next(
                    r for r in _job_results(client, initial_job_id) if r["id"] == review_row["id"]
                )
                assert (
                    imported_result["matched_entity_type"],
                    imported_result["matched_entity_id"],
                ) == ("hardware", hardware_id), imported_result

                # TOPOLOGY PLACEMENT. The imported device is a node in the default
                # graph, exactly once, and it was not there before the import.
                node_id = f"hw-{hardware_id}"
                nodes_after_import = _topology_nodes(client)
                assert node_id not in nodes_before_import, (
                    f"{node_id} was already a topology node before the import"
                )
                assert nodes_after_import.count(node_id) == 1, (
                    f"the imported device is placed {nodes_after_import.count(node_id)} times "
                    f"in the topology graph: {[n for n in nodes_after_import if n == node_id]}"
                )

                # An operator names the device they just imported. This is an
                # ordinary inventory write, and it is done HERE, before the monitors
                # exist, so that step 8's monitors provably follow the Hardware ROW
                # rather than the hostname the agent happened to report.
                _rename_hardware(client, hardware_id, _GATE_HARDWARE_NAME)

                # ═════════════════════════════════════════════════════════════
                # Step 8: ICMP, TCP, HTTP(S) and DNS monitors FROM the discovered
                #         device, with the agent vantage
                # ═════════════════════════════════════════════════════════════
                # THE JOIN THIS WHOLE FILE EXISTS FOR. Every address below is read
                # off the imported Hardware row, never from `_PROBE_TARGET_IP`:
                # discovery found the host, an operator imported it, and the
                # monitors are built from the row that import created. Slice 3's
                # test creates the same four check types against a hardcoded
                # fixture IP, which is a fine proof of the probe path and no proof
                # at all that the discovery -> import -> monitor chain holds.
                #
                # `target_type`/`target_id` link each monitor to that same row
                # (monitor-any-inventory-entity), so the vantage, the target entity
                # and the address all come from the one place.
                discovered_ip = hardware["ip_address"]
                assert discovered_ip == _PROBE_TARGET_IP, (
                    "the imported Hardware row does not carry the fixture's address, so the "
                    "monitors below would be pointed somewhere the agent never discovered: "
                    f"{hardware}"
                )
                assert _hardware_row(client, hardware_id)["name"] == _GATE_HARDWARE_NAME

                # The agent is an eligible vantage for that address with NO scope
                # edit of any kind — nothing in this test has ever PUT
                # /capabilities, and the only thing that put 10.77.0.0/24 in scope
                # is the interface facts in `hello`.
                _wait_until(
                    lambda: _probe_eligible_row(client, agent_id, host=discovered_ip)["eligible"],
                    timeout=_TOPOLOGY_PROPAGATION_BUDGET_S,
                )
                eligible = _probe_eligible_row(client, agent_id, host=discovered_ip)
                assert eligible["in_scope"] is True and eligible["reason"] is None, eligible
                assert eligible["granted"] is True and eligible["online"] is True, eligible
                assert eligible["readiness"] == "ready", eligible
                assert _PROBE_NET_CIDR in eligible["scope_networks"], eligible

                # OUT-OF-SCOPE, the required assertion's own half, asserted HERE
                # and not later. `evaluate_eligibility` short-circuits in a fixed
                # order — agent active, then grant enabled, then online, then
                # readiness, then scope — so the reason it names is only about
                # SCOPE while every earlier precondition holds. This is the one
                # moment in the journey where that is true of a grant nobody has
                # touched: step 16 withdraws `remote_probe`, and the identical call
                # made after that returns `capability_disabled`, which would satisfy
                # a bare `assert reason` while proving nothing about scope at all.
                # Same agent, same evaluator, same instant as the positive above;
                # only the address differs.
                out_of_scope = _probe_eligible_row(client, agent_id, host="8.8.8.8")
                assert out_of_scope["granted"] is True and out_of_scope["online"] is True, (
                    "the negative below is being taken while some precondition other than "
                    f"scope is already failing, so its reason would not be about scope: "
                    f"{out_of_scope}"
                )
                assert out_of_scope["in_scope"] is False, out_of_scope
                assert out_of_scope["eligible"] is False, out_of_scope
                assert out_of_scope["reason"] == "out_of_scope", (
                    "a public address was refused for a reason other than being outside the "
                    "agent's derived scope. `direct_private` admitted the fixture subnet a line "
                    f"ago from the same derivation, so this is the half that bounds it: "
                    f"{out_of_scope}"
                )

                common = {
                    "interval_secs": _PROBE_INTERVAL_S,
                    "max_retries": 0,
                    "enabled": True,
                    "probe_agent_id": agent_id,
                    "target_type": "hardware",
                    "target_id": hardware_id,
                }
                monitors = {
                    "icmp": _create_monitor(
                        client,
                        name="release gate icmp (discovered device)",
                        check_type="icmp",
                        host=discovered_ip,
                        config={"packet_count": 3, "timeout": 1.5},
                        **common,
                    ),
                    "tcp": _create_monitor(
                        client,
                        name="release gate tcp (discovered device)",
                        check_type="tcp",
                        # The port comes from the FINDING, not from a literal: the
                        # connect scan reported 8080 open, and that is what makes
                        # this monitor "created from the discovered device" rather
                        # than merely pointed at its address.
                        config={"port": _PROBE_TARGET_HTTP_PORT, "timeout": 2.0},
                        host=discovered_ip,
                        **common,
                    ),
                    "http": _create_monitor(
                        client,
                        name="release gate http (discovered device)",
                        check_type="http",
                        host=discovered_ip,
                        config={"url": f"http://{discovered_ip}:{_PROBE_TARGET_HTTP_PORT}/"},
                        **common,
                    ),
                    # The DNS monitor's RESOLVER is the discovered address; its
                    # record name is not, and cannot be. `probe_eligibility.
                    # evaluate_eligibility` resolves any non-literal monitor host on
                    # the SERVER before it will dispatch (an unresolvable name is
                    # refused as `unresolved_host`), and the only name the backend
                    # can resolve for this host is the `extra_hosts` entry in
                    # docker-compose.yml — not whatever PTR form Docker's embedded
                    # DNS handed the agent. So the record is the resolvable name and
                    # the resolver, the expectation and the target entity all come
                    # from the imported row.
                    "dns": _create_monitor(
                        client,
                        name="release gate dns (discovered device)",
                        check_type="dns",
                        host=_PROBE_TARGET_NAME,
                        config={
                            "record_type": "A",
                            "resolver": discovered_ip,
                            "expected_values": [discovered_ip],
                            "timeout": 5.0,
                        },
                        **common,
                    ),
                }
                for check_type, created in monitors.items():
                    assert created["probe_mode"] == "agent", (check_type, created)
                    assert created["probe_agent_id"] == agent_id, (check_type, created)
                    assert created["probe_agent"]["id"] == agent_id, (check_type, created)
                    assert created["target_type"] == "hardware", (check_type, created)
                    assert created["target_id"] == hardware_id, (
                        "the monitor is not attached to the Hardware row discovery created, so "
                        f"this is not a monitor 'from the discovered device': {created}"
                    )
                    assert created["status"] == "pending", (check_type, created)

                # ═════════════════════════════════════════════════════════════
                # Step 9: results enter the existing monitor state, history,
                #         retry, uptime and alert pipeline
                # ═════════════════════════════════════════════════════════════
                for check_type, created in monitors.items():
                    monitor_id = created["id"]

                    def _is_up(monitor_id: int = monitor_id) -> dict | None:
                        current = _monitor(client, monitor_id)
                        if current["status"] == "up" and current["probe_execution_status"] == "ready":
                            return current
                        return None

                    current = _wait_until_and_return(_is_up, timeout=_PROBE_FIRST_RESULT_BUDGET_S)
                    assert current["probe_execution_reason"] is None, (check_type, current)
                    assert current["probe_last_result_at"] is not None, (check_type, current)

                    # ORDINARY monitor telemetry — same table, same metric names —
                    # which is what lets uptime aggregate agent-executed and
                    # server-executed checks without splitting the denominator.
                    avail = _monitor_samples(client, monitor_id, "avail")
                    assert avail and set(avail) == {1.0}, (check_type, avail)
                    assert _monitor_samples(client, monitor_id, "latency_ms"), check_type
                    uptime = _uptime(client, monitor_id)
                    assert uptime["pct_24h"] == 100.0, (check_type, uptime)
                    assert uptime["last_polled_at"] is not None, (check_type, uptime)

                    # One transition, from the shared state machine.
                    transitions = _transitions(client, monitor_id)
                    assert [e["event_type"] for e in transitions] == ["up"], (check_type, transitions)
                    assert transitions[0]["status_from"] == "pending", (check_type, transitions)

                    # The vantage's own audit trail, which a server-executed check
                    # has none of, and which names the agent on every row.
                    runs = _probe_runs(client, monitor_id)
                    completed_runs = [r for r in runs if r["status"] == "completed"]
                    assert completed_runs, (check_type, runs)
                    assert completed_runs[0]["outcome"] == "completed", (check_type, completed_runs[0])
                    assert completed_runs[0]["agent_id"] == agent_id, (check_type, completed_runs[0])
                    assert completed_runs[0]["error_code"] is None, (check_type, completed_runs[0])

                # RETRY and the ALERT path, on the same discovered device. A closed
                # port on the imported row's own address is a genuine TARGET
                # failure, not an execution error, so it goes through `state.decide`
                # exactly as a server-executed failure does — and DOWN is the
                # transition that carries `notify="down"` into
                # `result_service._publish_transitions`, which is one implementation
                # for both vantages rather than two that agree.
                retry_monitor = _create_monitor(
                    client,
                    name="release gate retry/alert (discovered device)",
                    check_type="tcp",
                    host=discovered_ip,
                    config={"port": _PROBE_TARGET_CLOSED_PORT, "timeout": 2.0},
                    interval_secs=_PROBE_INTERVAL_S,
                    retry_interval_secs=10,
                    max_retries=1,
                    enabled=True,
                    probe_agent_id=agent_id,
                    target_type="hardware",
                    target_id=hardware_id,
                )
                retry_id = retry_monitor["id"]
                _wait_until(
                    lambda: _monitor(client, retry_id)["status"] == "down",
                    timeout=_PROBE_FIRST_RESULT_BUDGET_S,
                )
                down_transitions = _transitions(client, retry_id)
                assert [e["event_type"] for e in down_transitions] == ["down"], down_transitions
                assert down_transitions[0]["status_from"] == "pending", down_transitions
                down_avail = _monitor_samples(client, retry_id, "avail")
                assert set(down_avail) == {0.0}, down_avail
                # The retry itself, asserted where it is observable: with
                # max_retries=1 the state machine owes a second observation —
                # pulled in to retry_interval_secs rather than a full interval —
                # before it may transition, so more than one sample must sit behind
                # this DOWN.
                assert len(down_avail) >= 2, (
                    "the monitor went DOWN on its first failed check; max_retries=1 was not "
                    f"honoured for an agent-executed check against the discovered device: "
                    f"{down_avail}"
                )
                assert _monitor_samples(client, retry_id, "latency_ms") == [], (
                    "a failed TCP check produced a latency sample"
                )

                # ...and RECOVERY, which is the other half of the alert pipeline
                # (`notify="recovered"`). An ordinary monitor edit — point the same
                # monitor at the port the FINDING said was open — with the vantage
                # untouched: `MonitorUpdate` uses `exclude_unset`, so not sending
                # `probe_agent_id` is what tells a config edit apart from a
                # reassignment.
                repointed = client.patch(
                    f"/api/v1/monitors/{retry_id}",
                    json={"config": {"port": _PROBE_TARGET_HTTP_PORT, "timeout": 2.0}},
                )
                assert repointed.status_code == 200, repointed.text
                assert repointed.json()["probe_agent_id"] == agent_id, (
                    "editing a monitor's config moved its vantage"
                )
                _wait_until(
                    lambda: _monitor(client, retry_id)["status"] == "up",
                    timeout=_PROBE_FIRST_RESULT_BUDGET_S,
                )
                recovery = _transitions(client, retry_id)
                assert [e["event_type"] for e in recovery] == ["down", "up"], (
                    "the recovery did not produce a second transition after the DOWN, so the "
                    f"`recovered` half of the alert path never fired: {recovery}"
                )
                assert recovery[1]["status_from"] == "down", recovery
                assert 0.0 in _monitor_samples(client, retry_id, "avail")
                assert 1.0 in _monitor_samples(client, retry_id, "avail")
                # Uptime is computed over both, from the same rows: an
                # agent-executed monitor that has been down is not at 100%.
                retry_uptime = _uptime(client, retry_id)
                assert 0.0 < retry_uptime["pct_24h"] < 100.0, (
                    "uptime for a monitor that went down and recovered is not between the two, "
                    f"so agent-executed results are not reaching the uptime denominator: "
                    f"{retry_uptime}"
                )

                # ═════════════════════════════════════════════════════════════
                # Required assertion: existing server-side discovery and
                # monitoring paths still work unchanged
                # ═════════════════════════════════════════════════════════════
                # Not a journey step — a property the journey must not break, and
                # the natural place to establish it is here, with an agent doing
                # discovery and monitoring right beside the server.
                #
                # MONITORING: an ordinary server-executed monitor, `probe_agent_id`
                # absent entirely (the pre-Slice-3 shape). It targets the backend's
                # own HTTPS listener rather than anything on the remote subnet, so
                # it stays valid across step 15's address change and depends on the
                # agent for nothing.
                server_monitor = _create_monitor(
                    client,
                    name="release gate server-executed control",
                    check_type="tcp",
                    host="127.0.0.1",
                    config={"port": _BACKEND_HTTPS_PORT, "timeout": 2.0},
                    interval_secs=_PROBE_INTERVAL_S,
                    max_retries=0,
                    enabled=True,
                )
                server_monitor_id = server_monitor["id"]
                assert server_monitor["probe_mode"] == "server", server_monitor
                assert server_monitor["probe_agent_id"] is None, server_monitor
                _wait_until(
                    lambda: _monitor(client, server_monitor_id)["status"] == "up",
                    timeout=_PROBE_FIRST_RESULT_BUDGET_S,
                )
                assert _monitor(client, server_monitor_id)["probe_execution_status"] is None, (
                    "a server-executed monitor grew a vantage execution condition"
                )
                assert _probe_runs(client, server_monitor_id) == [], (
                    "a probe run was opened for a server-executed monitor — the existing "
                    "server path is being dispatched to an agent"
                )

                # DISCOVERY: an ordinary operator-created, server-executed profile,
                # scanning one address the server genuinely can reach (its own
                # agent-net interface). nmap is present in the mono image
                # (Dockerfile.mono), so this is the real server scanner, not a stub.
                #
                # It has to be switched on first: `nmap_enabled` defaults to False
                # (schemas/settings.py) and services/discovery_service.py refuses an
                # `nmap`/`deep_dive` job without it — "Enable 'Nmap Active Scanning'
                # in Discovery Settings", which is exactly what this does. That is
                # the operator's own path, not a test backdoor. It is also safe to
                # do mid-journey: the agent's own discovery runs `agent_connect`,
                # which is not in `_requires_nmap`'s set, so nothing above or below
                # changes behaviour because of this.
                nmap_on = client.put(
                    "/api/v1/settings", json={"nmap_enabled": True}, headers=headers
                )
                assert nmap_on.status_code == 200, nmap_on.text
                backend_ip = _container_ipv4(_backend_container(), server_net)
                server_profile = _create_server_profile(
                    client,
                    headers,
                    name="release gate server-side discovery",
                    cidr=f"{backend_ip}/32",
                )
                server_job = _run_profile_now(client, server_profile["id"])
                server_job_id = server_job["id"]
                assert server_job["scan_agent_id"] is None, server_job
                _wait_until(
                    lambda: _scan_job(client, server_job_id)["status"]
                    in ("completed", "failed", "cancelled"),
                    timeout=_SERVER_SCAN_BUDGET_S,
                )
                server_job_final = _scan_job(client, server_job_id)
                assert server_job_final["status"] == "completed", (
                    "the ordinary server-side discovery path no longer completes a scan of an "
                    f"address the server can reach: {server_job_final}"
                )
                assert server_job_final["hosts_found"] >= 1, (
                    "the server scanner found nothing at its own address, which it demonstrably "
                    f"reaches (the nc positive control above): {server_job_final}"
                )
                assert server_job_id not in [
                    j["id"] for j in _agent_scan_jobs(client, agent_id)
                ], "a server-executed job was dispatched to the agent"
                assert all(
                    row["discovery_agent_id"] is None
                    for row in _result_provenance()
                    if row["scan_job_id"] == server_job_id
                ), "a server-executed scan's results were attributed to an agent"
                # ...and the agent's own profiles were not disturbed by any of it.
                assert {p["id"] for p in _discovery_profiles(client, agent_id)} == {
                    p["id"] for p in profiles_at_bootstrap
                }, "creating a server profile changed the agent's system-managed profiles"

                # ═════════════════════════════════════════════════════════════
                # Step 10: disconnect WAN while collecting telemetry and while an
                #          eligible result is in flight
                # ═════════════════════════════════════════════════════════════
                # `_cut_agent_network`, not `_backend_outage`: step 11 requires the
                # SERVER to report the agent unavailable, which it can only do while
                # it is running. Only agent-net is severed, so the agent keeps its
                # route to the fixture — which is what makes "the vantage went away"
                # distinguishable from "the target went down", the exact distinction
                # step 11 is about.
                #
                # The in-flight result is a real one: an HTTP check against
                # /cgi-bin/slow, which sleeps for two minutes, dispatched
                # immediately before the cut so the agent is genuinely mid-check
                # when its link dies. A monitor whose check finishes in
                # milliseconds would give this step nothing to be about.
                slow_monitor = _create_monitor(
                    client,
                    name="release gate in-flight check (discovered device)",
                    check_type="http",
                    host=discovered_ip,
                    config={
                        "url": f"http://{discovered_ip}:{_PROBE_TARGET_HTTP_PORT}/cgi-bin/slow",
                        "timeout": 100.0,
                    },
                    # Long enough that the scheduler opens exactly one run for it
                    # across this whole journey.
                    interval_secs=3600,
                    max_retries=0,
                    enabled=True,
                    probe_agent_id=agent_id,
                    target_type="hardware",
                    target_id=hardware_id,
                )
                slow_id = slow_monitor["id"]

                def _dispatched_run(monitor_id: int, exclude: frozenset = frozenset()) -> dict | None:
                    """A run this monitor currently has in flight, ignoring any run
                    id the caller already knows about.

                    `exclude` is not tidiness. A run legitimately stays `dispatched`
                    until the reconciliation pass expires its lease, so a caller
                    asking "is there a NEW run in flight" can otherwise be answered
                    instantly with a stale one — and `_wait_until_and_return` returns
                    the first truthy answer, so the mistake surfaces as an assertion
                    failure on the very first poll rather than as a wait that would
                    have succeeded a second later.
                    """
                    for run in _probe_runs(client, monitor_id):
                        if run["status"] == "dispatched" and run["run_id"] not in exclude:
                            return run
                    return None

                in_flight = _wait_until_and_return(
                    lambda: _dispatched_run(slow_id), timeout=_PROBE_FIRST_RESULT_BUDGET_S
                )
                assert in_flight["agent_id"] == agent_id, in_flight

                icmp_id = monitors["icmp"]["id"]
                events_before_cut = _monitor_events(client, icmp_id)
                runs_before_cut = len(_probe_runs(client, icmp_id))
                result_at_before_cut = _monitor(client, icmp_id)["probe_last_result_at"]
                samples_before_cut = _agent_host_samples(
                    agent_id, first_sample_at - timedelta(seconds=1), datetime.now(timezone.utc)
                )

                with _cut_agent_network():
                    # A detached interface is a black hole: no FIN, no RST, and the
                    # agent's writes keep succeeding into a buffer that will never
                    # drain. The ONLY evidence available to it is silence, via
                    # internal/link's steady-state read deadline (60s = three missed
                    # server pings), so nothing collected before this flip is
                    # spooled and nothing collected before it can be asserted to
                    # arrive.
                    cut_at = time.monotonic()
                    _wait_until(
                        lambda: _agent_status()["link_state"] == "disconnected",
                        timeout=_PARTITION_DETECT_BUDGET_S,
                    )
                    detected_after = time.monotonic() - cut_at
                    detected_at = datetime.now(timezone.utc)
                    # A floor as well as a ceiling. Dropping the link far sooner than
                    # the read deadline would mean something other than silence tore
                    # it down, and this step would be describing a different outage
                    # shape than the WAN loss it claims to be about. Half the
                    # deadline is the same margin `test_agent_black_hole_partition_
                    # is_detected_and_spools` uses.
                    assert detected_after >= _PARTITION_DETECT_S * 0.5, (
                        f"the link dropped after only {detected_after:.0f}s of a "
                        f"{_PARTITION_DETECT_S}s read deadline — the drop cannot have come from "
                        "the deadline expiring on a severed route"
                    )
                    partition_status = _agent_status()
                    assert "read deadline" in partition_status.get("last_error", ""), (
                        "the link dropped during the partition, but not on the read deadline: "
                        f"last_error={partition_status.get('last_error')!r}. Something other "
                        "than silence tore it down, and the spooling below would be about a "
                        "different failure than the one step 10 describes"
                    )

                    # ═════════════════════════════════════════════════════════
                    # Step 11: central status becomes offline/unavailable without
                    #          falsely changing target state
                    # ═════════════════════════════════════════════════════════
                    _wait_until(
                        lambda: not _agent_online(client, agent_id),
                        timeout=_PROBE_UNAVAILABLE_BUDGET_S,
                    )
                    # The enrollment lifecycle is untouched: presence is not status,
                    # and an unreachable agent has not been revoked.
                    assert client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active"

                    def _is_unavailable() -> dict | None:
                        current = _monitor(client, icmp_id)
                        return current if current["probe_execution_status"] == "unavailable" else None

                    unavailable = _wait_until_and_return(
                        _is_unavailable, timeout=_PROBE_UNAVAILABLE_BUDGET_S
                    )
                    # §2's vocabulary. Which of these lands depends only on whether
                    # the presence key expired before or after the next scheduler
                    # tick, so all four are legal and none of them is "the target
                    # went down".
                    assert unavailable["probe_execution_reason"] in {
                        "agent_offline",
                        "no_link_owner",
                        "dispatch_failed",
                        "result_timeout",
                    }, unavailable
                    assert unavailable["status"] == "up", unavailable
                    assert unavailable["probe_agent_id"] == agent_id, (
                        "an unavailable vantage was silently taken away from the monitor — §2 "
                        "keeps the assignment and never falls back to the server"
                    )

                    # Two more monitor intervals, so this is "no false state change
                    # for the whole outage" rather than "none in its first second".
                    time.sleep(_PROBE_INTERVAL_S * 2)
                    during = _monitor(client, icmp_id)
                    assert during["status"] == "up", during
                    assert during["probe_last_result_at"] == result_at_before_cut, (
                        "probe_last_result_at moved while the agent was unreachable — something "
                        "wrote a result the agent cannot have produced"
                    )
                    assert set(_monitor_samples(client, icmp_id, "avail")) == {1.0}, (
                        "an avail=0 sample was written while the vantage was unavailable. §2/D-12 "
                        "forbid it: agent unavailability is not target downtime, and this sample "
                        "would corrupt the discovered device's uptime for the whole outage"
                    )
                    assert _uptime(client, icmp_id)["pct_24h"] == 100.0
                    # No TARGET transition either. `execution` events may be added —
                    # one per change of reason, §6 — and they carry the target's
                    # state through unchanged rather than rewriting it.
                    events_during = _monitor_events(client, icmp_id)
                    new_events = events_during[: len(events_during) - len(events_before_cut)]
                    assert {e["event_type"] for e in new_events} <= {"execution"}, new_events
                    for event in new_events:
                        assert event["status_from"] == "up" and event["status_to"] == "up", event
                    # The scheduler kept trying, and left nothing wedged behind the
                    # partial unique index. A run legitimately stays `dispatched`
                    # until deadline_at (scheduled_at + 20s) plus the reconciliation
                    # pass's 30s grace, so only rows well past that are evidence of
                    # a wedge rather than of a lease running its course.
                    assert len(_probe_runs(client, icmp_id)) > runs_before_cut, (
                        "the scheduler stopped opening runs for an assigned monitor whose agent "
                        "is offline — §2 requires it to keep trying on its normal interval"
                    )
                    wedged = [
                        r
                        for r in _probe_runs(client, icmp_id)
                        if r["status"] in ("queued", "dispatched")
                        and _parse_ts(r["scheduled_at"])
                        < datetime.now(timezone.utc) - timedelta(seconds=120)
                    ]
                    assert not wedged, (
                        f"a probe run is still in flight long past its lease: {wedged}"
                    )

                    # The server-executed control monitor is untouched by any of
                    # this — the existing path does not notice an agent outage.
                    assert _monitor(client, server_monitor_id)["status"] == "up", (
                        "an agent's WAN outage changed a server-executed monitor's state"
                    )

                    # ...and the agent goes on collecting, into the spool.
                    time.sleep(_WAN_SPOOL_S)
                    spool_during = _undelivered_frames()
                    _assert_spool_holds_only_data_frames(spool_during)
                    assert _spooled_of_type(spool_during, "telemetry.host"), (
                        f"nothing was spooled in {_WAN_SPOOL_S}s of collecting through a detected "
                        "partition — samples are being dropped instead of queued"
                    )
                    assert _agent_status()["spool_depth"] > 0, _agent_status()
                    # The in-flight check completed during the outage and its result
                    # is durably queued rather than lost. This is step 10's
                    # "completing an eligible in-flight result": the work finished,
                    # on the agent, with no link.
                    assert _spooled_of_type(spool_during, "probe.result"), (
                        "the check that was in flight when the WAN died produced no spooled "
                        "result — an eligible in-flight result was dropped rather than kept: "
                        f"{sorted({f.get('type') for f in spool_during})}"
                    )

                restored_at = datetime.now(timezone.utc)

                # ═════════════════════════════════════════════════════════════
                # Step 12: restore WAN — reconnect, bounded spool catch-up,
                #          idempotency, immediate due probe recovery, and no
                #          re-enrollment
                # ═════════════════════════════════════════════════════════════
                _wait_until(
                    lambda: _agent_status()["link_state"] == "accepted",
                    timeout=_RECONNECT_BUDGET_S,
                )
                _wait_until(_spool_fully_delivered, timeout=_SPOOL_DRAIN_BUDGET_S)
                _wait_until(
                    lambda: _agent_telemetry(client, agent_id)["spool"]["depth"] == 0,
                    timeout=_RECONNECT_BUDGET_S,
                )
                # NO RE-ENROLLMENT. Four independent facts, not one: one agents row,
                # the same id, the same device key on disk, and no second `enrolled`
                # event. A reconnect that quietly re-enrolled would satisfy any one
                # of them alone. The device key is compared against the digest taken
                # when the agent first came up, not against one read after the
                # outage: an agent that re-enrolled mid-outage and then stayed
                # consistent with itself would satisfy the second and not the first.
                assert _device_key(_AGENT_SERVICE) == device_key_at_enrollment, (
                    "the agent's on-disk device.key changed across the WAN outage — it "
                    "re-enrolled rather than resuming its existing identity"
                )
                assert len(_agents(client)) == 1, [a["id"] for a in _agents(client)]
                assert client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active"
                assert len(_enrolled_event_ids(client, agent_id)) == 1, _enrolled_event_ids(
                    client, agent_id
                )
                assert not [
                    a for a in client.get("/api/v1/agents/pending").json() if a["id"] == agent_id
                ], "the agent reappeared as pending after the outage — a new pairing code was needed"

                # BOUNDED CATCH-UP WITH ORIGINAL TIMESTAMPS. The window is the one
                # bounded by the two instants this test actually observed: the flip
                # to `disconnected` (before which nothing was spooled) and the
                # restore. Raw samples are read straight out of the database because
                # no endpoint can answer per-sample questions — `/telemetry` serves
                # exactly one row and `/telemetry/history` aggregates in SQL.
                outage_samples = _agent_host_samples(agent_id, detected_at, restored_at)
                assert len(outage_samples) >= 2, (
                    "fewer than two raw host samples carry a collected_at inside the partition "
                    f"window ({detected_at} .. {restored_at}). Either the backlog was lost, or "
                    "it was restamped to reconnect time — which is exactly the failure "
                    "'original observation timestamp' exists to forbid"
                )
                # IDEMPOTENCY. Delivery out of the spool is at-least-once by
                # construction (peek, send, then commit — internal/link/outbound.go),
                # so "no duplicate rows" is a property of the backend's
                # (agent_id, sample_id, collected_at) dedupe. Checking sample_id
                # alone is the point: a redelivery that arrived with a REWRITTEN
                # collected_at satisfies that constraint and lands as a second row
                # under the same sample_id, which is precisely what a bucket-count
                # check cannot see.
                outage_ids = [sample_id for sample_id, _ in outage_samples]
                assert len(set(outage_ids)) == len(outage_ids), (
                    "a sample_id was persisted more than once inside the outage window — the "
                    "spool's at-least-once redelivery was not deduped: "
                    f"{sorted({i for i in outage_ids if outage_ids.count(i) > 1})}"
                )
                # ...and nothing that was already delivered before the cut was
                # re-ingested behind it.
                pre_cut_ids = [sample_id for sample_id, _ in samples_before_cut]
                assert not set(pre_cut_ids) & set(outage_ids), (
                    "a sample delivered before the partition was ingested again inside the "
                    "outage window"
                )

                # IMMEDIATE DUE PROBE RECOVERY, with nobody asking. No check-now, no
                # reassignment, no restart: the scheduler's next tick must find the
                # vantage ready again and a result must land.
                _wait_until(
                    lambda: _probe_eligible_row(client, agent_id, host=discovered_ip)["online"],
                    timeout=_PROBE_RECONNECT_BUDGET_S,
                )

                def _recovered() -> dict | None:
                    current = _monitor(client, icmp_id)
                    if current["probe_execution_status"] != "ready":
                        return None
                    if current["probe_last_result_at"] == result_at_before_cut:
                        return None
                    return current

                recovered_monitor = _wait_until_and_return(
                    _recovered, timeout=_PROBE_RECONNECT_BUDGET_S
                )
                assert recovered_monitor["probe_execution_reason"] is None, recovered_monitor
                assert recovered_monitor["status"] == "up", recovered_monitor
                assert set(_monitor_samples(client, icmp_id, "avail")) == {1.0}, (
                    "the outage left an avail=0 sample on the discovered device's monitor after all"
                )
                assert _uptime(client, icmp_id)["pct_24h"] == 100.0

                # ═════════════════════════════════════════════════════════════
                # Step 13: a second device appears after the first scan
                # ═════════════════════════════════════════════════════════════
                # `probe-target-new` starts on the subnet the agent ALREADY knows,
                # so nothing about the topology changes — the agent's routing table
                # is identical and only the set of hosts answering on 10.77.0.0/24
                # is different. That is what makes this "a genuinely new device"
                # rather than "a new subnet", which is a different case entirely.
                routes_before_new_host = _agent_route_networks()
                _up_fixture_target(_PROBE_TARGET_NEW_SERVICE)
                assert _agent_route_networks() == routes_before_new_host, (
                    "starting a second host on probe-net changed the agent's routing table — it "
                    "is not on the subnet the agent already knows"
                )
                # Doubles as a settle for the new container's netns, and re-asserts
                # the premise for the address the recurring sweep is about to find.
                _assert_backend_cannot_reach(_PROBE_TARGET_NEW_IP, _PROBE_NET_CIDR)
                assert not [
                    r
                    for r in _job_results(client, initial_job_id)
                    if r["ip_address"] == _PROBE_TARGET_NEW_IP
                ], (
                    f"the first sweep already reported {_PROBE_TARGET_NEW_IP}, so it is not the "
                    "device-that-appeared-later this step needs"
                )

                hardware_last_seen_before = _hardware_row(client, hardware_id)["last_seen"]
                recurring_id = _run_profile_now(client, probe_profile["id"])["id"]
                assert recurring_id != initial_job_id
                _wait_until(
                    lambda: _scan_job(client, recurring_id)["status"] == "completed",
                    timeout=_RECURRING_SCAN_BUDGET_S,
                )
                recurring = _scan_job(client, recurring_id)
                assert recurring["scan_agent_id"] == agent_id, recurring
                rows = {row["ip_address"]: row for row in _job_results(client, recurring_id)}
                assert _PROBE_TARGET_IP in rows and _PROBE_TARGET_NEW_IP in rows, (
                    f"the recurring sweep did not report both fixtures: {sorted(rows)}"
                )

                # The device the inventory already knows comes back MATCHED, against
                # the row the import created, and creates nothing.
                known = rows[_PROBE_TARGET_IP]
                # `conflict`, not `matched`, and the cause is this journey's own
                # doing rather than a defect: step 7 renamed the imported row to
                # _GATE_HARDWARE_NAME, so the hostname the agent reports now
                # disagrees with the one the inventory stores, and the matcher says
                # so. That is the established contract — `_rename_hardware`'s own
                # docstring calls the disagreement its purpose, and
                # test_agent_e2e.py's
                # test_agent_discovery_reconnects_per_agent_and_requeues_only_changes
                # pins `state == "conflict"` for exactly this sequence.
                #
                # What step 13 is really about survives intact and is asserted
                # below: the device is RECOGNISED (matched to the same Hardware
                # row, id and all), no second row is created, and it is not
                # reported as `new`. A conflict is a recognised device with a field
                # to reconcile; only `new` means "the inventory has never seen
                # this".
                assert known["state"] == "conflict", (
                    "a device already in the inventory, renamed by this journey, came back as "
                    f"{known['state']!r} — expected `conflict`: {known}"
                )
                assert known["state"] != "new", (
                    "a device the inventory already holds was reported as new, which is what "
                    f"would put a duplicate in front of an operator: {known}"
                )
                assert (known["matched_entity_type"], known["matched_entity_id"]) == (
                    "hardware",
                    hardware_id,
                ), known
                assert [h["id"] for h in _hardware_with_ip(client, _PROBE_TARGET_IP)] == [
                    hardware_id
                ], "the recurring sweep created a second Hardware row for a known device"

                # The genuinely new one comes back NEW, into the ordinary review
                # queue, and is NOT imported by anything but a person.
                fresh = rows[_PROBE_TARGET_NEW_IP]
                assert fresh["state"] == "new" and fresh["matched_entity_id"] is None, fresh
                assert fresh["merge_status"] == "pending", fresh
                assert any(row["id"] == fresh["id"] for row in _review_queue(client)), (
                    "the new device is not in the ordinary review queue, which is the one place "
                    "an operator is asked to look"
                )
                assert not _hardware_with_ip(client, _PROBE_TARGET_NEW_IP), (
                    "the recurring sweep imported the new device by itself — plan §5 requires an "
                    "agent-authored row to reach the inventory only when a user accepts it"
                )
                assert recurring["hosts_new"] >= 1, recurring
                # One conflict, and exactly the one this journey created by renaming
                # the imported row — see the `known` block above.
                assert recurring["hosts_conflict"] == 1, (
                    "expected exactly the one conflict this journey's own rename causes: "
                    f"{recurring}"
                )

                # THE `last_seen` HALF, PINNED AS THE CURRENT CONTRACT.
                # §8 step 13 asks for the known device's `last_seen` to be updated
                # while only the new one enters review. On the AGENT path that does
                # not happen today, and the reason is specific rather than
                # incidental: `_auto_merge_known_devices` is reachable only from
                # `_scan_finalize`, an agent job is closed by `finalize_agent_job`,
                # and that function documents never calling it at any setting
                # (`tests/services/test_agent_discovery_ingest.py::
                # test_finalization_never_auto_merges_however_the_setting_is_left`
                # pins it). So the known device is re-queued and its `last_seen` is
                # not refreshed. Both halves are asserted as they actually are, with
                # messages that say so: if either changes, this fails and points at
                # the decision that changed rather than silently blessing it.
                assert known["merge_status"] == "pending", (
                    "an agent-executed recurring scan auto-updated a known unchanged device out "
                    "of the review queue. That IS what §8 step 13 asks for, and it is NOT what "
                    "`finalize_agent_job` does today. Something changed on purpose: update this "
                    f"assertion rather than reverting the change. Row: {known}"
                )
                assert _hardware_row(client, hardware_id)["last_seen"] == hardware_last_seen_before, (
                    "an agent-executed scan refreshed Hardware.last_seen. §8 step 13 asks for "
                    "exactly that and `finalize_agent_job` does not do it today — see the note "
                    "on `merge_status` above"
                )
                # No duplicate topology node came out of the second sighting either.
                assert _topology_nodes(client).count(node_id) == 1

                # ═════════════════════════════════════════════════════════════
                # Step 14: restart agent and backend INDEPENDENTLY; presence,
                #          profiles, schedules and grants reconcile without
                #          duplication, with all four slices' state live at once
                # ═════════════════════════════════════════════════════════════
                # "Independently" is the load-bearing word: two separate restarts,
                # each followed by its own reconciliation, and `restart` rather than
                # `down`/`up` throughout — the Postgres data, the vault key, the
                # agent's approval and the agent's state volume all have to survive,
                # and a recreate would additionally undo the runtime network
                # attachment step 15 depends on.
                profiles_before_restart = _discovery_profiles(client, agent_id)
                all_profiles_before_restart = _all_profiles(client)
                agent_before_restart = client.get(f"/api/v1/agents/{agent_id}").json()
                hardware_before_restart = _hardware_identity(client, hardware_id)
                provenance_before_restart = _result_provenance()
                monitor_assignments_before = {
                    name: _monitor(client, created["id"])["probe_agent_id"]
                    for name, created in monitors.items()
                }

                # Quiescence first: the bootstrap and the recurring sweep must not
                # still be running underneath a restart, or "no duplicate jobs"
                # would be a statement about a race.
                _wait_until(
                    lambda: not _unfinished_agent_jobs(client, agent_id),
                    timeout=_INITIAL_SCAN_BUDGET_S,
                )

                # ---- the BACKEND, alone --------------------------------------
                subprocess.run([*COMPOSE, "restart", "circuitbreaker"], check=True, cwd=E2E_DIR)
                _wait_until(
                    lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=240
                )
                # No new bootstrap: the same admin credentials still work, which a
                # server that forgot its state could not offer. The token is taken
                # fresh and the client re-headered with it — not because the old one
                # is known to be invalid, but because "log in again and keep going"
                # is what an operator does across a restart, and a test that leaned
                # on a cached token would not have exercised it.
                token = _bootstrap_admin(client)
                headers = {"Authorization": f"Bearer {token}"}
                client.headers.update(headers)
                _wait_until(lambda: _agent_online(client, agent_id), timeout=_RECONNECT_BUDGET_S)

                # ---- the AGENT, alone ----------------------------------------
                # Read immediately before the restart and from the agent's own
                # status file: `compose restart` keeps the state volume, so the
                # container comes back to the status.json it left behind and a bare
                # `link_state == "accepted"` would be satisfied by the stale value
                # already in that file.
                status_updated_before = _agent_status()["updated_at"]
                subprocess.run([*COMPOSE, "restart", _AGENT_SERVICE], check=True, cwd=E2E_DIR)

                def _reconnected() -> bool:
                    status = _agent_status()
                    return (
                        status["link_state"] == "accepted"
                        and status["updated_at"] != status_updated_before
                    )

                _wait_until(_reconnected, timeout=_RECONNECT_BUDGET_S)
                _wait_until(lambda: _agent_online(client, agent_id), timeout=_RECONNECT_BUDGET_S)

                # PRESENCE reconciled, with no new identity anywhere.
                agent_after_restart = client.get(f"/api/v1/agents/{agent_id}").json()
                assert agent_after_restart["status"] == "active", agent_after_restart
                assert agent_after_restart["device_pk"] == agent_before_restart["device_pk"]
                assert agent_after_restart["enrolled_at"] == agent_before_restart["enrolled_at"]
                assert _device_key(_AGENT_SERVICE) == device_key_at_enrollment, (
                    "the agent's on-disk device.key changed across the restarts — it lost its "
                    "state volume and generated a new identity"
                )
                assert len(_enrolled_event_ids(client, agent_id)) == 1, (
                    "a second `enrolled` event was recorded across the restarts: "
                    f"{_enrolled_event_ids(client, agent_id)}"
                )
                assert agent_toml_path.read_text() == agent_toml_after_install, (
                    "agent.toml was edited — no manual agent-side configuration is allowed after "
                    "the generated command, restarts included"
                )

                # GRANTS reconciled: the same map, byte for byte, config included.
                assert _agent_capabilities(client, agent_id) == granted_at_approval, (
                    "the capability grants are not what approval applied, after two restarts. "
                    "The database is authoritative and the agent's local state is not: a grant "
                    "that drifted here would mean one of the two ends re-derived it"
                )
                _wait_until(
                    lambda: _agent_believes(
                        {"host_telemetry": True, "remote_probe": True, "local_discovery": True}
                    ),
                    timeout=_RECONNECT_BUDGET_S,
                )

                # PROFILES and SCHEDULES reconciled, WITHOUT DUPLICATION. The
                # reconnect re-ran the bootstrap pass (hello carries the same
                # network facts), which is exactly the thing that must be a no-op.
                assert {p["id"] for p in _discovery_profiles(client, agent_id)} == {
                    p["id"] for p in profiles_before_restart
                }, "a restart created or replaced a system-managed profile"
                assert len(_all_profiles(client)) == len(all_profiles_before_restart), (
                    "the installation gained a discovery profile across the restarts"
                )
                _system_profile_for(client, agent_id, _PROBE_NET_CIDR)
                _system_profile_for(client, agent_id, _AGENT_NET_CIDR)
                assert (
                    _system_profile_for(client, agent_id, _PROBE_NET_CIDR)["schedule_cron"]
                    == expected_cron
                ), "the derived six-hourly cadence did not survive the restarts"
                # A cron that only lived in the replaced backend process's scheduler
                # state would be gone: `_register_discovery_profile_crons` runs at
                # start-up, and this is the assertion that it did.
                next_scheduled = _discovery_status(client)["next_scheduled"]
                assert next_scheduled is not None, (
                    "no discovery profile is registered with APScheduler after the backend "
                    "restarted, so the six-hourly cadence exists only as a column and will "
                    "never fire again"
                )
                assert _parse_ts(next_scheduled) > datetime.now(timezone.utc), next_scheduled
                bootstrap_jobs = [
                    j
                    for j in _scan_jobs(client, profile_id=probe_profile["id"])
                    if j["triggered_by"] == "bootstrap"
                ]
                assert len(bootstrap_jobs) == 1, (
                    "a reconnect queued another automatic first scan: "
                    f"{[j['id'] for j in bootstrap_jobs]}"
                )

                # ALL FOUR SLICES LIVE AT ONCE, after both restarts. This is the
                # part no per-slice test can assert, and it is asserted as four
                # things being simultaneously true of one running system.
                #  1 (Slice 1) the link is up and the identity is the same one:
                assert _agent_status()["link_state"] == "accepted"
                #  2 (Slice 2) telemetry is flowing again, with a sample newer than
                #    the restart:
                restart_watermark = datetime.now(timezone.utc)
                _wait_until(
                    lambda: _parse_ts(
                        _agent_telemetry(client, agent_id)["latest"]["collected_at"]
                    )
                    > restart_watermark,
                    timeout=_FIRST_SAMPLE_BUDGET_S,
                )
                #  3 (Slice 3) the agent-vantage monitors on the discovered device
                #    still hold their assignment and are producing results again:
                assert {
                    name: _monitor(client, created["id"])["probe_agent_id"]
                    for name, created in monitors.items()
                } == monitor_assignments_before, (
                    "a restart changed which vantage a monitor is assigned to"
                )
                _wait_until(
                    lambda: _parse_ts(_monitor(client, icmp_id)["probe_last_result_at"])
                    > restart_watermark,
                    timeout=_PROBE_RECONNECT_BUDGET_S,
                )
                assert _monitor(client, icmp_id)["status"] == "up"
                #  4 (Slice 4) the imported inventory row, its topology placement and
                #    its provenance are untouched by any of it:
                assert _hardware_identity(client, hardware_id) == hardware_before_restart, (
                    "the restarts changed the imported Hardware row"
                )
                assert _topology_nodes(client).count(node_id) == 1
                assert _result_provenance() == provenance_before_restart, (
                    "the restarts rewrote discovery result provenance"
                )

                # ═════════════════════════════════════════════════════════════
                # Step 15: change the agent's IP inside its subnet; identity and
                #          provenance stay stable
                # ═════════════════════════════════════════════════════════════
                # The subnet is deliberately unchanged and only the host part moves.
                # That is the shape that can actually break something: the CIDR the
                # agent reports in every `hello` — and therefore the
                # `normalized_cidr` half of D-7's partial unique index — is
                # identical, so an implementation that keyed a system profile, a
                # dispatch lease or an identity on anything address-shaped mints a
                # second profile for 10.88.0.0/24 exactly here and nowhere else.
                #
                # The move is made on agent-net because that is the network
                # `_agent_network_name` can resolve and the one an operator would
                # see the agent move on; probe-net, the fixture subnet, is
                # deliberately left alone so that "the agent moved" cannot be
                # confused with "the fixtures moved".
                identity_before_move = client.get(f"/api/v1/agents/{agent_id}").json()
                provenance_before_move = _result_provenance()
                profiles_before_move = _discovery_profiles(client, agent_id)
                old_ip, new_ip = _change_agent_address(_AGENT_NET_MOVED_IP)

                # hostinfo.Collect() runs once per link connection, so the new
                # address reaches the server on the agent's NEXT hello and not
                # before. `restart`, never `up --force-recreate`: the address itself
                # is a runtime attachment on this container.
                status_updated_before_move = _agent_status()["updated_at"]
                subprocess.run([*COMPOSE, "restart", _AGENT_SERVICE], check=True, cwd=E2E_DIR)
                _wait_until(
                    lambda: (
                        _agent_status()["link_state"] == "accepted"
                        and _agent_status()["updated_at"] != status_updated_before_move
                    ),
                    timeout=_RECONNECT_BUDGET_S,
                )
                _wait_until(lambda: _agent_online(client, agent_id), timeout=_RECONNECT_BUDGET_S)

                # The move really happened, asserted from the BACKEND's own network
                # namespace rather than from `docker inspect` metadata: it can reach
                # the new address and can no longer reach the old one.
                moved = _backend_sh(f"ping -c 2 -W 2 {new_ip}")
                assert moved.returncode == 0, (
                    f"the backend cannot reach the agent at its new address {new_ip}: "
                    f"{moved.stdout!r} {moved.stderr!r}"
                )
                vacated = _backend_sh(f"ping -c 2 -W 2 {old_ip}")
                assert vacated.returncode != 0, (
                    f"{old_ip} still answers, so the agent did not actually leave its old "
                    f"address: {vacated.stdout!r} {vacated.stderr!r}"
                )
                # ...and it moved WITHIN the subnet, asserted from the agent's own
                # kernel routing table, which is what makes this an address change
                # rather than a subnet change.
                assert ipaddress.ip_address(new_ip) in ipaddress.ip_network(_AGENT_NET_CIDR)
                assert _agent_route_networks() == {_AGENT_NET_CIDR, _PROBE_NET_CIDR}, (
                    "the agent's routing table changed, so this is a subnet change rather than "
                    f"the address change the duplication risk is about: {_agent_route_networks()}"
                )

                # IDENTITY stable.
                identity_after_move = client.get(f"/api/v1/agents/{agent_id}").json()
                assert identity_after_move["device_pk"] == identity_before_move["device_pk"]
                assert identity_after_move["enrolled_at"] == identity_before_move["enrolled_at"]
                assert identity_after_move["status"] == "active"
                assert _device_key(_AGENT_SERVICE) == device_key_at_enrollment
                assert len(_agents(client)) == 1
                assert len(_enrolled_event_ids(client, agent_id)) == 1

                # PROVENANCE stable: every discovery result still names the agent it
                # named before the move, and the imported row is untouched. An
                # address is not an identity, and nothing that was attributed to
                # this agent may be re-attributed because it moved.
                assert _result_provenance() == provenance_before_move, (
                    "changing the agent's address rewrote discovery result provenance"
                )
                assert _automatic_scope(client, agent_id) == {_AGENT_NET_CIDR, _PROBE_NET_CIDR}, (
                    "the derived scope changed when only the agent's host address did"
                )
                assert {p["id"] for p in _discovery_profiles(client, agent_id)} == {
                    p["id"] for p in profiles_before_move
                }, "the address change created or replaced a system profile"
                _system_profile_for(client, agent_id, _AGENT_NET_CIDR)
                assert _hardware_identity(client, hardware_id) == hardware_before_restart
                # And the vantage still works from its new address, which is the
                # product consequence: monitors do not care where the agent lives.
                move_watermark = datetime.now(timezone.utc)
                _wait_until(
                    lambda: _parse_ts(_monitor(client, icmp_id)["probe_last_result_at"])
                    > move_watermark,
                    timeout=_PROBE_RECONNECT_BUDGET_S,
                )
                assert _monitor(client, icmp_id)["status"] == "up"

                # ═════════════════════════════════════════════════════════════
                # Step 17 (EXECUTED HERE, BEFORE STEP 16 — see below): upgrade the
                #          agent without losing enrollment or historical data
                # ═════════════════════════════════════════════════════════════
                # WHY OUT OF ORDER. Revocation is terminal by construction:
                # `api/agents.py`'s `post_revoke` closes the socket, cancels the
                # probe runs and closes the discovery dispatches, and
                # `api/ws_agents.py`'s `link_stream` then refuses any agent whose
                # status is not `active`. An update dispatched to a revoked agent
                # could never be delivered, so step 17 after step 16 would be
                # unrunnable rather than merely awkward. It is therefore run here,
                # against the same live journey state, and step 16 closes the file.
                #
                # WHAT IS NOT ASSERTED HERE, AND WHY. The forced-rollback half is
                # deliberately not re-implemented in this gate. Two independent
                # reasons: (1) driving it needs `CB_AGENT_TEST_PRE_REEXEC_DELAY_MS`,
                # which is read at container-create time, so injecting it mid-journey
                # means `up -d` recreating cb-agent — which would discard the runtime
                # `--ip` attachment step 15 just proved and reset the agent's address
                # underneath every later assertion; and (2) it is finalization item
                # 1's own subject (F-8, red with two undiagnosed failure modes), and
                # folding it in would make this gate's signal a statement about F-8
                # rather than about whether the four slices compose. It stays owned
                # by `test_agent_e2e.py::test_agent_update_success_and_forced_rollback`.
                # What this block asserts instead is the property the rollback case
                # shares and that only a full journey can pose: a version change
                # loses neither the enrollment nor any of the four slices' history.
                version_before_update = _agent_status()["version"]
                assert version_before_update == "0.0.0-dev", (
                    "the running agent is not the e2e image's unversioned build, so the "
                    "manifest's baked version is not a genuine upgrade target: "
                    f"{version_before_update}"
                )
                # ...and the target is a DIFFERENT version from the running one.
                # Without this the `status.json` wait below is a tautology of exactly
                # the shape that has already produced one false pass in this suite:
                # `status.json` is written by the daemon and survives a restart, so
                # if `baked_version` ever equalled the running version the wait would
                # be satisfied by the value the PREVIOUS process left in the file,
                # instantly, whether or not a single byte of the binary changed.
                assert baked_version != version_before_update, (
                    f"the manifest's baked agent version is {baked_version!r}, which is what "
                    "the daemon is already running. Every 'the upgrade landed' assertion below "
                    "would then be satisfied by the status.json the pre-update process wrote. "
                    "Dockerfile.mono's agent-builder stage must produce a version distinct from "
                    "e2e/Dockerfile's 0.0.0-dev baseline"
                )
                history_before_update = {
                    "hardware": _hardware_identity(client, hardware_id),
                    "provenance": _result_provenance(),
                    "profiles": {p["id"] for p in _discovery_profiles(client, agent_id)},
                    "topology": _topology_nodes(client).count(node_id),
                    "samples": len(
                        _agent_host_samples(
                            agent_id,
                            first_sample_at - timedelta(seconds=1),
                            datetime.now(timezone.utc),
                        )
                    ),
                    "icmp_runs": len(_probe_runs(client, icmp_id)),
                }

                update = client.post(f"/api/v1/agents/{agent_id}/update", json={}, headers=headers)
                assert update.status_code == 200, update.text
                assert update.json()["version"] == baked_version, update.json()
                _wait_until(
                    lambda: _agent_status().get("version") == baked_version,
                    timeout=_UPDATE_BUDGET_S,
                )
                _wait_until(
                    lambda: _agent_status()["link_state"] == "accepted", timeout=_UPDATE_BUDGET_S
                )
                _wait_until(
                    lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                    timeout=_UPDATE_BUDGET_S,
                )
                assert any(
                    e["event_type"] == "version_changed"
                    and (e.get("detail") or {}).get("version") == baked_version
                    for e in _agent_events(client, agent_id)
                ), f"no version_changed event for {baked_version}"

                # ENROLLMENT SURVIVED: same identity, no new pairing code, no config
                # edit. The re-exec'd process is the same agent.
                assert _device_key(_AGENT_SERVICE) == device_key_at_enrollment, (
                    "the update replaced the agent's device key — the upgraded binary is a "
                    "different identity, and the enrollment did not survive"
                )
                assert len(_agents(client)) == 1
                assert len(_enrolled_event_ids(client, agent_id)) == 1
                assert agent_toml_path.read_text() == agent_toml_after_install
                assert _agent_capabilities(client, agent_id) == granted_at_approval, (
                    "the upgrade changed the agent's grants"
                )

                # HISTORICAL DATA SURVIVED, across all four slices. Sample and run
                # counts are floors, not equalities: the journey keeps running while
                # the update lands, so they may only grow.
                assert _hardware_identity(client, hardware_id) == history_before_update["hardware"]
                assert _result_provenance() == history_before_update["provenance"]
                assert {p["id"] for p in _discovery_profiles(client, agent_id)} == (
                    history_before_update["profiles"]
                )
                assert _topology_nodes(client).count(node_id) == history_before_update["topology"]
                assert (
                    len(
                        _agent_host_samples(
                            agent_id,
                            first_sample_at - timedelta(seconds=1),
                            datetime.now(timezone.utc),
                        )
                    )
                    >= history_before_update["samples"]
                ), "host telemetry history was lost across the upgrade"
                assert len(_probe_runs(client, icmp_id)) >= history_before_update["icmp_runs"], (
                    "probe run history was lost across the upgrade"
                )
                # The one thing an unbuilt/mis-injected binary would also produce is
                # "nothing happened", so the new binary is asked to do real work
                # before this step is called done.
                update_watermark = datetime.now(timezone.utc)
                _wait_until(
                    lambda: _parse_ts(
                        _agent_telemetry(client, agent_id)["latest"]["collected_at"]
                    )
                    > update_watermark,
                    timeout=_FIRST_SAMPLE_BUDGET_S,
                )
                _wait_until(
                    lambda: _parse_ts(_monitor(client, icmp_id)["probe_last_result_at"])
                    > update_watermark,
                    timeout=_PROBE_RECONNECT_BUDGET_S,
                )

                # ═════════════════════════════════════════════════════════════
                # Step 16: disable discovery DURING a scan, and THEN revoke the
                #          agent — one continuous act; cancellation and rejection
                #          of late frames across ALL capability handlers
                # ═════════════════════════════════════════════════════════════
                # THE HARD PART IS PROVING WHO ENFORCED IT. `discovery.cancel` is
                # best-effort by design (plan §4), so on the ordinary path the agent
                # receives it, stops, and sends nothing more — and the database then
                # looks exactly as it would if the backend enforced nothing at all.
                # A passing test on that path proves only that the agent is well
                # behaved. So the cancel is taken away: the sweep is put under a
                # depth that keeps it running for minutes, the agent's only route to
                # the server is severed (a black hole — no FIN, no RST, nothing it
                # can learn from a write), and the capabilities are withdrawn while
                # it is deaf. Its own status.json is read inside the partition to
                # prove it never heard.
                #
                # ALL THREE capabilities are withdrawn, not just discovery, because
                # "across all capability handlers" is a claim about
                # `CAPABILITY_FOR_TYPE`'s three entries: the agent goes on producing
                # a `discovery.finding`, a `telemetry.host` and a `probe.result`
                # for grants the server has already closed, and `dispatch_frame`
                # must audit one refusal per frame for each.
                #
                # THE REVOKE COMES AFTER THE DELIVERY, INSIDE THE SAME CONTINUOUS
                # BLOCK, and that ordering is forced rather than chosen: a revoked
                # agent cannot open a /link connection at all (`link_stream` refuses
                # any non-active agent), so revoking first would leave the late
                # frames undeliverable and the per-handler rejection unobservable.
                # Nothing is re-set-up between the two halves; it is one journey.
                assert _agent_believes(
                    {"host_telemetry": True, "remote_probe": True, "local_discovery": True}
                ), (
                    "the agent does not hold all three grants going in, so the withdrawals below "
                    f"would prove nothing: {_agent_status().get('grants')}"
                )

                # Quiescence, then a sweep slow enough that "mid-scan" is not a race.
                # `_CANCEL_DISCOVERY_CONFIG` is the harness's own derivation for
                # this: one host at a time at the grant's 10s per-host maximum, so
                # the sweep is still finding hosts long after internal/link's 60s
                # read deadline has taken the partitioned link down — which is what
                # makes the late findings SPOOLED rather than written into the void.
                _wait_until(
                    lambda: not _unfinished_agent_jobs(client, agent_id),
                    timeout=_INITIAL_SCAN_BUDGET_S,
                )
                _put_local_discovery(client, headers, agent_id, _CANCEL_DISCOVERY_CONFIG)
                doomed_job_id = _run_profile_now(client, probe_profile["id"])["id"]
                _wait_until(
                    lambda: _scan_job(client, doomed_job_id)["status"] == "running"
                    and len(_job_results(client, doomed_job_id)) >= 1,
                    timeout=_INITIAL_SCAN_BUDGET_S,
                    interval=0.5,
                )
                # An in-flight probe run too, so there is a `probe.result` to be
                # late with. The slow monitor's check outlives the partition's
                # detection window by construction.
                # 200, never "200 or 409". D-14 answers 409 when the vantage cannot
                # take the check, and the slow monitor's own interval is 3600s — so
                # a 409 here means no run will EVER be dispatched and the wait below
                # would burn its whole budget before failing with "no dispatched
                # run", which describes the symptom and not the cause. The agent is
                # online, granted and ready at this point (it produced a fresh probe
                # result a moment ago, at the end of step 17), so 200 is the only
                # correct answer and anything else is the finding.
                # Nothing may be in flight when check-now is issued. D-6 enforces
                # one active run per monitor in the DATABASE
                # (`uq_monitor_probe_runs_active`, partial on
                # `status IN ('queued','dispatched')`), so a monitor that already
                # has one answers 409 `previous_run_in_flight` — which is what this
                # step hit on its first real run, and it is not the 409 the comment
                # below is about.
                #
                # The run in the way is a legitimate one: step 12's reconnect makes
                # every assigned monitor immediately due, so the slow monitor was
                # re-dispatched then, and its own 100s timeout means it stays
                # `dispatched` for a while. It clears when the reconciliation pass
                # expires the lease — `coalesce(deadline_at, scheduled_at) < now -
                # RESULT_TIMEOUT_GRACE_S` (services/monitoring/probe_reconcile.py,
                # grace = agent_probe.LATE_RESULT_GRACE = 30s) — so the wait is the
                # check's own 100s timeout plus that 30s plus room for the tick.
                # Waiting is deterministic; branching on "is one already in flight"
                # would leave whichever path did not run untested.
                _wait_until(
                    lambda: not [
                        r
                        for r in _probe_runs(client, slow_id)
                        if r["status"] in ("queued", "dispatched")
                    ],
                    timeout=_PROBE_LEASE_EXPIRY_BUDGET_S,
                    interval=2.0,
                )
                check_now = client.post(f"/api/v1/monitors/{slow_id}/check")
                assert check_now.status_code == 200, (
                    "check-now refused to dispatch to the agent vantage, so there is no "
                    "in-flight probe.result for the withdrawal below to be late with: "
                    f"{check_now.status_code} {check_now.text}"
                )
                in_flight_late = _wait_until_and_return(
                    lambda: _dispatched_run(slow_id, frozenset({in_flight["run_id"]})),
                    timeout=_PROBE_FIRST_RESULT_BUDGET_S,
                )
                assert in_flight_late["agent_id"] == agent_id, in_flight_late
                assert in_flight_late["run_id"] != in_flight["run_id"], (
                    "the run picked up here is step 10's, not a fresh one — it is long past its "
                    "lease, so nothing about it could be 'in flight when the capability was "
                    f"withdrawn': {in_flight_late}"
                )

                # The spool is drained to a known floor BEFORE the cut, so that
                # `_undelivered_frames()` inside it means "the work the agent
                # produced after the withdrawal" exactly rather than approximately.
                # Step 10's outage, step 14's two restarts, step 15's address change
                # and step 17's re-exec each spooled and drained a backlog through
                # this same file; `queue.jsonl` keeps every one of those as a
                # consumed prefix, and an undelivered straggler left over from any of
                # them would be counted below as a late frame the withdrawal caused.
                # (`_spool_fully_delivered` IS `queue.head == len(queue.jsonl)`, so
                # this is the same statement as "`_undelivered_frames()` is empty" —
                # said once, in the form the harness already derives.)
                _wait_until(_spool_fully_delivered, timeout=_SPOOL_DRAIN_BUDGET_S)

                violations_before = {
                    capability: _capability_violations(client, agent_id, frame_type)
                    for capability, frame_type in _CAPABILITY_FRAME_TYPES.items()
                }

                with _cut_agent_network():
                    # The agent is deaf from here. Everything the backend does next
                    # it does alone.
                    _set_local_discovery_enabled(client, headers, agent_id, False)

                    cancelled_job = _scan_job(client, doomed_job_id)
                    assert cancelled_job["status"] == "cancelled", (
                        "disabling local_discovery left the running dispatch open — D-14 "
                        f"requires it closed in the same transaction: {cancelled_job}"
                    )
                    assert cancelled_job["error_reason"] == "capability_disabled", cancelled_job
                    # `dispatch_status` is the column the refusal is actually made
                    # of and `ScanJobOut` does not carry it, so a test that asserted
                    # `status == "cancelled"` and stopped there would not have
                    # checked the mechanism.
                    assert _job_dispatch_state(doomed_job_id) == ("cancelled", "cancelled"), (
                        "the job's dispatch_status did not close with it, and that is what "
                        "`agent_discovery` reads to refuse a late finding: "
                        f"{_job_dispatch_state(doomed_job_id)}"
                    )

                    # The other two grants go too, while it still cannot hear.
                    _set_capability_enabled(client, headers, agent_id, "host_telemetry", False)
                    _set_capability_enabled(client, headers, agent_id, "remote_probe", False)

                    # The witness that none of it was delivered. Without this, every
                    # assertion below is equally consistent with a cooperative agent
                    # that simply stopped.
                    assert _agent_believes(
                        {"host_telemetry": True, "remote_probe": True, "local_discovery": True}
                    ), (
                        "the agent already knows its grants were withdrawn while its only route "
                        "to the server is severed, so this is not a test of server-side "
                        "enforcement — it is a test of a well-behaved agent"
                    )

                    # Nothing else can reach the server now, so this is the last
                    # word on what each dispatch accepted while it was authorised.
                    results_at_cut = _job_results(client, doomed_job_id)
                    addresses_at_cut = {row["ip_address"] for row in results_at_cut}
                    samples_at_cut = _agent_host_samples(
                        agent_id,
                        first_sample_at - timedelta(seconds=1),
                        datetime.now(timezone.utc),
                    )

                    # ...and the agent, knowing nothing, keeps working for grants
                    # that no longer exist. All three kinds of late frame have to be
                    # physically on disk before the route comes back, or "no new
                    # rows" would be indistinguishable from "nothing was ever sent".
                    def _late_findings() -> list[dict]:
                        return [
                            payload
                            for frame in _spooled_of_type(
                                _undelivered_frames(), "discovery.finding"
                            )
                            for payload in [frame.get("payload") or {}]
                            if payload.get("scan_job_id") == doomed_job_id
                            and payload.get("kind") == "host"
                            and payload.get("ip_address") not in addresses_at_cut
                        ]

                    _wait_until(_late_findings, timeout=_LATE_FINDING_BUDGET_S, interval=2.0)
                    late_findings = _late_findings()
                    late_addresses = sorted({f["ip_address"] for f in late_findings})

                    # The findings arrive first — a connect sweep reports each dead
                    # address as it times out — but the probe.result cannot appear
                    # until the slow check itself finishes, and that check is slow
                    # BY DESIGN: its target sleeps longer than the monitor's own
                    # 100s timeout, so the run ends on that timeout and only then is
                    # a result framed. Asserting on it the moment the findings land
                    # races a duration the test itself chose. Same for the host
                    # sample, whose cadence is the grant's interval.
                    _wait_until(
                        lambda: _spooled_of_type(_undelivered_frames(), "probe.result")
                        and _spooled_of_type(_undelivered_frames(), "telemetry.host"),
                        timeout=_LATE_RESULT_SPOOL_BUDGET_S,
                        interval=2.0,
                    )

                    spooled_now = _undelivered_frames()
                    _assert_spool_holds_only_data_frames(spooled_now)
                    late_samples = _spooled_of_type(spooled_now, "telemetry.host")
                    late_results = _spooled_of_type(spooled_now, "probe.result")
                    assert late_samples, (
                        "no host sample was spooled during the partition, so the telemetry.host "
                        "handler has nothing to refuse and 'all capability handlers' would be a "
                        "claim about two of them"
                    )
                    assert late_results, (
                        "the in-flight check produced no spooled probe.result, so the "
                        "probe.result handler has nothing to refuse"
                    )
                    assert _agent_believes({"local_discovery": True}), (
                        "the agent learned about the withdrawal part-way through the partition, "
                        "so what it spooled is not unambiguously post-withdrawal work"
                    )

                    # The in-flight run's final server-side shape, snapshotted HERE
                    # rather than at the moment of the cut. The reconciliation pass
                    # legitimately retires a run once its lease is up (deadline_at =
                    # scheduled_at + 20s, plus a 30s grace), and by now the
                    # partition has lasted the read deadline plus the sweep's
                    # ten-seconds-per-dead-address march — minutes past that. A
                    # snapshot taken at the cut would still have been `dispatched`
                    # and would then change for a reason that has nothing to do with
                    # the late result, which is the only change the comparison after
                    # the reconnect is allowed to attribute to it.
                    def _slow_run() -> dict:
                        return next(
                            run
                            for run in _probe_runs(client, slow_id)
                            if run["run_id"] == in_flight_late["run_id"]
                        )

                    _wait_until(
                        lambda: _slow_run()["status"] not in ("queued", "dispatched"),
                        timeout=_PROBE_UNAVAILABLE_BUDGET_S,
                    )
                    slow_run_at_cut = _slow_run()

                # ---- the route returns and the agent delivers all of it -------
                _wait_until(
                    lambda: _agent_status()["link_state"] == "accepted",
                    timeout=_RECONNECT_BUDGET_S,
                )
                _wait_until(_spool_fully_delivered, timeout=_SPOOL_DRAIN_BUDGET_S)

                # ONE AUDITED REFUSAL PER FRAME, PER HANDLER. `dispatch_frame`
                # writes exactly one `capability_violation` per frame it drops for a
                # withdrawn grant, with the frame's wire type in `detail` — and it
                # is NOT rate-limited (unlike `recordable_violation`, which guards
                # the malformed-payload paths), so counting is meaningful. This is
                # the distinction that matters: without a refusal per frame, "no new
                # rows" is equally consistent with the frames never having arrived,
                # and those two outcomes leave an identical database. Waited for
                # rather than read once, because the agent commits a spooled frame
                # as soon as it has written it to the wire, so the disk can be
                # drained a moment before the server has finished refusing what came
                # off it.
                expected_refusals = {
                    "local_discovery": len(late_findings),
                    "host_telemetry": len(late_samples),
                    "remote_probe": len(late_results),
                }

                def _new_violations(capability: str) -> list[int]:
                    frame_type = _CAPABILITY_FRAME_TYPES[capability]
                    return sorted(
                        set(_capability_violations(client, agent_id, frame_type))
                        - set(violations_before[capability])
                    )

                for capability, expected in expected_refusals.items():
                    _wait_until(
                        lambda capability=capability, expected=expected: len(
                            _new_violations(capability)
                        )
                        >= expected,
                        timeout=_RECONNECT_BUDGET_S,
                    )
                    assert len(_new_violations(capability)) >= expected, (
                        f"the backend audited {len(_new_violations(capability))} refusals for the "
                        f"{expected} late {_CAPABILITY_FRAME_TYPES[capability]} frame(s) the agent "
                        f"delivered after {capability} was withdrawn. Every capability handler "
                        "must refuse per frame, or 'no new rows' proves nothing"
                    )

                # AND NOT ONE OF THEM BECAME A ROW.
                assert _job_dispatch_state(doomed_job_id) == ("cancelled", "cancelled"), (
                    "delivering the spooled findings reopened the cancelled job"
                )
                assert _job_results(client, doomed_job_id) == results_at_cut, (
                    "the cancelled job's result rows changed when the agent delivered its "
                    "backlog; every one of those frames was produced after the dispatch closed"
                )
                assert not [
                    row
                    for row in _job_results(client, doomed_job_id)
                    if row["ip_address"] in late_addresses
                ], (
                    f"an address the agent reported only AFTER the cancellation ({late_addresses}) "
                    "has a result row on the cancelled job"
                )
                assert (
                    _agent_host_samples(
                        agent_id,
                        first_sample_at - timedelta(seconds=1),
                        datetime.now(timezone.utc),
                    )
                    == samples_at_cut
                ), "a host sample was persisted for an agent whose host_telemetry grant was gone"
                assert (
                    next(
                        r
                        for r in _probe_runs(client, slow_id)
                        if r["run_id"] == in_flight_late["run_id"]
                    )
                    == slow_run_at_cut
                ), "the late probe result was applied to a run whose grant had been withdrawn"

                # Only now, and only because it reconnected, does the agent find out
                # — the order is the point: the rejections happened first and did
                # not depend on it.
                _wait_until(
                    lambda: _agent_believes(
                        {"host_telemetry": False, "remote_probe": False, "local_discovery": False}
                    ),
                    timeout=_RECONNECT_BUDGET_S,
                )
                assert _discovery_view(client, agent_id)["granted"] is False

                # ---- what this harness cannot inject, stated rather than faked --
                # The required assertion reads "server and agent independently
                # reject out-of-scope, cross-agent, stale, malformed and oversized
                # frames." Three of those five are driven above and below and are
                # real end-to-end proofs:
                #   * STALE — the late findings for a closed dispatch, just asserted;
                #   * OUT-OF-SCOPE — asserted in step 8, on the server's own
                #     eligibility evaluator, with `remote_probe` still granted so
                #     that the refusal reason is about scope and not about the
                #     withdrawal this block performs; restated below on `in_scope`,
                #     which is computed independently of `eligible`;
                #   * CROSS-AGENT — asserted in the closing block, on
                #     `scan_results.discovery_agent_id` against the subnets the
                #     reporter can physically reach.
                # MALFORMED and OVERSIZED are NOT expressible here, and no assertion
                # below pretends otherwise. The only frame-injection point this
                # harness has is the agent's own spool, and the agent re-encodes only
                # frames it produced itself; putting a malformed or oversized frame on
                # the wire would mean minting a Noise session, which nothing in this
                # harness can do. Both ends are pinned by named unit tests that inject
                # bytes directly — backend:
                #   tests/services/test_agent_discovery_ingest.py::
                #     test_oversized_finding_is_rejected_before_the_payload_is_parsed
                #   tests/services/test_agent_discovery_ingest.py::
                #     test_malformed_finding_is_a_protocol_violation
                #   tests/api/test_ws_agents_link.py::
                #     test_malformed_heartbeat_payload_does_not_tear_down_the_link
                #   tests/services/test_agent_telemetry.py::
                #     test_malformed_readiness_payload_records_a_protocol_violation
                # and agent: internal/frame's TestDecode_RejectsMalformedJSON and
                # internal/collect/probe's TestProbeRuntime_OutOfScopeAssignment*.
                # What IS assertable here is the negative that gives those tests
                # their standing in a real run: across this entire journey the agent
                # emitted nothing the server had to refuse as malformed.
                assert not [
                    e for e in _agent_events(client, agent_id) if e["event_type"] == "protocol_violation"
                ], (
                    "the server recorded a protocol_violation for this agent. Every frame in this "
                    "journey was produced by the real agent binary, so a malformed or oversized "
                    "one means the agent is emitting frames its own server refuses: "
                    f"{[e for e in _agent_events(client, agent_id) if e['event_type'] == 'protocol_violation']}"
                )
                # OUT-OF-SCOPE is asserted in full in step 8, with `remote_probe`
                # still granted, because that is the only place the REASON is about
                # scope: `evaluate_eligibility` short-circuits on the first failing
                # precondition, and `remote_probe` is withdrawn at this point in the
                # journey, so the same call now answers `capability_disabled`. What
                # survives the withdrawal is `in_scope`, which `get_probe_eligible_
                # agents` computes independently of `eligible` for exactly this
                # reason — so it is restated here, over the scope as it finally
                # stands after an address change and an upgrade, and the reason is
                # deliberately NOT asserted here rather than asserted weakly.
                out_of_scope = _probe_eligible_row(client, agent_id, host="8.8.8.8")
                assert out_of_scope["in_scope"] is False, (
                    "a public address is inside this agent's derived scope after the journey's "
                    f"address change and upgrade; step 8 proved it was not before them: "
                    f"{out_of_scope}"
                )
                assert out_of_scope["eligible"] is False, out_of_scope

                # ---- ZERO MANUAL CONFIGURATION, re-checked while the container is
                # still healthy. Deliberately before the revoke: a revoked agent
                # crash-loops on its refused link, and `docker compose exec` against
                # a restarting container is not a reliable read.
                assert agent_toml_path.read_text() == agent_toml_after_install, (
                    "agent.toml changed at some point in this journey — the whole of it happened "
                    "with no manual agent-side configuration after the generated command, or it "
                    "did not"
                )
                etc_listing = _agent_shell("ls /etc/circuit-breaker")
                assert etc_listing.returncode == 0, etc_listing.stderr
                assert etc_listing.stdout.split() == ["agent.toml"], (
                    "the agent's config directory holds something other than the single file the "
                    f"installer wrote: {etc_listing.stdout.split()}"
                )
                assert not _routable_listeners(_AGENT_SERVICE), (
                    "the agent has opened a listening socket on a non-loopback address at some "
                    "point in this journey — see _routable_listeners for why the loopback ones "
                    "(Docker's own embedded DNS resolver) are not the agent's"
                )

                # ---- ZERO INBOUND CONNECTIONS FROM CIRCUIT BREAKER TO THE REMOTE
                # SUBNET, over the topology as it finally stands. Here rather than
                # after the revoke for the same reason as the reads above: the
                # positive control pings the AGENT container, and a revoked agent's
                # container is the one thing in this stack whose liveness is no
                # longer guaranteed. Nothing after this point starts, stops or
                # re-attaches a container, so this IS the final topology — the
                # revoke changes grants and sockets, never routes.
                _assert_positive_controls(new_ip)
                for address in (_PROBE_TARGET_IP, _PROBE_TARGET_NEW_IP):
                    _assert_backend_cannot_reach(address, _PROBE_NET_CIDR)

                # ---- ...and THEN revoke, as the same continuous act ------------
                # TWO capabilities are put back first, and each is watched producing
                # something, because the post-revoke silence is only a statement
                # about revocation if the thing that fell silent was running. An
                # agent that had already been told to stop satisfies "nothing
                # arrived after the revoke" trivially — and after the withdrawal
                # above that is exactly the state `host_telemetry` AND `remote_probe`
                # are in, so asserting a frozen probe-run count against a capability
                # that is still disabled would prove nothing about revocation at all.
                # A bare boolean, so `set_capability_grants` restores the stored
                # config rather than resetting it: this is a resume, not a
                # reconfiguration.
                #
                # `local_discovery` is deliberately NOT re-enabled. Re-granting it
                # re-arms the bootstrap pass, and a fresh sweep starting seconds
                # before a revoke would race every "no new result rows" assertion
                # below for a reason that is about scheduling rather than about
                # revocation. The discovery half of revocation is instead asserted
                # structurally, on the dispatch columns — every one of this agent's
                # jobs must be closed and hold no open dispatch — which is the
                # mechanism `agent_discovery` actually reads to refuse a late
                # finding, and which does not need a live scan to be meaningful.
                _set_capability_enabled(client, headers, agent_id, "host_telemetry", True)
                _set_capability_enabled(client, headers, agent_id, "remote_probe", True)
                revoke_watermark = datetime.now(timezone.utc)
                _wait_until(
                    lambda: _parse_ts(
                        _agent_telemetry(client, agent_id)["latest"]["collected_at"]
                    )
                    > revoke_watermark,
                    timeout=_FIRST_SAMPLE_BUDGET_S,
                )
                _wait_until(
                    lambda: _parse_ts(_monitor(client, icmp_id)["probe_last_result_at"])
                    > revoke_watermark,
                    timeout=_PROBE_RECONNECT_BUDGET_S,
                )
                def _completed_runs() -> dict[str, int]:
                    """Per monitor, how many probe runs have actually COMPLETED.

                    Completed rather than total, because the scheduler keeps
                    opening runs for a monitor whose vantage is unavailable — step
                    11 asserts that as correct while the agent is merely
                    partitioned, and a revoked agent is a special case of an
                    unavailable vantage rather than a different mechanism. Slice 3
                    §8 requires revocation to "cancel runs and preserve assignments
                    as unavailable"; it does not require the scheduler to stop
                    noticing the monitor is due. A total would therefore measure
                    the scheduler's cadence rather than the revocation, and grows
                    by one tick per monitor on a completely correct system.

                    What a revoked agent may never do is complete a check.
                    """
                    return {
                        name: len(
                            [
                                run
                                for run in _probe_runs(client, created["id"])
                                if run["status"] == "completed"
                            ]
                        )
                        for name, created in monitors.items()
                    }

                runs_before_revoke = _completed_runs()

                # A listener connected NOW, and this is not tidiness. The presence
                # stream `_enroll_agent` opened is dead: a websocket does not
                # survive the server process it is connected to, and step 14
                # restarted the backend. Its `has_event` would answer False forever,
                # and an assertion built on it would be asserting that a socket
                # closed twenty minutes ago received nothing. Opened BEFORE the
                # revoke, for the same reason the original was opened before the
                # enrollment: the claim is that the event was PUSHED, and a listener
                # that connects afterwards could only ever poll for it.
                revoke_stream = _AgentStreamListener(token)
                try:
                    revoke = client.post(
                        f"/api/v1/agents/{agent_id}/revoke",
                        json={"reason": "release gate step 16"},
                        headers=headers,
                    )
                    assert revoke.status_code == 200, revoke.text
                    _wait_until(
                        lambda: revoke_stream.has_event(agent_id, "revoked"), timeout=30
                    )
                finally:
                    revoke_stream.close()
                assert client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "revoked"
                # The session is GONE, asked of the server's own presence view.
                #
                # Not of `docker compose logs cb-agent`: that returns the whole container
                # log since start, and this journey has already survived two partitions,
                # three restarts and an in-place re-exec — so a predicate looking for the
                # words "disconnect" or "reconnect" anywhere in it is true many
                # minutes before the revoke is issued and would hold even if
                # `post_revoke` did nothing whatsoever. Presence is a Redis key with
                # a 60s TTL that only a heartbeat refreshes, so its disappearance is
                # a statement about now.
                _wait_until(lambda: not _agent_online(client, agent_id), timeout=90)

                # ...and only once revocation is IN EFFECT are the counters that the
                # silence is measured against read. Snapshotting them before the
                # POST would open a window — one scheduler tick, one 30s collection
                # — in which a perfectly correct system writes a row between the
                # snapshot and the revoke, and this test would report that as a row
                # written for a revoked agent. The claim being made is "nothing lands
                # AFTER revocation takes effect", and this is where that starts.
                samples_at_revoke = _agent_host_samples(
                    agent_id, first_sample_at - timedelta(seconds=1), datetime.now(timezone.utc)
                )
                assert len(samples_at_revoke) > 0, samples_at_revoke
                # COMPLETED runs, not all runs. The scheduler keeps ticking a
                # monitor whose vantage is unavailable and keeps opening runs for
                # it — step 11 asserts exactly that as correct behaviour while the
                # agent is merely partitioned, and a revoked agent is a special case
                # of an unavailable vantage, not a different mechanism. Slice 3 §8
                # requires revocation to "cancel runs and preserve assignments as
                # unavailable"; it does not require the scheduler to stop noticing
                # the monitor is due. Counting every run therefore measured the
                # scheduler's cadence rather than the revocation, and grew by one
                # tick per monitor for a completely correct system.
                #
                # What a revoked agent may never do is COMPLETE a check. Every run
                # opened from here on has no vantage to dispatch to and must die
                # unavailable/expired, so this count is the one that has to stand
                # still.
                runs_at_revoke = _completed_runs()
                assert all(
                    runs_at_revoke[name] >= runs_before_revoke.get(name, 0)
                    for name in runs_at_revoke
                ), (
                    "probe run history went BACKWARDS across the revoke — `post_revoke` must "
                    "RETIRE the open runs, never delete the history of what the vantage did: "
                    f"{runs_before_revoke} -> {runs_at_revoke}"
                )
                results_at_revoke = {
                    job["id"]: len(_job_results(client, job["id"]))
                    for job in _agent_scan_jobs(client, agent_id)
                }

                # CANCELLATION ACROSS ALL CAPABILITY HANDLERS. `post_revoke` does
                # three things in one transaction, and each is checked where it
                # lands: probe runs are cancelled, discovery dispatches are closed,
                # and the socket is gone so telemetry has nowhere to go.
                for name, created in monitors.items():
                    wedged = [
                        r
                        for r in _probe_runs(client, created["id"])
                        if r["status"] in ("queued", "dispatched")
                        and _parse_ts(r["scheduled_at"])
                        < datetime.now(timezone.utc) - timedelta(seconds=120)
                    ]
                    assert not wedged, (
                        f"{name}: a probe run is still in flight long past its lease after the "
                        f"agent was revoked — revocation must retire them: {wedged}"
                    )
                for job in _agent_scan_jobs(client, agent_id):
                    status, dispatch_status = _job_dispatch_state(job["id"])
                    assert status not in ("queued", "running"), (
                        f"scan job {job['id']} is still open after its agent was revoked: "
                        f"{(status, dispatch_status)}"
                    )
                    assert dispatch_status != "dispatched", (
                        f"scan job {job['id']} still holds an open dispatch after its agent was "
                        f"revoked, and `agent_discovery` reads exactly that column to refuse a "
                        f"late finding: {(status, dispatch_status)}"
                    )
                # The assignments are RETAINED and reported unavailable rather than
                # silently handed back to the server: §2 forbids an automatic
                # fallback, and a revoked vantage is the sharpest case of it.
                for name, created in monitors.items():
                    current = _monitor(client, created["id"])
                    assert current["probe_agent_id"] == agent_id, (
                        f"{name}: revoking the agent silently moved the monitor to server "
                        f"execution: {current}"
                    )

                # LATE FRAMES DIE. Three full collection intervals of an agent that
                # was collecting a minute ago, and nothing it produces may land —
                # `link_stream` refuses any agent whose status is not `active`, so
                # it cannot even open the connection to try.
                time.sleep(_POST_REVOKE_SILENCE_S)
                # Asked of the SERVER rather than of the agent's own status file: a
                # revoked agent is refused at `/link` and retries behind its
                # reconnect backoff, and `docker compose exec` against a container in
                # that state is not a read this assertion should depend on. Presence
                # is the server's own answer to "is this agent connected", and it is
                # the one that matters here.
                assert not _agent_online(client, agent_id), (
                    "the server still reports a revoked agent as connected"
                )
                assert (
                    _agent_host_samples(
                        agent_id,
                        first_sample_at - timedelta(seconds=1),
                        datetime.now(timezone.utc),
                    )
                    == samples_at_revoke
                ), "a host sample was persisted for a revoked agent"
                assert _completed_runs() == runs_at_revoke, (
                    "a probe run COMPLETED for a revoked agent's monitor — the vantage is gone, "
                    "so every run opened after the revoke must die unavailable, never succeed"
                )
                assert {
                    job["id"]: len(_job_results(client, job["id"]))
                    for job in _agent_scan_jobs(client, agent_id)
                } == results_at_revoke, "a discovery result was accepted from a revoked agent"

                # ═════════════════════════════════════════════════════════════
                # Closing block: the spec's required assertions, over the journey
                #                as it finally stands
                # ═════════════════════════════════════════════════════════════
                # Each of these has been asserted at the moment it was created; this
                # is the after-the-fact sweep, because "no duplicates" is a property
                # of the END state and several of the steps above deliberately
                # retried, reconnected, restarted and replayed to try to break it.

                # (ZERO INBOUND CONNECTIONS FROM CIRCUIT BREAKER TO THE REMOTE
                # SUBNET is asserted immediately before the revoke, with its
                # positive controls, over this same final topology — see the note
                # there for why it cannot run after a revoked agent's container.)

                # NO DUPLICATE PROFILES.
                final_profiles = _discovery_profiles(client, agent_id)
                assert {p["id"] for p in final_profiles} == {
                    p["id"] for p in profiles_at_bootstrap
                }, "the journey created or replaced a system-managed profile"
                assert len(_all_profiles(client)) == len(all_profiles_before_restart), (
                    "the installation's profile count changed across the journey"
                )

                # NO DUPLICATE AUTOMATIC JOBS: three reconnects, two restarts, an
                # address change and an upgrade, and still exactly one bootstrap
                # scan per system profile.
                for profile in profiles_at_bootstrap:
                    automatic = [
                        j
                        for j in _scan_jobs(client, profile_id=profile["id"])
                        if j["triggered_by"] == "bootstrap"
                    ]
                    assert len(automatic) == 1, (
                        f"profile {profile['id']} ({profile['cidr']}) has {len(automatic)} "
                        f"bootstrap scans: {[j['id'] for j in automatic]}"
                    )

                # NO DUPLICATE FINDINGS: one result row per (job, address). This is
                # what the replay-stable `finding_id` digest exists for and what
                # `uq_scan_results_job_finding` enforces.
                final_provenance = _result_provenance()
                seen: dict[tuple[int, str], int] = {}
                for row in final_provenance:
                    key = (row["scan_job_id"], row["ip_address"])
                    seen[key] = seen.get(key, 0) + 1
                duplicated = {key: count for key, count in seen.items() if count > 1}
                assert not duplicated, (
                    f"a job holds more than one result row for the same address: {duplicated}"
                )

                # NO DUPLICATE HARDWARE RECORDS OR TOPOLOGY NODES.
                assert [h["id"] for h in _hardware_with_ip(client, _PROBE_TARGET_IP)] == [
                    hardware_id
                ], "the journey produced a second Hardware row for the discovered device"
                assert not _hardware_with_ip(client, _PROBE_TARGET_NEW_IP), (
                    "the device that appeared later was imported without anyone accepting it"
                )
                final_nodes = _topology_nodes(client)
                assert final_nodes.count(node_id) == 1, (
                    f"the imported device is placed {final_nodes.count(node_id)} times in the "
                    "topology graph"
                )
                assert len(final_nodes) == len(set(final_nodes)), (
                    "the topology graph contains duplicate node ids: "
                    f"{sorted({n for n in final_nodes if final_nodes.count(n) > 1})}"
                )

                # NO DUPLICATE SAMPLES, over the WHOLE journey rather than over one
                # outage window: two restarts, an upgrade, two partitions and a
                # spool drain all had their chance.
                journey_samples = _agent_host_samples(
                    agent_id, first_sample_at - timedelta(seconds=1), datetime.now(timezone.utc)
                )
                journey_ids = [sample_id for sample_id, _ in journey_samples]
                assert len(set(journey_ids)) == len(journey_ids), (
                    "a sample_id was persisted more than once across the journey: "
                    f"{sorted({i for i in journey_ids if journey_ids.count(i) > 1})}"
                )

                # NO DUPLICATE PROBE RESULTS, and NO DUPLICATE ALERTS. A run id is
                # the identity of one dispatched check, and a transition log that
                # repeats a state without an intervening change is a second alert
                # for one event — which is what an at-least-once result delivery
                # would produce if the state machine did not dedupe it.
                for name, created in list(monitors.items()) + [("retry/alert", retry_monitor)]:
                    run_ids = [r["run_id"] for r in _probe_runs(client, created["id"])]
                    assert len(set(run_ids)) == len(run_ids), (
                        f"{name}: a probe run id appears more than once: "
                        f"{sorted({r for r in run_ids if run_ids.count(r) > 1})}"
                    )
                    states = [e["event_type"] for e in _transitions(client, created["id"])]
                    assert all(
                        earlier != later for earlier, later in pairwise(states)
                    ), (
                        f"{name}: the same transition was recorded twice in a row, which is a "
                        f"duplicate alert for one state change: {states}"
                    )

                # EVERY REMOTE OBSERVATION ATTRIBUTABLE TO THE CORRECT AGENT.
                # Both provenance columns agree on every agent-executed row, and no
                # row names an agent that has no route to the address it reports —
                # which is what makes cross-attribution falsifiable rather than
                # merely absent from the table.
                reach = {agent_id: (_AGENT_NET_CIDR, _PROBE_NET_CIDR)}
                agent_rows = [r for r in final_provenance if r["job_scan_agent_id"] is not None]
                assert agent_rows, "no agent-executed results at all; nothing to attribute"
                for row in agent_rows:
                    assert row["discovery_agent_id"] == row["job_scan_agent_id"], (
                        f"a result's own reporter ({row['discovery_agent_id']}) is not the agent "
                        f"its job was dispatched to ({row['job_scan_agent_id']}). Those columns "
                        f"are written by different code paths and must never disagree: {row}"
                    )
                    assert _in_any(row["ip_address"], reach[row["discovery_agent_id"]]), (
                        f"result {row['id']} names {row['ip_address']} as reported by agent "
                        f"{row['discovery_agent_id']}, which has no route to that address"
                    )
                for address in (_PROBE_TARGET_IP, _PROBE_TARGET_NEW_IP):
                    reporters = {
                        row["discovery_agent_id"]
                        for row in final_provenance
                        if row["ip_address"] == address
                    }
                    assert reporters == {agent_id}, (
                        f"{address} is attributed to {sorted(reporters)}, expected only the agent "
                        "that can reach it"
                    )
                # ...and every probe run on the discovered device's monitors names
                # the same agent.
                for name, created in monitors.items():
                    owners = {r["agent_id"] for r in _probe_runs(client, created["id"])}
                    assert owners <= {agent_id}, (
                        f"{name}: probe runs are attributed to {sorted(owners)}"
                    )

                # EXISTING SERVER-SIDE PATHS, STILL WORKING AFTER ALL OF IT. The
                # server-executed monitor never noticed any of this, and the
                # server-executed scan's provenance is still nobody's.
                # Waited for rather than sampled once: the backend was restarted
                # in step 14 and this monitor polls every 30s, so it may legitimately
                # be inside a retry at any given instant. What must not happen is
                # that it stays anything other than up.
                _wait_until(
                    lambda: _monitor(client, server_monitor_id)["status"] == "up",
                    timeout=_PROBE_FIRST_RESULT_BUDGET_S,
                )
                assert _monitor(client, server_monitor_id)["probe_agent_id"] is None, (
                    "the server-executed control monitor acquired an agent vantage"
                )
                assert _probe_runs(client, server_monitor_id) == [], (
                    "a probe run was opened for the server-executed monitor"
                )
                assert all(
                    row["discovery_agent_id"] is None
                    for row in final_provenance
                    if row["scan_job_id"] == server_job_id
                ), "the server-executed scan's results gained an agent attribution"
            finally:
                stream.close()
        finally:
            discovery_stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)
