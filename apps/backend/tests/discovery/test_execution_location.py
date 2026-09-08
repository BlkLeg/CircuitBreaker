"""Tests for where a discovery profile or job says it will execute — both on
the profile API (create/patch) and on the read schemas for profiles and jobs.

Split out of the former tests/test_discovery.py.
"""

import pytest

from tests.discovery.helpers import (
    JOBS_URL,
    PROFILES_URL,
    _agent_profile_payload,
    _dispatched_job,
    _eligible_agent,
    _make_profile,
    _make_scan_job_with_results,
)

# ---------------------------------------------------------------------------
# Execution location on the profile API (Slice 4, D-7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_profile_persists_execution_location(
    client, auth_headers, db_session, factories
):
    """The API writes `scan_agent_id` through and derives the canonical CIDR."""
    from app.db.models import DiscoveryProfile

    # Eligible, not merely active: §3's creation-time gate refuses an
    # agent-targeted profile the named agent could not run.
    agent = _eligible_agent(
        factories,
        interfaces=[{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.44.0.9/24"]}],
    )
    payload = {
        "name": "agent-owned",
        "cidr": "10.44.0.9/24",
        "scan_types": ["agent_connect"],
        "scan_agent_id": agent.id,
    }
    resp = await client.post(PROFILES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    row = db_session.get(DiscoveryProfile, resp.json()["id"])
    assert row.scan_agent_id == agent.id
    assert row.normalized_cidr == "10.44.0.0/24"


@pytest.mark.asyncio
async def test_create_profile_ignores_managed_by_in_the_body(client, auth_headers, db_session):
    """`managed_by` is server-set only — a request that claims it is not obeyed.

    Honouring it would let a client park a row on the partial unique index that
    the system-profile bootstrap owns.
    """
    from app.db.models import DiscoveryProfile

    payload = {
        "name": "impostor",
        "cidr": "10.45.0.0/24",
        "scan_types": ["nmap"],
        "managed_by": "system",
    }
    resp = await client.post(PROFILES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert db_session.get(DiscoveryProfile, resp.json()["id"]).managed_by is None


@pytest.mark.asyncio
async def test_update_profile_ignores_managed_by_in_the_body(client, auth_headers, db_session):
    from app.db.models import DiscoveryProfile

    profile_id = _make_profile(db_session, scan_types_json='["nmap"]')
    resp = await client.patch(
        f"{PROFILES_URL}/{profile_id}",
        json={"name": "renamed", "managed_by": "system"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert db_session.get(DiscoveryProfile, profile_id).managed_by is None


# ---------------------------------------------------------------------------
# Execution location on the read schemas (Slice 4, §6 / Task 26)
# ---------------------------------------------------------------------------
#
# `DiscoveryProfileOut` and `ScanJobOut` are the only shapes the Discovery page
# and the history page ever see. Until this task they carried neither
# `scan_agent_id` nor `source_type`, so a job that ran from an agent's vantage
# point was indistinguishable from one the server swept — which is exactly the
# distinction plan §6 asks the job cards and the history list to render, and the
# one the "Scan from" selector has to read back to show what a profile is
# already set to.


@pytest.mark.asyncio
async def test_profile_read_reports_its_execution_location_and_provenance(
    client, auth_headers, factories
):
    """A profile's agent, its automatic/user provenance and its pause state all
    survive the round-trip through `DiscoveryProfileOut`."""
    agent = _eligible_agent(factories)
    created = await client.post(
        PROFILES_URL, json=_agent_profile_payload(agent), headers=auth_headers
    )
    assert created.status_code == 200, created.text
    assert created.json()["scan_agent_id"] == agent.id
    # A profile written through the API is the operator's, never the bootstrap's.
    assert created.json()["managed_by"] is None
    assert created.json()["paused_at"] is None

    listed = await client.get(PROFILES_URL, headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = next(p for p in listed.json() if p["id"] == created.json()["id"])
    assert row["scan_agent_id"] == agent.id


@pytest.mark.asyncio
async def test_server_profile_read_reports_no_agent(client, auth_headers, db_session):
    """The field has to be a field, not a constant: a profile with no agent is
    the existing server engine and must read as `null`."""
    profile_id = _make_profile(db_session, scan_types_json='["nmap"]')
    listed = await client.get(PROFILES_URL, headers=auth_headers)
    row = next(p for p in listed.json() if p["id"] == profile_id)
    assert row["scan_agent_id"] is None


@pytest.mark.asyncio
async def test_job_read_reports_the_vantage_point_it_ran_from(
    client, auth_headers, db_session, factories
):
    """Plan §6: the job card and the history row show *where* a scan executed.
    `source_type` is what separates an agent sweep from the server's own, and
    `scan_agent_id` is what the agent-name link is built from."""
    agent = _eligible_agent(factories)
    job = _dispatched_job(db_session, agent)

    resp = await client.get(f"{JOBS_URL}/{job.id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["scan_agent_id"] == agent.id
    assert resp.json()["source_type"] == "agent"

    listed = await client.get(JOBS_URL, headers=auth_headers)
    row = next(j for j in listed.json() if j["id"] == job.id)
    assert row["scan_agent_id"] == agent.id
    assert row["source_type"] == "agent"


@pytest.mark.asyncio
async def test_server_job_read_reports_no_agent(client, auth_headers, db_session):
    """The other side of the same branch — a server scan keeps reading as one."""
    job_id, _ = _make_scan_job_with_results(db_session)
    resp = await client.get(f"{JOBS_URL}/{job_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["scan_agent_id"] is None
    assert resp.json()["source_type"] == "manual"
