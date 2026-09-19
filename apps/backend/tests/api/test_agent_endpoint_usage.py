"""An endpoint nothing enrolled through is visible, not inferred from silence.

Spec §6 item 4. The failure this slice exists to end is invisible by
construction: the agent that would report "I cannot reach you" is the one that
cannot reach us. A count per endpoint is the only positive evidence an operator
has that an address they declared actually works.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_usage_counts_group_by_endpoint(client, factories, auth_headers):
    factories.agent(hostname="a", enrolled_via_endpoint="https://cb.example.com")
    factories.agent(hostname="b", enrolled_via_endpoint="https://cb.example.com")
    factories.agent(hostname="c", enrolled_via_endpoint="https://10.0.0.5")

    resp = await client.get("/api/v1/agents/endpoint-usage", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"https://cb.example.com": 2, "https://10.0.0.5": 1}


@pytest.mark.asyncio
async def test_agents_from_before_this_feature_are_not_counted(client, factories, auth_headers):
    factories.agent(hostname="old", enrolled_via_endpoint=None)

    resp = await client.get("/api/v1/agents/endpoint-usage", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {}


@pytest.mark.asyncio
async def test_endpoint_usage_is_not_parsed_as_an_agent_id(client, factories, auth_headers):
    """The route has to be declared before `/{agent_id}`.

    Declared after it, FastAPI matches `endpoint-usage` as an agent id and
    answers 422 — the same trap `/pending` and `/install-command` are placed
    ahead of. This asserts the ordering rather than trusting it.
    """
    resp = await client.get("/api/v1/agents/endpoint-usage", headers=auth_headers)

    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_endpoint_usage_requires_admin(client, factories, viewer_headers):
    """The fleet's addresses are deployment topology, not viewer-facing data."""
    resp = await client.get("/api/v1/agents/endpoint-usage", headers=viewer_headers)

    assert resp.status_code == 403, resp.text
