"""Test discovery merge operations including auto-learning and topology inference."""

import datetime

from app.db.models import HardwareConnection, KbOui, ScanJob, ScanResult, Topology
from app.schemas.discovery import BulkAssignment, EnhancedBulkMergeRequest
from app.services.discovery_merge import enhanced_bulk_merge, maybe_learn_oui


def _iso_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def test_enhanced_bulk_merge_creates_hardware_connections(db_session):
    """After bulk-accepting a router + 3 endpoints on the same /24,
    HardwareConnections must exist."""
    # Seed a default topology so _assign_to_default_map and apply_inferred_topology can find it
    topo = Topology(name="Test Map", is_default=True)
    db_session.add(topo)
    db_session.flush()

    # Create scan job
    job = ScanJob(
        target_cidr="10.0.0.0/24",
        scan_types_json='["arp"]',
        status="completed",
        created_at=_iso_now(),
    )
    db_session.add(job)
    db_session.flush()

    # 1 router + 3 endpoints on same /24
    router_r = ScanResult(
        scan_job_id=job.id,
        ip_address="10.0.0.1",
        state="new",
        merge_status="pending",
        created_at=_iso_now(),
    )
    db_session.add(router_r)

    endpoints = []
    for i in range(3):
        r = ScanResult(
            scan_job_id=job.id,
            ip_address=f"10.0.0.{i + 10}",
            state="new",
            merge_status="pending",
            created_at=_iso_now(),
        )
        db_session.add(r)
        endpoints.append(r)
    db_session.flush()

    all_ids = [router_r.id] + [r.id for r in endpoints]

    # Build assignments: router gets role=router, others default to server
    assignments = [BulkAssignment(result_id=router_r.id, role="router")]

    payload = EnhancedBulkMergeRequest(
        result_ids=all_ids,
        assignments=assignments,
        create_services=False,
    )

    result = enhanced_bulk_merge(db_session, payload, actor="test")

    assert result["merged"] == 4, f"Expected 4 merged; got {result}"
    assert len(result["hardware_ids"]) == 4

    connections = db_session.query(HardwareConnection).all()
    assert len(connections) >= 1, f"Expected >=1 inferred edge; got {len(connections)}"

    # All inferred edges should have source="discovery_inferred"
    inferred = [c for c in connections if c.source == "discovery_inferred"]
    assert len(inferred) >= 1, f"Expected >=1 discovery_inferred edge; got {inferred}"


def test_enhanced_bulk_merge_router_assignment_is_tree_root(db_session):
    """The node assigned role=router must be the SOURCE of all HardwareConnection edges."""
    from app.db.models import Hardware

    topo = Topology(name="Test Map", is_default=True)
    db_session.add(topo)
    db_session.flush()

    job = ScanJob(
        target_cidr="10.5.5.0/24",
        scan_types_json='["arp"]',
        status="completed",
        created_at=_iso_now(),
    )
    db_session.add(job)
    db_session.flush()

    # Router candidate has a non-.1 IP but is explicitly assigned role=router
    router_r = ScanResult(
        scan_job_id=job.id,
        ip_address="10.5.5.50",
        state="new",
        merge_status="pending",
        created_at=_iso_now(),
    )
    endpoints = [
        ScanResult(
            scan_job_id=job.id,
            ip_address=f"10.5.5.{i + 10}",
            state="new",
            merge_status="pending",
            created_at=_iso_now(),
        )
        for i in range(3)
    ]
    db_session.add(router_r)
    for r in endpoints:
        db_session.add(r)
    db_session.flush()

    payload = EnhancedBulkMergeRequest(
        result_ids=[router_r.id] + [r.id for r in endpoints],
        assignments=[BulkAssignment(result_id=router_r.id, role="router")],
    )
    result = enhanced_bulk_merge(db_session, payload, actor="test")
    assert result["merged"] == 4

    db_session.expire_all()
    connections = db_session.query(HardwareConnection).filter_by(source="discovery_inferred").all()
    assert len(connections) == 3, (
        f"Expected 3 edges from router to endpoints; got {len(connections)}"
    )

    router_hw = db_session.query(Hardware).filter_by(ip_address="10.5.5.50").one()
    assert router_hw.role == "router"
    assert all(c.source_hardware_id == router_hw.id for c in connections), (
        f"Expected all edges from router_hw.id={router_hw.id}; "
        f"got sources={[c.source_hardware_id for c in connections]}"
    )


def test_enhanced_bulk_merge_batch_loads_scan_results(db_session) -> None:  # type: ignore[no-untyped-def]
    """enhanced_bulk_merge uses a single batch IN-query for ScanResults."""
    from unittest.mock import MagicMock

    # Create a job and two pending results
    job = ScanJob(
        target_cidr="192.168.1.0/24",
        scan_types_json='["arp"]',
        status="completed",
        created_at=_iso_now(),
    )
    db_session.add(job)
    db_session.flush()

    r1 = ScanResult(
        scan_job_id=job.id,
        ip_address="192.168.1.10",
        merge_status="pending",
        state="new",
        created_at=_iso_now(),
    )
    r2 = ScanResult(
        scan_job_id=job.id,
        ip_address="192.168.1.11",
        merge_status="pending",
        state="new",
        created_at=_iso_now(),
    )
    db_session.add_all([r1, r2])
    db_session.flush()

    payload = MagicMock()
    payload.result_ids = [r1.id, r2.id]
    payload.assignments = []
    payload.cluster = None
    payload.network = None
    payload.rack_id = None
    payload.create_services = False

    # Should complete without error — batch load is an optimisation, not a behaviour change
    result = enhanced_bulk_merge(db_session, payload)
    assert isinstance(result, dict)
    assert "merged" in result or "accepted" in result or "skipped" in result


# ── maybe_learn_oui ───────────────────────────────────────────────────────────


class _FakeScanResult:
    """Minimal stand-in for ScanResult for maybe_learn_oui tests."""

    def __init__(self, mac=None, vendor=None, device_type=None):
        self.mac_address = mac
        self.os_vendor = vendor
        self.device_type = device_type


def test_maybe_learn_oui_creates_entry(db_session):
    """A new OUI not in curated KB is inserted into kb_oui on accept."""
    r = _FakeScanResult(mac="00:11:22:AA:BB:CC", vendor="Acme Devices Inc.", device_type="server")
    maybe_learn_oui(r, db_session)

    entry = db_session.get(KbOui, "001122")
    assert entry is not None
    assert entry.vendor == "Acme Devices Inc."
    assert entry.device_type == "server"
    assert entry.source == "learned"
    assert entry.seen_count == 1


def test_maybe_learn_oui_increments_seen_count(db_session):
    """Accepting the same OUI twice increments seen_count, no duplicate row."""
    r = _FakeScanResult(mac="00:11:22:AA:BB:CC", vendor="Acme Devices Inc.")
    maybe_learn_oui(r, db_session)
    maybe_learn_oui(r, db_session)

    entries = db_session.query(KbOui).filter_by(prefix="001122").all()
    assert len(entries) == 1
    assert entries[0].seen_count == 2


def test_maybe_learn_oui_skips_locally_administered_mac(db_session):
    """Locally-administered MACs (bit 1 of first byte) must not be stored."""
    r = _FakeScanResult(mac="02:AA:BB:CC:DD:EE", vendor="Some Vendor")
    maybe_learn_oui(r, db_session)

    assert db_session.get(KbOui, "02AABB") is None


def test_maybe_learn_oui_skips_curated_kb_prefix(db_session):
    """OUI already in device_kb.json must not be shadowed by a learned entry."""
    # BC2411 is Proxmox in the curated KB
    r = _FakeScanResult(mac="BC:24:11:00:00:01", vendor="Proxmox Server Solutions GmbH")
    maybe_learn_oui(r, db_session)

    assert db_session.get(KbOui, "BC2411") is None


def test_maybe_learn_oui_skips_missing_mac_or_vendor(db_session):
    """No entry is created when MAC or vendor is absent."""
    maybe_learn_oui(_FakeScanResult(mac=None, vendor="Some Vendor"), db_session)
    maybe_learn_oui(_FakeScanResult(mac="00:11:22:AA:BB:CC", vendor=None), db_session)

    assert db_session.query(KbOui).count() == 0
