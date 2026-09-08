"""The agent's reported outbound-spool backlog and eviction/refusal counters (Task
16 / D-12, Phase 3), as they appear on agent detail, the presence feed, and the
telemetry endpoint.

Split out of the former tests/api/test_agents_api.py.
"""

import pytest


@pytest.mark.asyncio
async def test_get_agent_detail_exposes_spool_state(client, factories, viewer_headers):
    """`AgentRead` carries the reported spool backlog (Task 16, D-12). NULL
    means "never reported" — an agent predating `HeartbeatPayload` — and must
    survive serialization as null rather than being coerced to 0."""
    from app.core.time import utcnow

    never_reported = factories.agent(status="active")
    reporting = factories.agent(status="active")
    reporting.spool_depth = 12
    reporting.spool_bytes = 4096
    reporting.spool_reported_at = utcnow()
    factories.session.commit()

    resp = await client.get(f"/api/v1/agents/{reporting.id}", headers=viewer_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["spool_depth"] == 12
    assert body["spool_bytes"] == 4096
    assert body["spool_reported_at"] is not None

    resp = await client.get(f"/api/v1/agents/{never_reported.id}", headers=viewer_headers)
    body = resp.json()
    assert body["spool_depth"] is None
    assert body["spool_bytes"] is None
    assert body["spool_reported_at"] is None


@pytest.mark.asyncio
async def test_presence_exposes_spool_eviction_state(client, factories, viewer_headers):
    """Phase 3: destroyed history rides the fleet presence poll, because an
    outage that filled one agent's spool usually filled several and an
    operator should not have to open each one. NULL must survive as null: a 0
    would read as "confirmed, nothing lost"."""
    from datetime import UTC, datetime

    never_reported = factories.agent(status="active")
    lossy = factories.agent(status="active")
    lossy.spool_evicted_frames = 9412
    lossy.spool_evicted_bytes = 33554432
    lossy.spool_evicted_oldest_at = datetime(2026, 9, 1, tzinfo=UTC)
    lossy.spool_evicted_newest_at = datetime(2026, 9, 3, 18, 30, tzinfo=UTC)
    lossy.spool_evicted_reported_at = datetime(2026, 9, 3, 18, 31, tzinfo=UTC)
    factories.session.commit()

    resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)
    assert resp.status_code == 200
    rows = {row["agent_id"]: row for row in resp.json()}

    assert rows[lossy.id]["spool_evicted_frames"] == 9412
    assert rows[lossy.id]["spool_evicted_bytes"] == 33554432
    assert rows[lossy.id]["spool_evicted_oldest_at"] is not None
    assert rows[lossy.id]["spool_evicted_newest_at"] is not None

    assert rows[never_reported.id]["spool_evicted_frames"] is None
    assert rows[never_reported.id]["spool_evicted_bytes"] is None
    assert rows[never_reported.id]["spool_evicted_oldest_at"] is None


@pytest.mark.asyncio
async def test_agent_telemetry_spool_block_carries_evictions_and_refusals(
    client, factories, viewer_headers
):
    """The detail page's `spool` block reports three separate facts: a backlog
    that will drain, history the agent destroyed, and frames this server
    refused. They have different remedies, so they stay apart."""
    from datetime import UTC, datetime

    agent = factories.agent(status="active")
    agent.spool_depth = 4096
    agent.spool_bytes = 67108864
    agent.spool_evicted_frames = 9412
    agent.spool_evicted_bytes = 33554432
    agent.spool_evicted_oldest_at = datetime(2026, 9, 1, tzinfo=UTC)
    agent.spool_evicted_newest_at = datetime(2026, 9, 3, 18, 30, tzinfo=UTC)
    agent.refused_frames = 512
    agent.refused_frames_last_reason = "capability_withheld"
    agent.refused_frames_last_at = datetime(2026, 9, 4, tzinfo=UTC)
    factories.session.commit()

    resp = await client.get(f"/api/v1/agents/{agent.id}/telemetry", headers=viewer_headers)
    assert resp.status_code == 200
    spool = resp.json()["spool"]

    assert spool["depth"] == 4096
    assert spool["evicted_frames"] == 9412
    assert spool["evicted_bytes"] == 33554432
    assert spool["evicted_oldest_at"] is not None
    assert spool["evicted_newest_at"] is not None
    assert spool["refused_frames"] == 512
    assert spool["refused_last_reason"] == "capability_withheld"


@pytest.mark.asyncio
async def test_agent_telemetry_spool_block_is_null_for_a_never_reporting_agent(
    client, factories, viewer_headers
):
    """Old agent -> new server: nothing reported means null, not zero, so the
    UI renders nothing rather than a reassuring "0 lost"."""
    agent = factories.agent(status="active")

    resp = await client.get(f"/api/v1/agents/{agent.id}/telemetry", headers=viewer_headers)
    spool = resp.json()["spool"]

    assert spool["evicted_frames"] is None
    assert spool["evicted_bytes"] is None
    assert spool["evicted_oldest_at"] is None
    assert spool["refused_frames"] is None
    assert spool["refused_last_reason"] is None
