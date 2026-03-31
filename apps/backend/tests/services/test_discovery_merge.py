"""Test that enhanced_bulk_merge creates HardwareConnection rows via topology inference."""

import datetime

from app.db.models import HardwareConnection, ScanJob, ScanResult, Topology
from app.schemas.discovery import BulkAssignment, EnhancedBulkMergeRequest
from app.services.discovery_merge import enhanced_bulk_merge


def _iso_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def test_enhanced_bulk_merge_creates_hardware_connections(db_session):
    """After bulk-accepting a router + 3 endpoints on the same /24, HardwareConnections must exist."""
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
