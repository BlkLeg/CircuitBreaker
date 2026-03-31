"""
Unit tests for _auto_merge_known_devices() and prober dedup in discovery_service.py.

Verifies the four cases:
  1. Known device, nothing changed → auto_updated (silent)
  2. Known device, IP changed → stays pending (user review)
  3. Known device, MAC changed → stays pending (user review)
  4. New device (no match) → stays pending (user review)

Also verifies prober dedup (Task 5):
  5. Second prober run with the same devices must not create additional pending rows.
"""

from datetime import UTC, datetime
from unittest.mock import patch

from app.db.models import Hardware, ScanJob, ScanResult
from app.services.discovery_service import _auto_merge_known_devices, _scan_import


def _now():
    return datetime.now(UTC).isoformat()


def _make_job(db) -> int:
    job = ScanJob(
        status="running",
        triggered_by="test",
        target_cidr="10.0.0.0/24",
        scan_types_json='["nmap"]',
        hosts_found=0,
        hosts_new=0,
        hosts_updated=0,
        hosts_conflict=0,
        created_at=_now(),
    )
    db.add(job)
    db.flush()
    return job.id


def _make_hw(db, ip, mac=None) -> Hardware:
    hw = Hardware(
        name=ip,
        ip_address=ip,
        mac_address=mac,
        role="misc",
        source="discovery",
        discovered_at=_now(),
        last_seen=_now(),
    )
    db.add(hw)
    db.flush()
    return hw


def _make_result(db, job_id, ip, mac=None, status="pending") -> ScanResult:
    sr = ScanResult(
        scan_job_id=job_id,
        ip_address=ip,
        mac_address=mac,
        state="up",
        merge_status=status,
        created_at=_now(),
    )
    db.add(sr)
    db.flush()
    return sr


# ── Case 1: known device, nothing changed → auto_updated ─────────────────────


def test_known_device_unchanged_is_auto_updated(db_session):
    job_id = _make_job(db_session)
    _make_hw(db_session, ip="10.0.0.1", mac="aa:bb:cc:dd:ee:ff")
    sr = _make_result(db_session, job_id, ip="10.0.0.1", mac="aa:bb:cc:dd:ee:ff")

    _auto_merge_known_devices(db_session, job_id)

    db_session.refresh(sr)
    assert sr.merge_status == "auto_updated"


# ── Case 2: known device, IP changed → stays pending ─────────────────────────


def test_known_device_ip_changed_stays_pending(db_session):
    job_id = _make_job(db_session)
    _make_hw(db_session, ip="10.0.0.1", mac="aa:bb:cc:dd:ee:ff")
    # Same MAC, but new IP
    sr = _make_result(db_session, job_id, ip="10.0.0.99", mac="aa:bb:cc:dd:ee:ff")

    _auto_merge_known_devices(db_session, job_id)

    db_session.refresh(sr)
    assert sr.merge_status == "pending"


# ── Case 3: known device, MAC changed → stays pending ────────────────────────


def test_known_device_mac_changed_stays_pending(db_session):
    job_id = _make_job(db_session)
    _make_hw(db_session, ip="10.0.0.2", mac="aa:bb:cc:dd:ee:ff")
    # Same IP, but new MAC
    sr = _make_result(db_session, job_id, ip="10.0.0.2", mac="11:22:33:44:55:66")

    _auto_merge_known_devices(db_session, job_id)

    db_session.refresh(sr)
    assert sr.merge_status == "pending"


# ── Case 4: new device (no match) → stays pending ────────────────────────────


def test_new_device_stays_pending(db_session):
    job_id = _make_job(db_session)
    # No Hardware row for this IP/MAC
    sr = _make_result(db_session, job_id, ip="10.0.0.3", mac="de:ad:be:ef:00:01")

    _auto_merge_known_devices(db_session, job_id)

    db_session.refresh(sr)
    assert sr.merge_status == "pending"


# ── Case 5: match by IP only (no MAC on either side) → auto_updated ──────────


def test_match_by_ip_no_mac_is_auto_updated(db_session):
    job_id = _make_job(db_session)
    _make_hw(db_session, ip="10.0.0.4", mac=None)
    sr = _make_result(db_session, job_id, ip="10.0.0.4", mac=None)

    _auto_merge_known_devices(db_session, job_id)

    db_session.refresh(sr)
    assert sr.merge_status == "auto_updated"


# ── Case 6: hostname updated on known device ─────────────────────────────────


def test_hostname_updated_on_known_device(db_session):
    job_id = _make_job(db_session)
    hw = _make_hw(db_session, ip="10.0.0.5", mac="ca:fe:ba:be:00:01")
    hw.hostname = "old-hostname"
    db_session.flush()

    sr = _make_result(db_session, job_id, ip="10.0.0.5", mac="ca:fe:ba:be:00:01")
    sr.hostname = "new-hostname"
    db_session.flush()

    _auto_merge_known_devices(db_session, job_id)

    db_session.refresh(hw)
    assert hw.hostname == "new-hostname"


# ── Task 5: prober dedup — second run must not create duplicate pending rows ──

# 14 fake devices matching the "32 runs × 14 devices = 448 rows" scenario
_PROBER_DEVICES = [
    {"ip": f"192.168.1.{10 + i}", "mac_address": f"AA:BB:CC:DD:EE:{i:02X}"} for i in range(14)
]


def _prober_raw_results():
    return [
        {
            "ip": d["ip"],
            "mac_address": d["mac_address"],
            "hostname": f"host-{i}",
            "source": "nmap",
            "snmp_data": {},
        }
        for i, d in enumerate(_PROBER_DEVICES)
    ]


def _make_prober_job(db) -> ScanJob:
    job = ScanJob(
        target_cidr="192.168.1.0/24",
        scan_types_json='["nmap"]',
        status="completed",
        triggered_by="prober",
        created_at=datetime.now(UTC).isoformat(),
    )
    db.add(job)
    db.flush()
    return job


def test_prober_dedup_no_new_rows_on_second_run(db_session):
    """Second prober run with the same 14 devices must not add more pending ScanResult rows."""

    setup = {"triggered_by": "prober", "auto_merge": False}

    # Patch SessionLocal so _scan_import uses the test session; suppress its close() call.
    with patch("app.services.discovery_service.SessionLocal", return_value=db_session):
        db_session.close = lambda: None  # fixture owns lifecycle

        # Run 1
        job1 = _make_prober_job(db_session)
        _scan_import(job1.id, setup, _prober_raw_results())

        count_after_run1 = (
            db_session.query(ScanResult).filter(ScanResult.merge_status == "pending").count()
        )
        assert count_after_run1 == 14, (
            f"Expected 14 pending rows after run 1, got {count_after_run1}"
        )

        # Run 2 — same devices, new job
        job2 = _make_prober_job(db_session)
        _scan_import(job2.id, setup, _prober_raw_results())

    count_after_run2 = (
        db_session.query(ScanResult).filter(ScanResult.merge_status == "pending").count()
    )
    assert count_after_run2 == count_after_run1, (
        f"Duplicate rows created: expected {count_after_run1} pending rows after run 2, "
        f"got {count_after_run2}"
    )
