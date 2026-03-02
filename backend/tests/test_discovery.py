"""
Auto-Discovery backend tests — spec: 01_PROMPT_A-AD.md § Tests
"""
import json
import datetime
from unittest.mock import patch

import pytest

from app.db.models import Hardware, ScanJob, ScanResult
from app.services.discovery_service import (
    _validate_cidr,
    create_scan_job,
    merge_scan_result,
    bulk_merge_results,
    purge_old_scan_results,
    _arp_available,
)
from app.services.settings_service import get_or_create_settings
from app.core.time import utcnow_iso
# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────
def _make_job(db, cidr="10.0.0.0/24", scan_types=None) -> ScanJob:
    return create_scan_job(db, cidr, scan_types or ["nmap"])
def _make_result(db, job, *, ip="192.168.1.10", mac=None,
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
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(hw)
    db.commit()
    db.refresh(hw)
    return hw
# ─────────────────────────────────────────────────────────────────
# 1. CIDR validation
# ─────────────────────────────────────────────────────────────────
def test_validate_cidr_valid():
    assert _validate_cidr("192.168.1.0/24") == "192.168.1.0/24"
def test_validate_cidr_normalises():
    # Host bits set — normalised, not rejected
    assert _validate_cidr("192.168.1.5/24") == "192.168.1.0/24"
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
    job = _make_job(db, "192.168.1.0/24")
    assert job.id is not None
    assert job.status == "queued"
    assert job.target_cidr == "192.168.1.0/24"
def test_create_scan_job_stores_normalised_cidr(db):
    job = create_scan_job(db, "10.0.0.5/24", ["nmap"])
    assert job.target_cidr == "10.0.0.0/24"
def test_create_scan_job_invalid_cidr_raises(db):
    before = db.query(ScanJob).count()
    with pytest.raises(ValueError):
        create_scan_job(db, "bad-input", ["nmap"])
    assert db.query(ScanJob).count() == before
# ─────────────────────────────────────────────────────────────────
# 3. Result state classification
# ─────────────────────────────────────────────────────────────────
def test_upsert_result_new_host(db):
    job = _make_job(db)
    r = _make_result(db, job, ip="192.168.99.99")
    assert r.state == "new"
    assert r.merge_status == "pending"
def test_upsert_result_matched_host(db):
    hw = _make_hardware(db, ip="10.0.0.5")
    job = _make_job(db)
    r = _make_result(db, job, ip="10.0.0.5", state="matched",
                     matched_entity_id=hw.id, matched_entity_type="hardware")
    assert r.state == "matched"
    assert r.matched_entity_id == hw.id
def test_upsert_result_conflict(db):
    hw = _make_hardware(db, ip="10.0.0.6", mac="AA:BB:CC:DD:EE:FF")
    job = _make_job(db)
    r = _make_result(db, job, ip="10.0.0.6", mac="00:11:22:33:44:55",
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
    r = _make_result(db, job, ip="192.168.200.1")
    assert r.state == "new"
    assert r.merge_status == "pending"
    assert db.query(Hardware).filter(Hardware.ip_address == "192.168.200.1").first() is None
def test_auto_merge_creates_hardware(db):
    from app.services.discovery_service import _auto_merge_result
    settings = get_or_create_settings(db)
    settings.discovery_auto_merge = True
    db.commit()
    job = _make_job(db)
    r = _make_result(db, job, ip="192.168.200.2")
    _auto_merge_result(db, r)
    hw = db.query(Hardware).filter(Hardware.ip_address == "192.168.200.2").first()
    assert hw is not None
    assert hw.source in ("discovery", "nmap")
    db.refresh(r)
    assert r.merge_status == "merged"
# ─────────────────────────────────────────────────────────────────
# 5. merge_scan_result — accept / reject
# ─────────────────────────────────────────────────────────────────
def test_merge_accept_new_creates_hardware(db):
    job = _make_job(db)
    r = _make_result(db, job, ip="10.1.1.1")
    result = merge_scan_result(db, r.id, "accept", entity_type="hardware")
    assert result["entity_type"] == "hardware"
    assert result["entity_id"] is not None
    hw = db.query(Hardware).filter(Hardware.id == result["entity_id"]).first()
    assert hw is not None
    assert hw.ip_address == "10.1.1.1"
    db.refresh(r)
    assert r.merge_status == "accepted"
def test_merge_accept_returns_ports(db):
    ports = json.dumps([
        {"port": 22, "protocol": "tcp", "name": "ssh"},
        {"port": 443, "protocol": "tcp", "name": "https"},
    ])
    job = _make_job(db)
    r = _make_result(db, job, ip="10.1.1.2", open_ports_json=ports)
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
    r = _make_result(db, job, ip="10.1.1.3", open_ports_json=ports)
    result = merge_scan_result(db, r.id, "accept", entity_type="hardware")
    misc = [p for p in result["ports"] if p["port"] == 12345]
    assert misc[0]["suggested_category"] == "misc"
def test_merge_reject(db):
    job = _make_job(db)
    r = _make_result(db, job, ip="10.2.2.2")
    result = merge_scan_result(db, r.id, "reject")
    assert result == {"rejected": True}
    db.refresh(r)
    assert r.merge_status == "rejected"
    assert db.query(Hardware).filter(Hardware.ip_address == "10.2.2.2").first() is None
def test_merge_already_accepted_returns_409(db):
    from fastapi import HTTPException
    job = _make_job(db)
    r = _make_result(db, job, ip="10.3.3.3")
    merge_scan_result(db, r.id, "accept", entity_type="hardware")
    with pytest.raises(HTTPException) as exc_info:
        merge_scan_result(db, r.id, "accept", entity_type="hardware")
    assert exc_info.value.status_code == 409
def test_merge_conflict_with_overrides(db):
    hw = _make_hardware(db, ip="10.4.4.4", mac="AA:BB:CC:DD:EE:FF", name="OldName")
    job = _make_job(db)
    r = _make_result(db, job, ip="10.4.4.4", mac="00:11:22:33:44:55",
                     state="conflict", matched_entity_id=hw.id,
                     matched_entity_type="hardware")
    result = merge_scan_result(db, r.id, "accept", overrides={"name": "my-switch"})
    assert result == {"updated": True}
    db.refresh(hw)
    assert hw.name == "my-switch"
    # mac not in overrides — must not be overwritten
    assert hw.mac_address == "AA:BB:CC:DD:EE:FF"
# ─────────────────────────────────────────────────────────────────
# 6. bulk_merge_results
# ─────────────────────────────────────────────────────────────────
def test_bulk_merge_skips_conflicts(db):
    job = _make_job(db)
    hw = _make_hardware(db, ip="10.5.5.5", mac="AA:BB:CC:00:00:01")
    r1 = _make_result(db, job, ip="10.5.5.1")
    r2 = _make_result(db, job, ip="10.5.5.2")
    r_conflict = _make_result(db, job, ip="10.5.5.5", mac="00:00:00:00:00:01",
                              state="conflict", matched_entity_id=hw.id,
                              matched_entity_type="hardware")
    counts = bulk_merge_results(db, [r1.id, r2.id, r_conflict.id], "accept")
    assert counts["accepted"] == 2
    assert counts["skipped"] == 1
    assert counts["rejected"] == 0
def test_bulk_merge_reject_all(db):
    job = _make_job(db)
    r1 = _make_result(db, job, ip="10.6.6.1")
    r2 = _make_result(db, job, ip="10.6.6.2")
    counts = bulk_merge_results(db, [r1.id, r2.id], "reject")
    assert counts["rejected"] == 2
    assert counts["accepted"] == 0
    assert counts["skipped"] == 0
# ─────────────────────────────────────────────────────────────────
# 7. REST API auth enforcement
# ─────────────────────────────────────────────────────────────────
def test_scan_endpoint_requires_auth_without_token(client):
    resp = client.post("/api/v1/discovery/scan", json={
        "cidr": "192.168.1.0/24",
        "scan_types": ["nmap"],
    })
    assert resp.status_code == 401
def test_scan_endpoint_accepts_valid_token(client, auth_headers):
    resp = client.post("/api/v1/discovery/scan", json={
        "cidr": "192.168.1.0/24",
        "scan_types": ["nmap"],
    }, headers=auth_headers)
    assert resp.status_code != 401
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
        "cidr": "10.0.0.0/24",
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
    """Two POSTs within 1 minute → second returns 429."""
    from app.core.rate_limit import limiter
    limiter.enabled = True
    try:
        resp1 = client.post("/api/v1/discovery/scan", json={
            "cidr": "192.168.1.0/24", "scan_types": ["nmap"],
        }, headers=auth_headers)
        resp2 = client.post("/api/v1/discovery/scan", json={
            "cidr": "192.168.1.0/24", "scan_types": ["nmap"],
        }, headers=auth_headers)
        statuses = {resp1.status_code, resp2.status_code}
        assert 429 in statuses
    finally:
        limiter.enabled = False
# ─────────────────────────────────────────────────────────────────
# 10. WebSocket auth
# ─────────────────────────────────────────────────────────────────
def test_websocket_auth_rejects_invalid_token(client):
    with client.websocket_connect("/api/v1/discovery/stream") as ws:
        ws.send_text("totally-invalid-token")
        data = ws.receive_text()
        msg = json.loads(data)
        assert msg.get("error") == "unauthorized"
        with pytest.raises(Exception):
            ws.receive_text()
def test_websocket_auth_accepts_valid_token(client, auth_headers):
    token = auth_headers["Authorization"].split(" ", 1)[1]
    with client.websocket_connect("/api/v1/discovery/stream") as ws:
        ws.send_text(token)
        data = ws.receive_text()
        msg = json.loads(data)
        assert msg.get("status") == "connected"
# ─────────────────────────────────────────────────────────────────
# 11. Purge respects retention_days
# ─────────────────────────────────────────────────────────────────
def test_purge_respects_retention_days(db):
    old_ts = "2020-01-01T00:00:00Z"
    old_job = ScanJob(
        target_cidr="10.0.0.0/24",
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
        ip_address="10.0.0.1",
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
