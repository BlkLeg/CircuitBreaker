"""GET /agents/{id}/discovery -- the Agent Detail scope section (Plan section 6 /
Task 26): effective CIDRs and their automatic/override provenance, the port set
and grant limits, per-collector readiness, the live job plus its history and
profiles, and the fleet-wide pause reported separately from the per-agent one.

Split out of the former tests/api/test_agents_api.py.
"""

import pytest

from tests.api.agent_fakes import (
    _DISCOVERY_INTERFACES,
    _DISCOVERY_SUBNET,
    DISCOVERY_SUBNET_B,
    LOCAL_DISCOVERY_DEFAULT_CONFIG,
    _discovery_agent,
    _discovery_url,
    _live_dispatch,
)

# ---------------------------------------------------------------------------
# GET /agents/{id}/discovery — the Agent Detail scope section (§6 / Task 26)
# ---------------------------------------------------------------------------
#
# `GET /agents/{id}/probes`' twin, and deliberately shaped like it: it is what
# `AgentDetailPage` already loads for `AssignedProbesSection`, and Task 27's
# `DiscoveryScopeSection` is cloned from that component. Plan §6 names what it
# has to carry — "effective CIDRs and their automatic/override provenance, port
# set, limits, readiness, active job, and recent job history".
#
# Two of those need care:
#
# * **Provenance** is not decoration. An automatic subnet came off the agent's
#   own interfaces and disappears when the interface does; an override is a CIDR
#   an administrator typed and nothing but another edit removes. The section lets
#   an operator exclude the first and add the second, so a UI that could not tell
#   them apart would offer the wrong control.
# * **Effective** is not the allow list. `EffectiveScope.networks` is what is
#   permitted *before* exclusions and the static special-use blocklist are
#   subtracted, and rendering it as reachability would claim access the evaluator
#   refuses.


_TWO_SUBNET_INTERFACES = [
    {"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.30.40.5/24"]},
    {"name": "eth1", "flags": ["broadcast", "up"], "addrs": ["10.30.41.5/24"]},
]


def _scope_by_cidr(body) -> dict:
    return {entry["cidr"]: entry for entry in body["scope"]}


@pytest.mark.asyncio
async def test_agent_discovery_renders_scope_with_provenance_and_the_effective_verdict(
    client, factories, viewer_headers
):
    agent = _discovery_agent(
        factories,
        interfaces=_TWO_SUBNET_INTERFACES,
        config={
            "excluded_cidrs": [DISCOVERY_SUBNET_B],
            "additional_cidrs": ["10.31.0.0/24"],
        },
    )

    resp = await client.get(_discovery_url(agent), headers=viewer_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent_id"] == agent.id
    scope = _scope_by_cidr(body)

    # Directly connected and unexcluded: automatic, and actually reachable.
    assert scope[_DISCOVERY_SUBNET]["provenance"] == "automatic"
    assert scope[_DISCOVERY_SUBNET]["effective"] is True

    # Directly connected but centrally excluded — this is the difference between
    # the allow list and what the evaluator permits, and the whole reason
    # `effective` is a separate field from membership in `scope`.
    assert scope[DISCOVERY_SUBNET_B]["provenance"] == "automatic"
    assert scope[DISCOVERY_SUBNET_B]["effective"] is False
    assert scope[DISCOVERY_SUBNET_B]["reason"] == "excluded_cidr"

    # An administrator's routed override: in the allow list, not directly
    # connected, and visibly a different kind of thing.
    assert scope["10.31.0.0/24"]["provenance"] == "override"
    assert scope["10.31.0.0/24"]["effective"] is True

    assert body["scope_version"]


@pytest.mark.asyncio
async def test_agent_discovery_reports_the_port_set_and_the_grant_limits(
    client, factories, viewer_headers
):
    """Plan §6 asks the section to show the port set and the limits, because
    those are what refuse an otherwise-fine agent (`port_not_granted`,
    `address_limit_exceeded`) — an operator reading a refusal needs the numbers
    it was measured against on the same page."""
    agent = _discovery_agent(factories, config={"max_addresses_per_job": 512})

    body = (await client.get(_discovery_url(agent), headers=viewer_headers)).json()

    limits = body["limits"]
    assert limits["max_addresses_per_job"] == 512
    assert limits["max_concurrent_hosts"] == LOCAL_DISCOVERY_DEFAULT_CONFIG["max_concurrent_hosts"]
    assert limits["host_timeout_ms"] == LOCAL_DISCOVERY_DEFAULT_CONFIG["host_timeout_ms"]
    assert limits["job_timeout_seconds"] == LOCAL_DISCOVERY_DEFAULT_CONFIG["job_timeout_seconds"]
    assert limits["scope_mode"] == LOCAL_DISCOVERY_DEFAULT_CONFIG["scope_mode"]
    assert limits["tcp_ports"] == LOCAL_DISCOVERY_DEFAULT_CONFIG["tcp_ports"]


@pytest.mark.asyncio
async def test_agent_discovery_reports_every_collector_including_the_ones_with_no_row(
    client, factories, viewer_headers
):
    """D-8 names four discovery collectors. A collector that has never reported
    is rendered with a null state rather than omitted: "not installed" and
    "installed and broken" are different operator problems, and an absent row is
    the one that makes a job refuse with `readiness_unknown`."""
    from app.services import discovery_eligibility

    agent = _discovery_agent(factories)  # brings discovery.tcp = ready
    factories.agent_capability_readiness(
        agent, collector="discovery.icmp", state="degraded", reason="no datagram socket"
    )

    body = (await client.get(_discovery_url(agent), headers=viewer_headers)).json()

    rows = {row["collector"]: row for row in body["readiness"]}
    assert set(rows) == set(discovery_eligibility.READINESS_COLLECTORS)
    assert rows["discovery.tcp"]["state"] == "ready"
    # The one collector a job is actually gated on, flagged as such: the other
    # three are legitimately unavailable on an unprivileged host that can still
    # run the whole scan.
    assert rows["discovery.tcp"]["required"] is True
    assert rows["discovery.icmp"]["state"] == "degraded"
    assert rows["discovery.icmp"]["reason"] == "no datagram socket"
    assert rows["discovery.icmp"]["required"] is False
    assert rows["discovery.neighbor"]["state"] is None
    assert rows["discovery.dns"]["state"] is None


@pytest.mark.asyncio
async def test_agent_discovery_reports_the_live_job_its_history_and_its_profiles(
    client, factories, viewer_headers, db_session
):
    from app.core.time import utcnow_iso
    from app.db.models import DiscoveryProfile

    agent = _discovery_agent(factories)
    other = _discovery_agent(factories)
    now = utcnow_iso()
    profile = DiscoveryProfile(
        name="held",
        cidr=_DISCOVERY_SUBNET,
        normalized_cidr=_DISCOVERY_SUBNET,
        scan_types='["agent_connect"]',
        scan_agent_id=agent.id,
        managed_by="system",
        schedule_cron="7 */6 * * *",
        enabled=1,
        created_at=now,
        updated_at=now,
    )
    db_session.add(profile)
    db_session.flush()
    live = _live_dispatch(db_session, agent, profile_id=profile.id)
    finished = _live_dispatch(
        db_session, agent, status="completed", dispatch_status="completed", hosts_found=3
    )
    elsewhere = _live_dispatch(db_session, other)

    body = (await client.get(_discovery_url(agent), headers=viewer_headers)).json()

    assert [job["id"] for job in body["active_jobs"]] == [live.id]
    assert body["active_jobs"][0]["scan_agent_id"] == agent.id
    history = [job["id"] for job in body["recent_jobs"]]
    assert finished.id in history
    # Another agent's work is another agent's page.
    assert elsewhere.id not in history
    assert elsewhere.id not in [job["id"] for job in body["active_jobs"]]
    assert [p["id"] for p in body["profiles"]] == [profile.id]
    assert body["profiles"][0]["schedule_cron"] == "7 */6 * * *"
    assert body["profiles"][0]["managed_by"] == "system"


@pytest.mark.asyncio
async def test_agent_discovery_reports_why_nothing_is_being_discovered(
    client, factories, viewer_headers
):
    """The section's whole job when it is empty. `reason` is the same closed
    vocabulary the scan endpoints refuse with, so the page and the error the
    operator just saw agree."""
    granted = _discovery_agent(factories)
    body = (await client.get(_discovery_url(granted), headers=viewer_headers)).json()
    assert body["granted"] is True
    assert body["eligible"] is True
    assert body["reason"] is None

    ungranted = factories.agent(status="active")
    factories.agent_network(ungranted, facts=_DISCOVERY_INTERFACES)
    body = (await client.get(_discovery_url(ungranted), headers=viewer_headers)).json()
    assert body["granted"] is False
    assert body["eligible"] is False
    assert body["reason"] == "capability_disabled"


@pytest.mark.asyncio
async def test_agent_discovery_returns_404_for_an_unknown_agent(client, viewer_headers):
    resp = await client.get("/api/v1/agents/999999/discovery", headers=viewer_headers)
    assert resp.status_code == 404
