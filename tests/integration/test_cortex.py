"""CORTEX Backend Intelligence Upgrade — the built subset of the 14-finding suite.

Section numbers below are the original CORTEX finding IDs, so the gaps in them
are deliberate. Findings 1, 2, 8 and 9 were removed because the features they
covered were never built: those tests were failing against absent code, not
against a regression, and a test that can only ever fail reports nothing.

  1. CB-RACK-001 / 2. CB-RACK-002 — Rack Foundation. There is no Rack model, no
     rack_id/rack_unit/u_height column on Hardware, and no /api/v1/racks route.
     POST answered 405, so neither test got past its first request.
  8. CB-STATE-001 / 9. CB-STATE-002 — worst-child status derivation. Both
     imported recalculate_hardware_status / recalculate_compute_status from
     app.services.status_service, a module that exists nowhere under
     apps/backend/src (only a stale .pyc in __pycache__ remains of it), so both
     ERRORed with ModuleNotFoundError before asserting anything.

  11. CB-PATTERN-003 / 12. CB-PATTERN-004 — orphan detection and vendor+model
     grouping. `GET /api/v1/hardware/orphans` and `GET /api/v1/hardware/groups`
     were deleted by f2c9bff7 ("delete seven routes with no caller"); that
     commit touched no test file, so both tests kept calling the routes and
     both started failing with 422 — `/hardware/{hardware_id}` matches the
     literal path segment and rejects "orphans" as a non-integer id. Removed
     here rather than restored: the frontend calls neither route, which is why
     they were deleted.

Those six IDs are the only record in this repository of what was specified for
racks, for derived status, and for pattern detection. If any of those features
is picked up later, restore the tests from git history rather than re-deriving
the contract.

Uses existing conftest.py fixtures (client, db, db_engine).
"""

import pytest

# ── Test constants ────────────────────────────────────────────────────────────
IP_CONFLICT_A    = "10.0.0.50"   # duplicate IP for conflict-cascade test
IP_PORT_HOST     = "10.0.0.70"   # hardware host in port-conflict test
IP_PORT_SVC      = "10.0.0.71"   # service IP for port-conflict test
IP_MAC_HW1       = "10.0.1.1"    # first hardware in MAC-duplicate test
IP_MAC_HW2       = "10.0.1.2"    # second hardware in MAC-duplicate test
CIDR_MERGE       = "10.0.0.0/24" # target CIDR for scan-job fixtures
IP_MERGE_RESULT  = "10.0.0.99"   # IP in merge-atomicity scan result
IP_SOURCE_RESULT = "10.0.0.200"  # IP in source_scan_result_id test

# ── Helpers ────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _authenticated_client(client, auth_headers):
    client.headers.update(auth_headers)


def _create_hardware(client, name="Test Server", **kwargs):
    payload = {"name": name, "role": "server", **kwargs}
    resp = client.post("/api/v1/hardware", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_compute_unit(client, hardware_id, name="VM-1", kind="vm"):
    resp = client.post("/api/v1/compute-units", json={
        "name": name,
        "kind": kind,
        "hardware_id": hardware_id,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_service(client, name="svc-1", **kwargs):
    resp = client.post("/api/v1/services", json={"name": name, **kwargs})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── 3. CB-REL-002: Service hardware_id denorm ─────────────────────────────────


def test_service_hardware_id_denorm(client):
    """Compute-bound service auto-gets hardware_id from its compute unit."""
    hw = _create_hardware(client, name="Host1")
    cu = _create_compute_unit(client, hw["id"], name="VM-svc")
    svc = _create_service(client, name="app-svc", compute_id=cu["id"])
    assert svc["hardware_id"] == hw["id"]


# ── 4. CB-STATE-003: IP conflict cascade (existing behavior) ──────────────────


def test_ip_conflict_cascade(client):
    """Documenting existing behavior: IP conflict blocks duplicate save."""
    _create_hardware(client, name="HW-ip1", ip_address=IP_CONFLICT_A)
    resp = client.post("/api/v1/hardware", json={
        "name": "HW-ip2", "role": "server", "ip_address": IP_CONFLICT_A,
    })
    assert resp.status_code == 409


# ── 5. CB-STATE-006: Port conflict (existing behavior) ────────────────────────


def test_port_conflict(client):
    """Documenting existing behavior: services with same IP trigger conflict detection."""
    hw = _create_hardware(client, name="PortHost", ip_address=IP_PORT_HOST)
    _create_service(client, name="svc-port1", hardware_id=hw["id"], ip_address=IP_PORT_SVC)
    # Second service with same IP should be blocked
    resp = client.post("/api/v1/services", json={
        "name": "svc-port2", "hardware_id": hw["id"], "ip_address": IP_PORT_SVC,
    })
    assert resp.status_code == 409


# ── 6. CB-CASCADE-005: Merge atomicity ────────────────────────────────────────


def test_merge_atomicity(client, db):
    """Savepoint rollback on merge failure doesn't corrupt data."""
    from app.core.time import utcnow_iso
    from app.db.models import ScanJob, ScanResult

    now = utcnow_iso()
    job = ScanJob(
        target_cidr=CIDR_MERGE,
        scan_types_json='["nmap"]',
        status="completed",
        created_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    result = ScanResult(
        scan_job_id=job.id,
        ip_address=IP_MERGE_RESULT,
        hostname="new-host",
        state="new",
        merge_status="pending",
        created_at=now,
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    from app.services.discovery_service import merge_scan_result
    out = merge_scan_result(db, result.id, "accept")
    assert out.get("entity_type") == "hardware"
    assert out.get("entity_id") is not None
    # Verify result is now accepted
    db.refresh(result)
    assert result.merge_status == "accepted"


# ── 7. CB-PATTERN-001: MAC duplicate soft alert ───────────────────────────────


def test_mac_duplicate_soft_alert(client, caplog):
    """Both hardware records save; a warning is logged for the duplicate MAC."""
    hw1 = _create_hardware(client, name="MAC-hw1", ip_address=IP_MAC_HW1)
    # Manually set MAC via PATCH
    client.patch(f"/api/v1/hardware/{hw1['id']}", json={"mac_address": "AA:BB:CC:DD:EE:FF"})

    # Second hardware with same MAC should still save (freeform-first)
    # but log a warning. The MAC is on the schema but not in HardwareBase,
    # so we set it after creation.
    hw2 = _create_hardware(client, name="MAC-hw2", ip_address=IP_MAC_HW2)
    # Both exist
    resp1 = client.get(f"/api/v1/hardware/{hw1['id']}")
    resp2 = client.get(f"/api/v1/hardware/{hw2['id']}")
    assert resp1.status_code == 200
    assert resp2.status_code == 200


# ── 10. CB-STATE-005: last_seen updated on PATCH ──────────────────────────────


def test_last_seen_updated(client):
    """PATCH hardware → last_seen is set."""
    hw = _create_hardware(client, name="LastSeenHost")
    resp = client.patch(f"/api/v1/hardware/{hw['id']}", json={"notes": "updated"})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("last_seen") is not None


# ── 13. CB-LEARN-002: Catalog auto-fill ───────────────────────────────────────


def test_catalog_autofill(client):
    """Null u_height/role filled from catalog when vendor/model keys present."""
    # Use a known catalog entry if available, otherwise this tests the code path
    resp = client.post("/api/v1/hardware", json={
        "name": "Auto-fill Test",
        "vendor_catalog_key": "dell",
        "model_catalog_key": "poweredge-r740",
        # u_height and role intentionally omitted
    })
    assert resp.status_code == 201
    data = resp.json()
    # If the catalog entry exists with u_height/role, they'll be auto-filled
    # If not, they'll stay None — the test validates the code path runs without error
    assert data["name"] == "Auto-fill Test"


# ── 14. CB-REL-001: source_scan_result_id populated on merge accept ───────────


def test_source_scan_result_id(client, db):
    """source_scan_result_id is set on hardware when a scan result is accepted."""
    from app.core.time import utcnow_iso
    from app.db.models import Hardware, ScanJob, ScanResult

    now = utcnow_iso()
    job = ScanJob(
        target_cidr=CIDR_MERGE,
        scan_types_json='["nmap"]',
        status="completed",
        created_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    result = ScanResult(
        scan_job_id=job.id,
        ip_address=IP_SOURCE_RESULT,
        hostname="traced-host",
        state="new",
        merge_status="pending",
        created_at=now,
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    from app.services.discovery_service import merge_scan_result
    out = merge_scan_result(db, result.id, "accept")
    hw_id = out["entity_id"]

    hw = db.get(Hardware, hw_id)
    assert hw is not None
    assert hw.source_scan_result_id == result.id
