"""`GET /api/v1/discovery/results` for the enriched set, and the fields it now carries.

A device discovery re-found is backfilled by `discovery_enrich` and lands at
`merge_status="auto_updated"`, which means it never appears in the review queue's
`status=pending` read. The review queue still has to be able to show it — "here
is what was filled in for you, and on which device" — so it asks for that set by
name and needs `matched_entity_name` and `enriched_fields_json` on the way back.
"""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy import event

from app.db.models import Hardware, ScanJob, ScanResult


def _iso_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _job(db) -> ScanJob:
    job = ScanJob(
        target_cidr="10.88.0.0/24",
        scan_types_json='["nmap"]',
        status="completed",
        created_at=_iso_now(),
    )
    db.add(job)
    db.flush()
    return job


def _hardware(db, name: str, ip: str) -> Hardware:
    hw = Hardware(name=name, ip_address=ip, role="server", source="discovery")
    db.add(hw)
    db.flush()
    return hw


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
async def test_enriched_results_are_fetchable_and_name_the_device(client, db_session, admin_token):
    job = _job(db_session)
    hw = _hardware(db_session, "_gateway", "10.88.0.1")
    _result(
        db_session,
        job,
        "10.88.0.1",
        state="matched",
        merge_status="auto_updated",
        matched_entity_type="hardware",
        matched_entity_id=hw.id,
        enriched_fields_json=[{"field": "mac_address", "value": "AA:BB:CC:DD:EE:FF"}],
        enriched_at=_iso_now(),
    )
    db_session.commit()

    resp = await client.get(
        "/api/v1/discovery/results?status=auto_updated",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [r["ip_address"] for r in body] == ["10.88.0.1"]
    assert body[0]["matched_entity_name"] == "_gateway"
    # JSONB comes back as a list; the schema serializes it, exactly as it does
    # for open_ports_json, so the client parses one shape and not two.
    assert json.loads(body[0]["enriched_fields_json"]) == [
        {"field": "mac_address", "value": "AA:BB:CC:DD:EE:FF"}
    ]


@pytest.mark.asyncio
async def test_an_enriched_row_is_absent_from_the_review_queue(client, db_session, admin_token):
    job = _job(db_session)
    hw = _hardware(db_session, "known", "10.88.0.2")
    _result(
        db_session,
        job,
        "10.88.0.2",
        state="matched",
        merge_status="auto_updated",
        matched_entity_type="hardware",
        matched_entity_id=hw.id,
    )
    _result(db_session, job, "10.88.0.3")
    db_session.commit()

    resp = await client.get(
        "/api/v1/discovery/results",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 200, resp.text
    assert "10.88.0.2" not in [r["ip_address"] for r in resp.json()]


@pytest.mark.asyncio
async def test_the_matched_name_costs_one_query_for_the_whole_page(client, db_session, admin_token):
    """Resolving it per row would be an N+1 on a read the queue does every load."""
    job = _job(db_session)
    for i in range(5):
        hw = _hardware(db_session, f"device-{i}", f"10.88.1.{i}")
        _result(
            db_session,
            job,
            f"10.88.1.{i}",
            state="matched",
            merge_status="auto_updated",
            matched_entity_type="hardware",
            matched_entity_id=hw.id,
        )
    db_session.commit()

    from app.db.session import engine

    hardware_selects: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        if "FROM hardware" in statement:
            hardware_selects.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        resp = await client.get(
            "/api/v1/discovery/results?status=auto_updated",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 5
    assert len(hardware_selects) == 1, hardware_selects


@pytest.mark.asyncio
async def test_limit_is_honoured(client, db_session, admin_token):
    """It was accepted by the client and ignored by the server until now."""
    job = _job(db_session)
    for i in range(5):
        _result(db_session, job, f"10.88.2.{i}")
    db_session.commit()

    resp = await client.get(
        "/api/v1/discovery/results?limit=2",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2
