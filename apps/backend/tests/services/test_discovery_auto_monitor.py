"""Auto-monitor-on-discovery feeds the native monitoring engine, not the legacy bridge."""

import datetime

from app.db.models import AppSettings, IntegrationMonitor, MonitorItem, ScanJob, ScanResult
from app.services.discovery_merge import merge_scan_result


def _iso_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _pending_new_host(db_session, ip: str = "10.20.30.40"):
    job = ScanJob(
        target_cidr="10.20.30.0/24",
        scan_types_json='["nmap"]',
        status="completed",
        created_at=_iso_now(),
    )
    db_session.add(job)
    db_session.flush()

    result = ScanResult(
        scan_job_id=job.id,
        ip_address=ip,
        hostname="fresh-host",
        state="new",
        merge_status="pending",
        created_at=_iso_now(),
    )
    db_session.add(result)
    db_session.flush()
    return result


def _set_auto_monitor(db_session, enabled: bool) -> None:
    settings = db_session.query(AppSettings).first()
    if settings is None:
        settings = AppSettings()
        db_session.add(settings)
    settings.auto_monitor_on_discovery = enabled
    db_session.flush()


def test_accept_creates_native_monitor_when_enabled(db_session):
    _set_auto_monitor(db_session, True)
    result = _pending_new_host(db_session)

    merge_scan_result(db_session, result.id, "accept", actor="tester")

    items = db_session.query(MonitorItem).filter(MonitorItem.target_type == "hardware").all()
    assert len(items) == 1
    assert items[0].host == "10.20.30.40"
    assert items[0].check_type == "icmp"
    assert items[0].target_id == result.matched_entity_id
    # The legacy bridge must no longer be written to.
    assert db_session.query(IntegrationMonitor).count() == 0


def test_accept_creates_no_monitor_when_disabled(db_session):
    _set_auto_monitor(db_session, False)
    result = _pending_new_host(db_session, ip="10.20.30.41")

    merge_scan_result(db_session, result.id, "accept", actor="tester")

    assert db_session.query(MonitorItem).count() == 0
    # The host itself was still accepted — auto-monitoring is the only thing skipped.
    assert result.merge_status == "accepted"
