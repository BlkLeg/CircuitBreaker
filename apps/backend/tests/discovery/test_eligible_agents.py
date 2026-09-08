"""Tests for GET /discovery/eligible-agents.

Split out of the former tests/test_discovery.py.
"""

import pytest

from tests.discovery.helpers import (
    _AGENT_INTERFACES,
    _AGENT_SUBNET,
    _OVERSIZED_INTERFACES,
    _OVERSIZED_SUBNET,
    _eligible_agent,
)

# ---------------------------------------------------------------------------
# GET /discovery/eligible-agents (Slice 4, §6 "Discovery page" / Task 26)
# ---------------------------------------------------------------------------
#
# Plan §6: "Show why an agent is ineligible." The selector therefore renders
# *every* active agent and never filters the list down to the choosable ones —
# an agent that has silently disappeared from a dropdown is the failure mode this
# endpoint exists to prevent.
#
# The verdict is `discovery_admission.validate_agent_execution_location`, the same
# function `POST /discovery/scan` and `POST /discovery/profiles` refuse with, so
# the listing and the refusal cannot disagree about a reason or drift apart when
# a new one is added. In particular that means the listing judges with
# `require_online=False`, exactly as creation does (D-5): an offline agent is a
# legitimate choice whose job parks as `waiting_for_agent`, so `online` is
# rendered as a warning and never as a refusal.


ELIGIBLE_AGENTS_URL = "/api/v1/discovery/eligible-agents"


class _FakePresenceRedis:
    def __init__(self, store):
        self._store = store

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def get(self, key: str) -> str | None:
        return self._store.get(key)


@pytest.fixture
def discovery_presence(monkeypatch):
    """Redis double plus a `mark(agent)` helper; offline is the default."""
    store: dict[str, str] = {}

    async def _get_redis():
        return _FakePresenceRedis(store)

    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)

    def mark(agent, worker: str = "worker-1") -> None:
        store[f"agent:presence:{agent.id}"] = "{}"
        store[f"agent:connection:{agent.id}"] = worker

    return mark


async def _eligible_rows(client, auth_headers, **params):
    resp = await client.get(ELIGIBLE_AGENTS_URL, headers=auth_headers, params=params)
    assert resp.status_code == 200, resp.text
    return {row["agent_id"]: row for row in resp.json()}


@pytest.mark.asyncio
async def test_eligible_discovery_agents_render_every_active_agent_with_its_reason(
    client, auth_headers, factories, discovery_presence
):
    ready = _eligible_agent(factories, name="branch")
    degraded = _eligible_agent(factories, readiness="degraded")
    ungranted = factories.agent(status="active")
    factories.agent_network(ungranted, facts=_AGENT_INTERFACES)
    pending = _eligible_agent(factories, status="pending")
    revoked = _eligible_agent(factories, status="revoked")
    discovery_presence(ready)

    rows = await _eligible_rows(client, auth_headers)

    good = rows[ready.id]
    assert good["name"] == "branch"
    assert good["online"] is True
    assert good["granted"] is True
    assert good["readiness"] == "ready"
    assert good["readiness_collector"] == "discovery.tcp"
    assert good["scope_networks"] == [_AGENT_SUBNET]
    assert good["direct_networks"] == [_AGENT_SUBNET]
    # The registry defaults, spelled out: a silent widening of what every
    # approved agent may sweep has to fail here rather than ship.
    assert good["max_addresses_per_job"] == 1024
    assert good["max_concurrent_hosts"] == 64
    assert good["tcp_ports"] == [22, 53, 80, 443, 445, 3389, 8000, 8080, 8443]
    assert good["paused"] is False
    assert good["eligible"] is True
    assert good["reason"] is None

    assert rows[degraded.id]["eligible"] is False
    assert rows[degraded.id]["reason"] == "readiness_degraded"
    assert rows[ungranted.id]["granted"] is False
    assert rows[ungranted.id]["reason"] == "capability_disabled"
    # §7: pending, rejected and revoked agents can never scan, so they are not
    # candidates at all — offering one would be offering a choice that cannot
    # work. "Show why an agent is ineligible" is about the *active* fleet, which
    # is also exactly the population `GET /agents/probe-eligible` renders.
    assert pending.id not in rows
    assert revoked.id not in rows


@pytest.mark.asyncio
async def test_eligible_discovery_agents_carry_the_hostname_enrollment_recorded(
    client, auth_headers, factories
):
    """An un-renamed agent must not reach the "Scan from" selector as "agent 7".

    `agents.name` is nullable and *enrollment never writes it* — see
    `agent_registry.create_pending_agent`, whose only caller
    (`ws_agents.enroll_stream`) passes hostname/os/arch and no name; the sole
    writer is an explicit operator `PATCH /agents/{id}`. So `name is None` is
    the state of every agent nobody has renamed, which is most of them, and a
    selector with only `name` to render falls back to the bare id for the
    common case rather than the rare one.

    Rejected alternative: defaulting `Agent.name` to the hostname at
    enrollment. That leaves every *existing* un-renamed row still nameless, and
    it conflates "an operator named this" with "we guessed" — a later hostname
    change would then not track, because a stored guess is indistinguishable
    from a deliberate name. Carrying `hostname` alongside `name` and resolving
    at display time fixes old and new rows alike and keeps `name` meaning what
    it means.

    The assertion below is deliberately about the *nameless* agent: a fixture
    that supplies a name cannot see this bug, which is exactly why it shipped.
    """
    unnamed = _eligible_agent(factories, hostname="branch-office-01")
    named = _eligible_agent(factories, name="renamed-by-hand", hostname="dc-rack-3")
    # The premise, pinned against production rather than assumed: this is the
    # row shape enrollment actually produces.
    assert unnamed.name is None

    rows = await _eligible_rows(client, auth_headers)

    assert rows[unnamed.id]["name"] is None
    assert rows[unnamed.id]["hostname"] == "branch-office-01"
    # `hostname` is additional to `name`, never a replacement: an operator who
    # renamed an agent must still see the name they chose.
    assert rows[named.id]["name"] == "renamed-by-hand"
    assert rows[named.id]["hostname"] == "dc-rack-3"


@pytest.mark.asyncio
async def test_eligible_discovery_agents_judge_scope_against_the_asked_subnet(
    client, auth_headers, factories
):
    """Scope compatibility is a property of the pair, so the answer has to move
    with the CIDR — a per-agent verdict computed once would say the same thing
    about every subnet the operator typed."""
    agent = _eligible_agent(factories)
    degraded = _eligible_agent(factories, readiness="degraded")

    inside = await _eligible_rows(client, auth_headers, cidr=_AGENT_SUBNET)
    assert inside[agent.id]["in_scope"] is True
    assert inside[agent.id]["eligible"] is True
    # Scope is answered independently of eligibility, which short-circuits on the
    # first failing precondition: this agent's collector is what refuses it, and
    # a UI that read `in_scope` off `eligible` would tell the operator to fix the
    # CIDR instead of the collector.
    assert inside[degraded.id]["in_scope"] is True
    assert inside[degraded.id]["eligible"] is False
    assert inside[degraded.id]["reason"] == "readiness_degraded"

    outside = await _eligible_rows(client, auth_headers, cidr="192.168.50.0/24")
    assert outside[agent.id]["in_scope"] is False
    assert outside[agent.id]["eligible"] is False
    assert outside[agent.id]["reason"] == "out_of_scope"

    # With no CIDR the question was never asked, which is distinct from "no".
    unasked = await _eligible_rows(client, auth_headers)
    assert unasked[agent.id]["in_scope"] is None


@pytest.mark.asyncio
async def test_eligible_discovery_agents_refuse_a_subnet_over_the_address_ceiling(
    client, auth_headers, factories
):
    """The ceiling is enforced by the creation path and *not* by
    `discovery_eligibility`, so a listing that asked the eligibility module
    directly would advertise an agent the very next request refuses."""
    agent = _eligible_agent(factories, interfaces=_OVERSIZED_INTERFACES)

    rows = await _eligible_rows(client, auth_headers, cidr=_OVERSIZED_SUBNET)

    assert rows[agent.id]["eligible"] is False
    assert rows[agent.id]["reason"] == "address_limit_exceeded"
    assert rows[agent.id]["detail"] == "65536>1024"


@pytest.mark.asyncio
async def test_an_offline_agent_is_still_a_choosable_discovery_vantage(
    client, auth_headers, factories, discovery_presence
):
    """D-5: an agent that is not connected parks its job as `waiting_for_agent`
    rather than failing it, so being offline is a scheduling condition. Marking
    it ineligible here would contradict the creation endpoint, which accepts it."""
    agent = _eligible_agent(factories)

    rows = await _eligible_rows(client, auth_headers, cidr=_AGENT_SUBNET)

    assert rows[agent.id]["online"] is False
    assert rows[agent.id]["eligible"] is True
    assert rows[agent.id]["reason"] is None
