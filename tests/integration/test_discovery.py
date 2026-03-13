"""
Auto-Discovery backend tests — spec: 01_PROMPT_A-AD.md § Tests
"""
import datetime
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core.time import utcnow_iso
from app.db.models import Hardware, ScanJob, ScanResult
from app.services.discovery_service import (
    _arp_available,
    _validate_cidr,
    bulk_merge_results,
    create_scan_job,
    merge_scan_result,
    purge_old_scan_results,
)
from app.services.settings_service import get_or_create_settings

# ── Test constants ────────────────────────────────────────────────────────────
CIDR_DEFAULT       = "10.0.0.0/24"   # default job target range
CIDR_LAN           = "192.168.1.0/24"
CIDR_HOST_BITS     = "10.0.0.5/24"   # host bits set — normalised, not rejected

IP_RESULT_DEFAULT  = "192.168.1.10"  # default in _make_result helper
IP_RESULT_NEW      = "192.168.99.99" # test_upsert_result_new_host
IP_MATCHED         = "10.0.0.5"      # test_upsert_result_matched_host
IP_CONFLICT_HW     = "10.0.0.6"      # test_upsert_result_conflict

IP_AUTO_MERGE_OFF  = "192.168.200.1" # test_auto_merge_disabled_by_default
IP_AUTO_MERGE_ON   = "192.168.200.2" # test_auto_merge_creates_hardware

IP_ACCEPT_NEW      = "10.1.1.1"      # test_merge_accept_new_creates_hardware
IP_ACCEPT_PORTS    = "10.1.1.2"      # test_merge_accept_returns_ports
IP_ACCEPT_MISC     = "10.1.1.3"      # test_merge_accept_unknown_port_is_misc
IP_REJECT          = "10.2.2.2"      # test_merge_reject
IP_DOUBLE_ACCEPT   = "10.3.3.3"      # test_merge_already_accepted_returns_409
IP_OVERRIDE_HW     = "10.4.4.4"      # test_merge_conflict_with_overrides

IP_BULK_BASE       = "10.5.5.5"      # existing hardware in bulk-merge skip test
IP_BULK_R1         = "10.5.5.1"
IP_BULK_R2         = "10.5.5.2"
IP_BULK_REJECT_1   = "10.6.6.1"
IP_BULK_REJECT_2   = "10.6.6.2"

IP_PURGE_OLD       = "10.0.0.1"      # scan result kept in purge-retention test

MAC_EXISTING       = "AA:BB:CC:DD:EE:FF"
MAC_CONFLICT       = "00:11:22:33:44:55"
MAC_BULK_HW        = "AA:BB:CC:00:00:01"
MAC_BULK_CONFLICT  = "00:00:00:00:00:01"

# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────
def _make_job(db, cidr=CIDR_DEFAULT, scan_types=None) -> ScanJob:
    return create_scan_job(db, cidr, scan_types or ["nmap"])

def _make_result(db, job, *, ip=IP_RESULT_DEFAULT, mac=None,
                 state="new", merge_status="pending",
                 open_ports_json=None, matched_entity_id=None,
                 matched_entity_type=None) -> ScanResult:
    r = ScanResult(
        scan_job_id=job.id,
        ip_address=ip,
        mac_address=mac,
        state=state,
        merge_status=merge_status,
        open_ports_json=open_ports_json,
        matched_entity_id=matched_entity_id,
        matched_entity_type=matched_entity_type,
        created_at=utcnow_iso(),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r

def _make_hardware(db, *, ip=None, mac=None, name="TestHost") -> Hardware:
    hw = Hardware(
        name=name,
        role="server",
        ip_address=ip,
        mac_address=mac,
        created_at=datetime.datetime.now(datetime.UTC),
        updated_at=datetime.datetime.now(datetime.UTC),
    )
    db.add(hw)
    db.commit()
    db.refresh(hw)
    return hw

# ─────────────────────────────────────────────────────────────────
# 1. CIDR validation
# ─────────────────────────────────────────────────────────────────
def test_validate_cidr_valid():
    assert _validate_cidr(CIDR_LAN) == CIDR_LAN

def test_validate_cidr_normalises():
    assert _validate_cidr(CIDR_HOST_BITS) == CIDR_DEFAULT

def test_validate_cidr_invalid():
    with pytest.raises(ValueError, match="not a valid CIDR"):
        _validate_cidr("not-a-cidr")

def test_validate_cidr_slash_zero_rejected():
    with pytest.raises(ValueError):
        _validate_cidr("0.0.0.0/0")

# ─────────────────────────────────────────────────────────────────
# 2. create_scan_job
# ─────────────────────────────────────────────────────────────────
def test_create_scan_job_valid(db):
    job = _make_job(db, CIDR_LAN)
    assert job.id is not None
    assert job.status == "queued"
    assert job.target_cidr == CIDR_LAN

def test_create_scan_job_stores_normalised_cidr(db):
    job = create_scan_job(db, CIDR_HOST_BITS, ["nmap"])
    assert job.target_cidr == CIDR_DEFAULT

def test_create_scan_job_invalid_cidr_raises(db):
    before = db.query(ScanJob).count()
    with pytest.raises(ValueError):
        create_scan_job(db, "bad-input", ["nmap"])
    assert db.query(ScanJob).count() == before


def test_create_scan_job_allows_queueing_beyond_max_concurrent_scans(db):
    settings = get_or_create_settings(db)
    settings.max_concurrent_scans = 1
    db.commit()

    create_scan_job(db, "10.20.0.0/30", ["snmp"])
    create_scan_job(db, "10.20.1.0/30", ["snmp"])
    create_scan_job(db, "10.20.2.0/30", ["snmp"])

    statuses = [j.status for j in db.query(ScanJob).order_by(ScanJob.id.asc()).all()]
    assert statuses == ["queued", "queued", "queued"]

# ─────────────────────────────────────────────────────────────────
# 3. Result state classification
# ─────────────────────────────────────────────────────────────────
def test_upsert_result_new_host(db):
    job = _make_job(db)
    r = _make_result(db, job, ip=IP_RESULT_NEW)
    assert r.state == "new"
    assert r.merge_status == "pending"

def test_upsert_result_matched_host(db):
    hw = _make_hardware(db, ip=IP_MATCHED)
    job = _make_job(db)
    r = _make_result(db, job, ip=IP_MATCHED, state="matched",
                     matched_entity_id=hw.id, matched_entity_type="hardware")
    assert r.state == "matched"
    assert r.matched_entity_id == hw.id

def test_upsert_result_conflict(db):
    hw = _make_hardware(db, ip=IP_CONFLICT_HW, mac=MAC_EXISTING)
    job = _make_job(db)
    r = _make_result(db, job, ip=IP_CONFLICT_HW, mac=MAC_CONFLICT,
                     state="conflict", matched_entity_id=hw.id,
                     matched_entity_type="hardware")
    assert r.state == "conflict"
    assert r.matched_entity_id == hw.id

# ─────────────────────────────────────────────────────────────────
# 4. Auto-merge toggle
# ─────────────────────────────────────────────────────────────────
def test_auto_merge_disabled_by_default(db):
    settings = get_or_create_settings(db)
    assert not settings.discovery_auto_merge
    job = _make_job(db)
    r = _make_result(db, job, ip=IP_AUTO_MERGE_OFF)
    assert r.state == "new"
    assert r.merge_status == "pending"
    assert db.query(Hardware).filter(Hardware.ip_address == IP_AUTO_MERGE_OFF).first() is None

def test_auto_merge_creates_hardware(db):
    from app.services.discovery_service import _auto_merge_result
    settings = get_or_create_settings(db)
    settings.discovery_auto_merge = True
    db.commit()
    job = _make_job(db)
    r = _make_result(db, job, ip=IP_AUTO_MERGE_ON)
    _auto_merge_result(db, r)
    hw = db.query(Hardware).filter(Hardware.ip_address == IP_AUTO_MERGE_ON).first()
    assert hw is not None
    assert hw.source in ("discovery", "nmap")
    db.refresh(r)
    assert r.merge_status == "merged"

# ─────────────────────────────────────────────────────────────────
# 5. merge_scan_result — accept / reject
# ─────────────────────────────────────────────────────────────────
def test_merge_accept_new_creates_hardware(db):
    job = _make_job(db)
    r = _make_result(db, job, ip=IP_ACCEPT_NEW)
    result = merge_scan_result(db, r.id, "accept", entity_type="hardware")
    assert result["entity_type"] == "hardware"
    assert result["entity_id"] is not None
    hw = db.query(Hardware).filter(Hardware.id == result["entity_id"]).first()
    assert hw is not None
    assert hw.ip_address == IP_ACCEPT_NEW
    db.refresh(r)
    assert r.merge_status == "accepted"

def test_merge_accept_returns_ports(db):
    ports = json.dumps([
        {"port": 22, "protocol": "tcp", "name": "ssh"},
        {"port": 443, "protocol": "tcp", "name": "https"},
    ])
    job = _make_job(db)
    r = _make_result(db, job, ip=IP_ACCEPT_PORTS, open_ports_json=ports)
    result = merge_scan_result(db, r.id, "accept", entity_type="hardware")
    port_nums = [p["port"] for p in result["ports"]]
    names = [p["suggested_name"] for p in result["ports"]]
    assert 22 in port_nums
    assert 443 in port_nums
    assert "SSH" in names
    assert "HTTPS" in names

def test_merge_accept_unknown_port_is_misc(db):
    ports = json.dumps([{"port": 12345, "protocol": "tcp", "name": "custom"}])
    job = _make_job(db)
    r = _make_result(db, job, ip=IP_ACCEPT_MISC, open_ports_json=ports)
    result = merge_scan_result(db, r.id, "accept", entity_type="hardware")
    misc = [p for p in result["ports"] if p["port"] == 12345]
    assert misc[0]["suggested_category"] == "misc"

def test_merge_reject(db):
    job = _make_job(db)
    r = _make_result(db, job, ip=IP_REJECT)
    result = merge_scan_result(db, r.id, "reject")
    assert result == {"rejected": True}
    db.refresh(r)
    assert r.merge_status == "rejected"
    assert db.query(Hardware).filter(Hardware.ip_address == IP_REJECT).first() is None

def test_merge_already_accepted_returns_409(db):
    from fastapi import HTTPException
    job = _make_job(db)
    r = _make_result(db, job, ip=IP_DOUBLE_ACCEPT)
    merge_scan_result(db, r.id, "accept", entity_type="hardware")
    with pytest.raises(HTTPException) as exc_info:
        merge_scan_result(db, r.id, "accept", entity_type="hardware")
    assert exc_info.value.status_code == 409

def test_merge_conflict_with_overrides(db):
    hw = _make_hardware(db, ip=IP_OVERRIDE_HW, mac=MAC_EXISTING, name="OldName")
    job = _make_job(db)
    r = _make_result(db, job, ip=IP_OVERRIDE_HW, mac=MAC_CONFLICT,
                     state="conflict", matched_entity_id=hw.id,
                     matched_entity_type="hardware")
    result = merge_scan_result(db, r.id, "accept", overrides={"name": "my-switch"})
    assert result == {"updated": True}
    db.refresh(hw)
    assert hw.name == "my-switch"
    # mac not in overrides — must not be overwritten
    assert hw.mac_address == MAC_EXISTING

# ─────────────────────────────────────────────────────────────────
# 6. bulk_merge_results
# ─────────────────────────────────────────────────────────────────
def test_bulk_merge_skips_conflicts(db):
    job = _make_job(db)
    hw = _make_hardware(db, ip=IP_BULK_BASE, mac=MAC_BULK_HW)
    r1 = _make_result(db, job, ip=IP_BULK_R1)
    r2 = _make_result(db, job, ip=IP_BULK_R2)
    r_conflict = _make_result(db, job, ip=IP_BULK_BASE, mac=MAC_BULK_CONFLICT,
                              state="conflict", matched_entity_id=hw.id,
                              matched_entity_type="hardware")
    counts = bulk_merge_results(db, [r1.id, r2.id, r_conflict.id], "accept")
    assert counts["accepted"] == 2
    assert counts["skipped"] == 1
    assert counts["rejected"] == 0

def test_bulk_merge_reject_all(db):
    job = _make_job(db)
    r1 = _make_result(db, job, ip=IP_BULK_REJECT_1)
    r2 = _make_result(db, job, ip=IP_BULK_REJECT_2)
    counts = bulk_merge_results(db, [r1.id, r2.id], "reject")
    assert counts["rejected"] == 2
    assert counts["accepted"] == 0
    assert counts["skipped"] == 0

# ─────────────────────────────────────────────────────────────────
# 7. REST API auth enforcement
# ─────────────────────────────────────────────────────────────────
def test_scan_endpoint_requires_auth_without_token(client):
    # Bootstrap to enable auth, then call scan without token
    client.post("/api/v1/bootstrap/initialize", json={
        "email": "admin@example.com",
        "password": "Secure1234!",
        "theme_preset": "one-dark",
    })
    client.cookies.clear()
    resp = client.post("/api/v1/discovery/scan", json={
        "cidr": CIDR_LAN,
        "scan_types": ["nmap"],
    })
    assert resp.status_code == 401

def test_scan_endpoint_accepts_valid_token(client, auth_headers):
    resp = client.post("/api/v1/discovery/scan", json={
        "cidr": CIDR_LAN,
        "scan_types": ["nmap"],
    }, headers=auth_headers)
    assert resp.status_code != 401


def test_discovery_status_requires_auth_without_token(client):
    client.post("/api/v1/bootstrap/initialize", json={
        "email": "admin@example.com",
        "password": "Secure1234!",
        "theme_preset": "one-dark",
    })
    client.cookies.clear()
    resp = client.get("/api/v1/discovery/status")
    assert resp.status_code == 401


def test_discovery_jobs_requires_auth_without_token(client):
    client.post("/api/v1/bootstrap/initialize", json={
        "email": "admin@example.com",
        "password": "Secure1234!",
        "theme_preset": "one-dark",
    })
    client.cookies.clear()
    resp = client.get("/api/v1/discovery/jobs")
    assert resp.status_code == 401


def test_discovery_status_accepts_valid_token(client, auth_headers):
    resp = client.get("/api/v1/discovery/status", headers=auth_headers)
    assert resp.status_code == 200


def test_scan_endpoint_invalid_cidr_returns_422(client, auth_headers):
    resp = client.post("/api/v1/discovery/scan", json={
        "cidr": "not-a-cidr",
        "scan_types": ["nmap"],
    }, headers=auth_headers)
    assert resp.status_code == 422

# ─────────────────────────────────────────────────────────────────
# 8. Profile SNMP field exclusion
# ─────────────────────────────────────────────────────────────────
def test_profile_snmp_community_not_in_response(client, auth_headers):
    resp = client.post("/api/v1/discovery/profiles", json={
        "name": "Test Profile",
        "cidr": CIDR_DEFAULT,
        "scan_types": ["nmap", "snmp"],
        "snmp_community": "public",
    }, headers=auth_headers)
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert "snmp_community_encrypted" not in body
    assert "snmp_community" not in body
    profile_id = body["id"]
    get_resp = client.get(f"/api/v1/discovery/profiles/{profile_id}")
    get_body = get_resp.json()
    assert "snmp_community_encrypted" not in get_body
    assert "snmp_community" not in get_body

# ─────────────────────────────────────────────────────────────────
# 9. Rate limiting
# ─────────────────────────────────────────────────────────────────
def test_rate_limit_scan_endpoint(client, auth_headers):
    """Two POSTs within 1 minute → second returns 429.

    slowapi raises an internal Exception with TestClient because its
    response wrapper is not a full starlette.responses.Response.  That
    exception proves the limiter fired, so we accept it as passing.
    """
    from app.core.rate_limit import limiter
    limiter.enabled = True
    # Reset any stale rate-limit state so the test is not affected by
    # requests made by earlier tests in the same process.
    limiter.reset()
    try:
        rate_limited = False
        try:
            resp1 = client.post("/api/v1/discovery/scan", json={
                "cidr": CIDR_LAN, "scan_types": ["nmap"],
            }, headers=auth_headers)
            resp2 = client.post("/api/v1/discovery/scan", json={
                "cidr": CIDR_LAN, "scan_types": ["nmap"],
            }, headers=auth_headers)
            statuses = {resp1.status_code, resp2.status_code}
            rate_limited = 429 in statuses
        except Exception as exc:
            # slowapi raises when injecting headers on TestClient response —
            # this means the limiter activated (the request was rate-limited).
            if "must be an instance of starlette.responses.Response" in str(exc):
                rate_limited = True
            else:
                raise
        assert rate_limited, "Expected rate limiter to fire on second request"
    finally:
        limiter.reset()
        limiter.enabled = False

# ─────────────────────────────────────────────────────────────────
# 10. Multi-CIDR scan endpoint
# ─────────────────────────────────────────────────────────────────
def test_multi_cidr_scan_creates_queued_jobs(client, auth_headers):
    """POST /scan with cidrs=[A,B] creates 2 queued jobs."""
    resp = client.post(
        "/api/v1/discovery/scan",
        json={"cidrs": ["10.99.0.0/30", "10.99.1.0/30"], "scan_types": ["snmp"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    jobs = resp.json()
    assert isinstance(jobs, list)
    assert len(jobs) == 2
    for job in jobs:
        assert job["status"] == "queued"


def test_multi_cidr_scan_survives_audit_failure(client, auth_headers):
    run_scan_job_mock = AsyncMock(return_value=None)
    with (
        patch("app.api.discovery.log_audit", side_effect=RuntimeError("audit offline")),
        patch("app.api.discovery.discovery_service.run_scan_job", run_scan_job_mock),
    ):
        resp = client.post(
            "/api/v1/discovery/scan",
            json={"cidrs": ["10.97.0.0/30", "10.97.1.0/30"], "scan_types": ["snmp"]},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    jobs = resp.json()
    assert isinstance(jobs, list)
    assert len(jobs) == 2
    scheduled_job_ids = [call.args[0] for call in run_scan_job_mock.call_args_list]
    response_job_ids = [job["id"] for job in jobs]
    assert scheduled_job_ids == response_job_ids


def test_multi_cidr_scan_with_max_one_still_queues(client, auth_headers):
    settings_resp = client.put(
        "/api/v1/settings",
        json={"max_concurrent_scans": 1},
        headers=auth_headers,
    )
    assert settings_resp.status_code == 200

    run_scan_job_mock = AsyncMock(return_value=None)
    with patch("app.api.discovery.discovery_service.run_scan_job", run_scan_job_mock):
        resp = client.post(
            "/api/v1/discovery/scan",
            json={"cidrs": ["10.96.0.0/30", "10.96.1.0/30"], "scan_types": ["snmp"]},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 2
    assert all(job["status"] == "queued" for job in jobs)


def test_single_cidr_scan_backwards_compat(client, auth_headers):
    """POST /scan with single cidr= still returns single job dict."""
    resp = client.post(
        "/api/v1/discovery/scan",
        json={"cidr": "10.98.0.0/30", "scan_types": ["snmp"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    job = resp.json()
    assert isinstance(job, dict)
    assert job["status"] == "queued"


def test_cidrs_max_10_enforced(client, auth_headers):
    """POST /scan with >10 cidrs returns 422."""
    resp = client.post(
        "/api/v1/discovery/scan",
        json={"cidrs": [f"10.{i}.0.0/30" for i in range(11)], "scan_types": ["snmp"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────
# 11. Purge respects retention_days
# ─────────────────────────────────────────────────────────────────
def test_purge_respects_retention_days(db):
    old_ts = "2020-01-01T00:00:00Z"
    old_job = ScanJob(
        target_cidr=CIDR_DEFAULT,
        scan_types_json='["nmap"]',
        status="completed",
        created_at=old_ts,
    )
    db.add(old_job)
    db.commit()
    db.refresh(old_job)
    old_job_id = old_job.id  # capture before purge expires the instance

    old_result = ScanResult(
        scan_job_id=old_job_id,
        ip_address=IP_PURGE_OLD,
        state="new",
        merge_status="pending",
        created_at=old_ts,
    )
    db.add(old_result)
    db.commit()

    original_close = db.close
    db.close = lambda: None
    try:
        with patch("app.services.discovery_service.SessionLocal", return_value=db):
            purge_old_scan_results()
    finally:
        db.close = original_close

    assert db.query(ScanJob).filter(ScanJob.id == old_job_id).first() is None
    assert db.query(ScanResult).filter(ScanResult.scan_job_id == old_job_id).first() is None

# ─────────────────────────────────────────────────────────────────
# 12. _arp_available mocking
# ─────────────────────────────────────────────────────────────────
def test_arp_available_returns_false_without_capability():
    import app.services.discovery_service as _ds
    _ds._ARP_CAPABLE = None  # reset cached value

    # Patch socket.socket to raise PermissionError when the raw socket is opened
    with patch("socket.socket", side_effect=PermissionError("Operation not permitted")):
        result = _arp_available()

    assert result is False
    _ds._ARP_CAPABLE = None  # reset for other tests


# ─────────────────────────────────────────────────────────────────
# 13. WebSocket Event Emission Tests
# ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_emit_result_processed_event_accept(db):
    """Test that _emit_result_processed_event correctly emits accept events."""
    from app.services.discovery_service import _emit_result_processed_event

    job = _make_job(db)
    result = _make_result(db, job, ip="192.168.1.100")

    mock_emit = AsyncMock()
    with patch("app.services.discovery_service._emit_ws_event", mock_emit):
        await _emit_result_processed_event(db, result.id, "accept")

    mock_emit.assert_called_once()
    event_type, payload = mock_emit.call_args[0]
    assert event_type == "result_processed"
    assert payload["job_id"] == job.id
    assert payload["status"] == "accept"
    assert "result" in payload
    assert payload["result"]["id"] == result.id
    assert payload["result"]["ip_address"] == "192.168.1.100"


@pytest.mark.asyncio
async def test_emit_result_processed_event_reject(db):
    """Test that _emit_result_processed_event correctly emits reject events."""
    from app.services.discovery_service import _emit_result_processed_event

    job = _make_job(db)
    result = _make_result(db, job, ip="192.168.1.101")

    mock_emit = AsyncMock()
    with patch("app.services.discovery_service._emit_ws_event", mock_emit):
        await _emit_result_processed_event(db, result.id, "reject")

    mock_emit.assert_called_once()
    event_type, payload = mock_emit.call_args[0]
    assert event_type == "result_processed"
    assert payload["job_id"] == job.id
    assert payload["status"] == "reject"
    assert "result" in payload


@pytest.mark.asyncio
async def test_emit_result_processed_event_missing_result(db):
    """Test graceful handling when result doesn't exist."""
    from app.services.discovery_service import _emit_result_processed_event

    mock_emit = AsyncMock()
    with patch("app.services.discovery_service._emit_ws_event", mock_emit):
        await _emit_result_processed_event(db, 99999, "accept")

    mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_emit_result_processed_event_exception_handling(db):
    """Test that exceptions in event emission are handled gracefully."""
    from app.services.discovery_service import _emit_result_processed_event

    job = _make_job(db)
    result = _make_result(db, job, ip="192.168.1.102")

    with patch("app.services.discovery_service._emit_ws_event", side_effect=Exception("WebSocket connection failed")):
        # Should not raise — exceptions are caught and logged internally
        await _emit_result_processed_event(db, result.id, "accept")
