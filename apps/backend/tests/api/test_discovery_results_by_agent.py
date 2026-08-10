"""`GET /api/v1/discovery/results` filtered to one agent's own findings.

This is the data the Slice 3 §7 "Create monitor from this agent" action needs
(`plans/2026-08-04-cbi-agent-slice3-remote-probe.md:414`): Agent Detail has to
be able to list the devices *this* agent discovered before it can offer to
build a monitor from one with that agent preselected as the vantage.

`ScanResult.discovery_agent_id` has existed on the model since Slice 4
(`db/models.py`) but was neither exposed by `ScanResultOut` nor filterable, so
no caller could tell one agent's findings from another's — or from the
server's own scans.
"""

from __future__ import annotations

import datetime

import pytest

from app.db.models import ScanJob, ScanResult


def _iso_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _job(db) -> ScanJob:
    job = ScanJob(
        target_cidr="10.77.0.0/24",
        scan_types_json='["connect"]',
        status="completed",
        created_at=_iso_now(),
    )
    db.add(job)
    db.flush()
    return job


def _result(db, job, ip, **kwargs) -> ScanResult:
    defaults = {
        "scan_job_id": job.id,
        "ip_address": ip,
        "state": "new",
        "merge_status": "pending",
        "created_at": _iso_now(),
    }
    defaults.update(kwargs)
    result = ScanResult(**defaults)
    db.add(result)
    db.flush()
    return result


@pytest.mark.asyncio
async def test_results_can_be_filtered_to_one_agents_findings(
    client, db_session, factories, admin_token
):
    agent = factories.agent(status="active")
    other = factories.agent(status="active")
    job = _job(db_session)
    _result(db_session, job, "10.77.0.11", discovery_agent_id=agent.id)
    _result(db_session, job, "10.77.0.12", discovery_agent_id=other.id)
    # A server-executed scan: no agent at all. It must not leak into an
    # agent-scoped list, or "found by this agent" would be a lie.
    _result(db_session, job, "10.77.0.13")
    db_session.commit()

    resp = await client.get(
        f"/api/v1/discovery/results?agent_id={agent.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [r["ip_address"] for r in body] == ["10.77.0.11"]
    assert body[0]["discovery_agent_id"] == agent.id


@pytest.mark.asyncio
async def test_results_expose_the_discovering_agent(client, db_session, factories, admin_token):
    """Attribution has to survive serialization even on an unfiltered read —
    the review queue shows findings from every source at once."""
    agent = factories.agent(status="active")
    job = _job(db_session)
    _result(db_session, job, "10.77.0.21", discovery_agent_id=agent.id)
    _result(db_session, job, "10.77.0.22")
    db_session.commit()

    resp = await client.get(
        "/api/v1/discovery/results",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 200, resp.text
    by_ip = {r["ip_address"]: r for r in resp.json()}
    assert by_ip["10.77.0.21"]["discovery_agent_id"] == agent.id
    assert by_ip["10.77.0.22"]["discovery_agent_id"] is None


@pytest.mark.asyncio
async def test_agent_filter_composes_with_the_status_filter(
    client, db_session, factories, admin_token
):
    """The action lists devices that were *accepted* into Hardware, which are
    no longer `pending` — so the agent filter has to work alongside
    `status=all` rather than replace it."""
    agent = factories.agent(status="active")
    job = _job(db_session)
    _result(
        db_session,
        job,
        "10.77.0.31",
        discovery_agent_id=agent.id,
        merge_status="merged",
        matched_entity_type="hardware",
        matched_entity_id=4242,
    )
    _result(db_session, job, "10.77.0.32", discovery_agent_id=agent.id)
    db_session.commit()

    merged = await client.get(
        f"/api/v1/discovery/results?status=merged&agent_id={agent.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    every = await client.get(
        f"/api/v1/discovery/results?status=all&agent_id={agent.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert merged.status_code == 200, merged.text
    assert [r["ip_address"] for r in merged.json()] == ["10.77.0.31"]
    # matched_entity_id is what the monitor's target_id is built from.
    assert merged.json()[0]["matched_entity_id"] == 4242
    assert sorted(r["ip_address"] for r in every.json()) == ["10.77.0.31", "10.77.0.32"]
