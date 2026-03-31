"""
Tests for discovery_import_service.batch_import().
"""

import datetime

from app.db.models import ScanJob, ScanResult
from app.schemas.discovery import BatchImportItem, BatchImportRequest
from app.services.discovery_import_service import batch_import


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def test_batch_import_finalizes_scan_results(db_session):
    """After batch_import, all processed ScanResult rows must have merge_status='accepted'."""
    # Create a scan job
    job = ScanJob(
        target_cidr="10.0.0.0/24",
        scan_types_json='["arp"]',
        status="completed",
        created_at=_now(),
    )
    db_session.add(job)
    db_session.flush()

    # Create 3 scan results (no MACs — forces the "new hardware" branch)
    results = []
    for i in range(3):
        r = ScanResult(
            scan_job_id=job.id,
            ip_address=f"10.0.0.{i + 1}",
            state="new",
            merge_status="pending",
            created_at=_now(),
        )
        db_session.add(r)
        results.append(r)
    db_session.flush()

    # Run batch import
    req = BatchImportRequest(
        items=[BatchImportItem(scan_result_id=r.id, overrides={}) for r in results]
    )
    batch_import(db_session, job.id, req, actor="test_user")
    db_session.expire_all()

    # Assert all results are finalised
    for r in results:
        updated = db_session.get(ScanResult, r.id)
        assert updated.merge_status == "accepted", f"Result {r.id} still '{updated.merge_status}'"
        assert updated.reviewed_at is not None, f"Result {r.id} reviewed_at is None"
        assert updated.reviewed_by == "test_user", (
            f"Result {r.id} reviewed_by='{updated.reviewed_by}'"
        )
        assert updated.matched_entity_id is not None, f"Result {r.id} matched_entity_id is None"
        assert updated.matched_entity_type == "hardware", (
            f"Result {r.id} matched_entity_type='{updated.matched_entity_type}'"
        )


def test_batch_import_created_includes_scan_result_id(db_session):
    """BatchImportCreated.scan_result_id must be populated for new hardware."""
    job = ScanJob(
        target_cidr="10.0.0.0/24",
        scan_types_json='["arp"]',
        status="completed",
        created_at=_now(),
    )
    db_session.add(job)
    db_session.flush()

    r = ScanResult(
        scan_job_id=job.id,
        ip_address="10.0.0.5",
        state="new",
        merge_status="pending",
        created_at=_now(),
    )
    db_session.add(r)
    db_session.flush()

    req = BatchImportRequest(items=[BatchImportItem(scan_result_id=r.id, overrides={})])
    resp = batch_import(db_session, job.id, req, actor="test")

    assert len(resp.created) == 1
    assert resp.created[0].scan_result_id == r.id, (
        f"Expected scan_result_id={r.id}, got {resp.created[0].scan_result_id}"
    )
