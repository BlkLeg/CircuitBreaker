"""`hello.networks` -> `agent_networks`, versioned (Task 2, D-1).

The generation counter is the contract: Slice 4 cancels in-flight work when
the scope version moves, so it must move when — and only when — the agent's
directly connected networks actually changed. A counter that ticked on every
reconnect would make "scope changed" meaningless, which is why the comparison
runs against the normalized form rather than the reported one.
"""

from __future__ import annotations

from datetime import timedelta

from app.core.time import utcnow
from app.db.models import AgentNetwork
from app.schemas.agent_frame import HelloPayload
from app.services import agent_registry as svc

# As reported on the wire ...
_ETH0 = {"name": "eth0", "flags": ["up", "broadcast"], "addrs": ["10.0.0.5/24", "fd00::5/64"]}
_WG0 = {"name": "wg0", "flags": ["up", "pointtopoint"], "addrs": ["10.9.0.2/32"]}
# ... and as stored, with every list sorted.
_ETH0_STORED = {
    "name": "eth0",
    "flags": ["broadcast", "up"],
    "addrs": ["10.0.0.5/24", "fd00::5/64"],
}
_WG0_STORED = {"name": "wg0", "flags": ["pointtopoint", "up"], "addrs": ["10.9.0.2/32"]}


def _report(db_session, agent_id: int) -> AgentNetwork:
    return db_session.query(AgentNetwork).filter_by(agent_id=agent_id).one()


def test_hello_with_networks_creates_a_generation_one_row(db_session, factories):
    agent = factories.agent(status="active")

    svc.update_hello_metadata(
        db_session, agent, HelloPayload.model_validate({"networks": [_WG0, _ETH0]})
    )

    row = _report(db_session, agent.id)
    assert row.generation == 1
    assert row.observed_at is not None
    assert row.facts == [_ETH0_STORED, _WG0_STORED]


def test_identical_facts_do_not_bump_generation(db_session, factories):
    """The prior report is seeded and expired rather than left in the identity
    map: in production it was written by a previous connection, so the equality
    test runs against JSONB-decoded values, not the objects we just assigned."""
    agent = factories.agent(status="active")
    first = factories.agent_network(agent, facts=[_ETH0_STORED, _WG0_STORED]).observed_at
    db_session.expire_all()

    # Same facts, different ordering — a reconnect whose enumeration came back
    # shuffled is not a scope change.
    reordered = dict(_ETH0, flags=["broadcast", "up"], addrs=list(reversed(_ETH0["addrs"])))
    svc.update_hello_metadata(
        db_session, agent, HelloPayload.model_validate({"networks": [_WG0, reordered]})
    )

    row = _report(db_session, agent.id)
    assert row.generation == 1
    assert row.observed_at == first


def test_changed_facts_bump_generation_and_observed_at(db_session, factories):
    agent = factories.agent(status="active")
    svc.update_hello_metadata(db_session, agent, HelloPayload.model_validate({"networks": [_ETH0]}))

    # Backdate so the new timestamp is unambiguously later than the old one.
    stale = utcnow() - timedelta(hours=1)
    _report(db_session, agent.id).observed_at = stale

    svc.update_hello_metadata(
        db_session, agent, HelloPayload.model_validate({"networks": [_ETH0, _WG0]})
    )

    row = _report(db_session, agent.id)
    assert row.generation == 2
    assert row.observed_at > stale
    assert row.facts == [_ETH0_STORED, _WG0_STORED]


def test_hello_without_networks_leaves_the_previous_report_intact(db_session, factories):
    """Presence, not truthiness — the rule `update_hello_metadata` already
    documents. An agent build that predates network reporting omits the key
    and must not erase what a newer build reported; an explicit empty list is
    a real report and must land."""
    agent = factories.agent(status="active")
    svc.update_hello_metadata(db_session, agent, HelloPayload.model_validate({"networks": [_ETH0]}))

    svc.update_hello_metadata(db_session, agent, HelloPayload.model_validate({"os": "linux"}))

    row = _report(db_session, agent.id)
    assert row.generation == 1
    assert row.facts == [_ETH0_STORED]

    # The half of the rule a truthiness gate gets silently wrong: an agent that
    # has lost every usable interface would keep a stale, wider-than-reality
    # scope, and the generation the scheduler cancels work on would never move.
    svc.update_hello_metadata(db_session, agent, HelloPayload.model_validate({"networks": []}))

    row = _report(db_session, agent.id)
    assert row.generation == 2
    assert row.facts == []
