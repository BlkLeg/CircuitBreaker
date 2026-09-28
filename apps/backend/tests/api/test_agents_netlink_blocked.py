"""RISK-011: list the agents whose systemd unit still refuses AF_NETLINK.

Hosts installed before the unit template granted AF_NETLINK keep their old
unit, and on them discovery and probing are silently dead. The fleet list is
built from each agent's `discovery.neighbor` readiness row, so the rows here are
fed through the real `ingest_readiness` using the shared frame corpus — the same
entries apps/agent's discover tests pin the agent's actual output against. A
rewording on either side fails one of the two suites instead of silently
dropping a broken host from this list.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.db.models import AgentCapabilityReadiness
from app.services import agent_netlink, agent_telemetry

_CORPUS_PATH = Path(__file__).resolve().parents[4] / "fixtures" / "agent_frame_corpus.json"
_CURRENT = "capability.readiness — AF_NETLINK refused by the service sandbox (RISK-011)"
_LEGACY = (
    "capability.readiness — AF_NETLINK refused by the service sandbox, as an agent built before"
)
_ENDPOINT = "/api/v1/agents/netlink-blocked"


def _corpus_payload(prefix: str) -> dict[str, Any]:
    """The payload of the one corpus entry whose description starts with `prefix`."""
    entries = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    matches = [e for e in entries if e["description"].startswith(prefix)]
    assert len(matches) == 1, f"expected exactly one corpus entry starting {prefix!r}"
    return copy.deepcopy(matches[0]["json"]["payload"])


def _neighbor_payload(**row: Any) -> dict[str, Any]:
    return {"readiness": [{"collector": "discovery.neighbor", **row}]}


@pytest.mark.asyncio
async def test_lists_current_and_legacy_reports_and_nothing_else(
    client, auth_headers, db_session, factories
):
    current = factories.agent(status="active", hostname="current-agent")
    legacy = factories.agent(status="active", hostname="legacy-agent")
    healthy = factories.agent(status="active", hostname="healthy")
    other_failure = factories.agent(status="active", hostname="fd-exhausted")
    revoked = factories.agent(status="revoked", hostname="revoked")
    icmp_only = factories.agent(status="active", hostname="icmp-only")
    db_session.commit()

    await agent_telemetry.ingest_readiness(db_session, current, _corpus_payload(_CURRENT))
    await agent_telemetry.ingest_readiness(db_session, legacy, _corpus_payload(_LEGACY))
    await agent_telemetry.ingest_readiness(db_session, healthy, _neighbor_payload(state="ready"))
    await agent_telemetry.ingest_readiness(
        db_session,
        other_failure,
        _neighbor_payload(
            state="unavailable", reason="discover: open netlink socket: too many open files"
        ),
    )
    await agent_telemetry.ingest_readiness(db_session, revoked, _corpus_payload(_CURRENT))
    # The token on a different collector's row is not evidence about the neighbor socket.
    await agent_telemetry.ingest_readiness(
        db_session,
        icmp_only,
        {
            "readiness": [
                {"collector": "discovery.icmp", "state": "unavailable", "missing": ["AF_NETLINK"]}
            ]
        },
    )

    resp = await client.get(_ENDPOINT, headers=auth_headers)
    assert resp.status_code == 200
    rows = {row["hostname"]: row for row in resp.json()}
    assert set(rows) == {"current-agent", "legacy-agent"}

    assert rows["current-agent"]["legacy_report"] is False
    assert "systemctl edit cb-agent" in rows["current-agent"]["remediation"]
    assert rows["current-agent"]["reported_at"] is not None
    assert rows["legacy-agent"]["legacy_report"] is True
    assert rows["legacy-agent"]["reason"] == agent_netlink.LEGACY_NETLINK_BLOCKED_REASON


@pytest.mark.asyncio
async def test_an_agent_drops_off_once_it_reports_ready(
    client, auth_headers, db_session, factories
):
    """Rewriting the unit and restarting is the remediation; the next readiness
    report flipping the row to `ready` is the evidence, and must be enough on
    its own to take the host off the list."""
    agent = factories.agent(status="active", hostname="fixed-later")
    db_session.commit()

    await agent_telemetry.ingest_readiness(db_session, agent, _corpus_payload(_CURRENT))
    listed = (await client.get(_ENDPOINT, headers=auth_headers)).json()
    assert [row["hostname"] for row in listed] == ["fixed-later"]

    await agent_telemetry.ingest_readiness(db_session, agent, _neighbor_payload(state="ready"))
    assert (await client.get(_ENDPOINT, headers=auth_headers)).json() == []


@pytest.mark.asyncio
async def test_a_revoked_discovery_grant_drops_the_agent(
    client, auth_headers, db_session, factories
):
    """The daemon overwrites the row with `disabled` when discovery is revoked.
    A host that no longer runs discovery is not one this list should chase."""
    agent = factories.agent(status="active", hostname="grant-revoked")
    db_session.commit()

    await agent_telemetry.ingest_readiness(db_session, agent, _corpus_payload(_CURRENT))
    await agent_telemetry.ingest_readiness(db_session, agent, _neighbor_payload(state="disabled"))
    assert (await client.get(_ENDPOINT, headers=auth_headers)).json() == []


@pytest.mark.asyncio
async def test_empty_fleet_is_an_empty_list(client, auth_headers):
    resp = await client.get(_ENDPOINT, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_requires_admin(client, viewer_headers):
    assert (await client.get(_ENDPOINT, headers=viewer_headers)).status_code == 403


@pytest.mark.asyncio
async def test_is_not_shadowed_by_the_agent_detail_route(client, auth_headers):
    """`/{agent_id}` is declared later in the router; a literal segment placed
    after it would be parsed as an id and answer 422 instead."""
    resp = await client.get(_ENDPOINT, headers=auth_headers)
    assert resp.status_code != 422


def test_service_honours_the_limit(db_session, factories):
    for i in range(3):
        agent = factories.agent(status="active", hostname=f"blocked-{i}")
        db_session.add(
            AgentCapabilityReadiness(
                agent_id=agent.id,
                collector=agent_netlink.NEIGHBOR_COLLECTOR,
                state="unavailable",
                reason="refused",
                missing=[agent_netlink.NETLINK_MISSING_TOKEN],
            )
        )
    db_session.commit()
    assert len(agent_netlink.list_netlink_blocked_agents(db_session, limit=2)) == 2
    assert len(agent_netlink.list_netlink_blocked_agents(db_session)) == 3
