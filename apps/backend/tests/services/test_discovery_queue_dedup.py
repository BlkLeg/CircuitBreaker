"""Regression coverage for repeated devices in the discovery review queue."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.time import utcnow_iso
from app.db.models import Hardware, ScanJob, ScanResult, Tenant
from app.services import discovery_service
from app.services.discovery_enrich import backfill_pending_matched
from app.services.discovery_merge import _auto_merge_result, merge_scan_result
from app.services.discovery_result_service import (
    build_and_classify_result,
    deduplicate_pending_result,
)


def job(db, **kw):
    row = ScanJob(
        target_cidr="192.168.0.0/24",
        scan_types_json='["nmap"]',
        status="running",
        created_at=utcnow_iso(),
        **kw,
    )
    db.add(row)
    db.flush()
    return row


def observation(db, scan=None, *, ip="192.168.0.66", mac="00:F3:61:CC:96:E0", **kw):
    row, _ = build_and_classify_result(
        db,
        scan or job(db),
        {"ip": ip, "mac_address": mac, **kw},
    )
    db.flush()
    return row


def pending(db):
    db.flush()
    return db.query(ScanResult).filter_by(merge_status="pending").order_by(ScanResult.id).all()


@pytest.mark.parametrize("trigger", ["api", "scheduler", "prober"])
def test_repeated_server_scans_keep_one_review_item_and_all_history(db_session, trigger):
    with (
        patch.object(discovery_service, "SessionLocal", return_value=db_session),
        patch.object(db_session, "close"),
    ):
        for _ in range(3):
            scan = job(db_session)
            output = discovery_service._scan_import(
                scan.id,
                {"triggered_by": trigger},
                [{"ip": "192.168.0.66", "mac_address": "00:f3:61:cc:96:e0"}],
            )
            assert output["stats"]["hosts_found"] == 1
    assert len(pending(db_session)) == 1
    assert db_session.query(ScanResult).count() == 3
    assert db_session.query(ScanResult).filter_by(merge_status="duplicate").count() == 2


def test_ip_only_finding_gains_mac_and_details_without_losing_existing_details(db_session):
    first = observation(db_session, mac=None, hostname="printer")
    second = observation(db_session, hostname="new-name", os_family="Linux")
    canonical = deduplicate_pending_result(db_session, second)
    assert canonical.id == first.id
    assert first.mac_address == second.mac_address
    assert first.os_family == "Linux"
    assert first.hostname == "printer"
    assert second.merge_status == "duplicate"
    third = observation(db_session, mac=None)
    deduplicate_pending_result(db_session, third)
    assert pending(db_session) == [first]


def test_single_scan_preserves_different_devices_at_one_ip(db_session):
    scan = job(db_session)
    with (
        patch.object(discovery_service, "SessionLocal", return_value=db_session),
        patch.object(db_session, "close"),
    ):
        discovery_service._scan_import(
            scan.id,
            {},
            [
                {"ip": "192.168.0.66", "mac_address": "00:F3:61:CC:96:E0"},
                {"ip": "192.168.0.66", "mac_address": "AA:BB:CC:DD:EE:FF"},
            ],
        )
    assert len(pending(db_session)) == 2


def test_different_macs_and_ambiguous_ip_only_finding_remain_separate(db_session):
    rows = [
        observation(db_session),
        observation(db_session, mac="AA:BB:CC:DD:EE:FF"),
        observation(db_session, mac=None),
    ]
    for row in rows:
        deduplicate_pending_result(db_session, row)
    assert pending(db_session) == rows


def test_same_mac_at_changed_ip_is_one_device(db_session):
    first = observation(db_session)
    second = observation(db_session, ip="192.168.0.67")
    deduplicate_pending_result(db_session, second)
    assert pending(db_session) == [first]


def test_same_addresses_in_different_tenants_are_separate(db_session):
    tenants = [Tenant(name="queue-a"), Tenant(name="queue-b")]
    db_session.add_all(tenants)
    db_session.flush()
    rows = [observation(db_session, job(db_session, tenant_id=t.id)) for t in tenants]
    for row in rows:
        deduplicate_pending_result(db_session, row)
    assert pending(db_session) == rows


def test_same_addresses_in_different_networks_are_separate(db_session, factories):
    networks = [factories.network(cidr="192.168.0.0/24") for _ in range(2)]
    rows = [observation(db_session, network_id=network.id) for network in networks]
    for row in rows:
        deduplicate_pending_result(db_session, row)
    assert pending(db_session) == rows


@pytest.mark.parametrize("source", ["docker", "proxmox"])
def test_integration_specific_identities_are_not_collapsed(db_session, source):
    first = observation(db_session, source_type=source)
    second = observation(db_session, source_type=source)
    deduplicate_pending_result(db_session, second)
    assert pending(db_session) == [first, second]


def test_startup_repairs_screenshot_duplicates_across_batches(db_session):
    for ip, count, mac in [
        ("192.168.0.66", 3, "00:F3:61:CC:96:E0"),
        ("192.168.0.79", 3, "92:87:ED:4C:09:A2"),
        ("192.168.0.2", 2, "C6:84:A1:14:8F:D6"),
    ]:
        for index in range(count):
            observation(db_session, ip=ip, mac=mac if index else None)
    assert len(pending(db_session)) == 8
    assert backfill_pending_matched(db_session, batch_limit=2) == 0
    assert len(pending(db_session)) == 3
    assert db_session.query(ScanResult).count() == 8
    assert backfill_pending_matched(db_session, batch_limit=2) == 0
    assert len(pending(db_session)) == 3


def test_startup_reclassifies_old_new_rows_after_device_enters_inventory(db_session):
    rows = [observation(db_session) for _ in range(3)]
    hw = Hardware(name="known-device", ip_address=rows[0].ip_address)
    db_session.add(hw)
    db_session.flush()
    assert backfill_pending_matched(db_session, batch_limit=1) == 3
    assert pending(db_session) == []
    assert hw.mac_address == rows[0].mac_address
    assert {row.merge_status for row in rows} == {"auto_updated"}


@pytest.mark.parametrize("automatic", [False, True])
def test_accept_rechecks_stale_new_results_and_creates_one_device(db_session, automatic):
    rows = [observation(db_session) for _ in range(2)]
    for row in rows:
        if automatic:
            _auto_merge_result(db_session, row, actor="test")
        else:
            merge_scan_result(db_session, row.id, "accept", actor="test")
    assert db_session.query(Hardware).count() == 1
    assert rows[1].matched_entity_id == rows[0].matched_entity_id


def test_accept_requires_review_if_identity_now_conflicts(db_session):
    row = observation(db_session)
    hw = Hardware(
        name="different-device", ip_address=row.ip_address, mac_address="AA:BB:CC:DD:EE:FF"
    )
    db_session.add(hw)
    db_session.flush()
    with pytest.raises(HTTPException) as error:
        merge_scan_result(db_session, row.id, "accept", actor="test")
    assert error.value.status_code == 409
    assert row.state == "conflict"
    assert row.merge_status == "pending"
    assert db_session.query(Hardware).count() == 1


@pytest.mark.parametrize("operation", ["ingest", "accept"])
def test_concurrent_identity_decisions_do_not_create_duplicates(setup_db, operation):
    """Exercise the empty-queue and empty-inventory races on real connections."""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        tenant = Tenant(name="queue-concurrent")
        db.add(tenant)
        db.flush()
        tenant_id = tenant.id
        scans = [job(db, tenant_id=tenant_id) for _ in range(2)]
        if operation == "accept":
            for scan in scans:
                observation(db, scan)
        scan_ids = [scan.id for scan in scans]
        db.commit()
    barrier = Barrier(2)

    def ingest(scan_id):
        with SessionLocal() as db:
            scan = db.get(ScanJob, scan_id)
            barrier.wait(timeout=10)
            if operation == "accept":
                row = db.query(ScanResult).filter_by(scan_job_id=scan.id).one()
                merge_scan_result(db, row.id, "accept", actor="test")
            else:
                row = observation(db, scan)
                deduplicate_pending_result(db, row)
            db.commit()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(ingest, scan_ids))
        with SessionLocal() as db:
            assert db.query(ScanResult).filter_by(
                tenant_id=tenant_id, merge_status="pending"
            ).count() == (1 if operation == "ingest" else 0)
            assert db.query(ScanResult).filter_by(tenant_id=tenant_id).count() == 2
            assert db.query(Hardware).filter_by(tenant_id=tenant_id).count() == (
                1 if operation == "accept" else 0
            )
    finally:
        with SessionLocal() as db:
            db.query(Hardware).filter_by(tenant_id=tenant_id).delete()
            db.query(ScanResult).filter(ScanResult.scan_job_id.in_(scan_ids)).delete()
            db.query(ScanJob).filter(ScanJob.id.in_(scan_ids)).delete()
            db.query(Tenant).filter_by(id=tenant_id).delete()
            db.commit()


def test_agent_accept_keeps_tenant_ownership_and_rescan_matches(db_session, factories):
    tenant = Tenant(name="queue-accept-owner")
    db_session.add(tenant)
    db_session.flush()
    agent = factories.agent(status="active", tenant_id=tenant.id)
    scan = job(db_session, tenant_id=tenant.id, scan_agent_id=agent.id)
    row, _ = build_and_classify_result(
        db_session, scan, {"ip": "192.168.0.66"}, discovery_agent_id=agent.id
    )
    db_session.flush()
    # Same private address in an unrelated tenant cannot become the match.
    foreign_hw = Hardware(name="other-tenant", ip_address=row.ip_address)
    db_session.add(foreign_hw)
    db_session.flush()
    merge_scan_result(db_session, row.id, "accept", actor="test")
    hw = db_session.get(Hardware, row.matched_entity_id)
    assert hw.id != foreign_hw.id
    assert hw.tenant_id == tenant.id
    rescan = job(db_session, tenant_id=tenant.id, scan_agent_id=agent.id)
    result, classification = build_and_classify_result(
        db_session, rescan, {"ip": row.ip_address}, discovery_agent_id=agent.id
    )
    assert classification == "matched"
    assert result.matched_entity_id == hw.id


def test_agent_hostname_is_not_copied_into_server_observation(db_session, factories):
    server_row = observation(db_session, mac=None)
    agent = factories.agent(status="active")
    scan = job(db_session, scan_agent_id=agent.id)
    agent_row, _ = build_and_classify_result(
        db_session,
        scan,
        {"ip": server_row.ip_address, "mac_address": "00:F3:61:CC:96:E0", "hostname": "agent-name"},
        discovery_agent_id=agent.id,
    )
    db_session.flush()
    deduplicate_pending_result(db_session, agent_row)
    assert server_row.hostname is None
    assert server_row.mac_address == agent_row.mac_address
    assert agent_row.hostname == "agent-name"
    assert agent_row.merge_status == "duplicate"


def test_distinct_conflicts_are_kept_for_review(db_session):
    db_session.add(Hardware(name="known-name", ip_address="192.168.0.66"))
    db_session.flush()
    first = observation(db_session, hostname="first-name")
    second = observation(db_session, hostname="second-name")
    repeat = observation(db_session, hostname="first-name")
    for row in (first, second, repeat):
        deduplicate_pending_result(db_session, row)
    assert pending(db_session) == [first, second]
    assert repeat.merge_status == "duplicate"
