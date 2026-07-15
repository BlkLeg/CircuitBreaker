"""Orchestrator tests: real DB rows, mocked feed/network I/O."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.time import utcnow_iso
from app.db.models import (
    AppSettings,
    NetworkPrivacySnapshot,
    PrivacyScoreHistory,
    ScanJob,
    ScanResult,
)
from app.services import privacy_score
from app.services.threat_feed import ThreatFeed

_CHECKS_ALL_OK = [
    {
        "check_id": "captive_portal",
        "status": "ok",
        "evidence": "204",
        "detected_at": "2026-07-15T00:00:00+00:00",
    },
    {
        "check_id": "dns_tamper",
        "status": "ok",
        "evidence": "match",
        "detected_at": "2026-07-15T00:00:00+00:00",
    },
    {
        "check_id": "dns_filtering_absent",
        "status": "unknown",
        "evidence": "feed unavailable",
        "detected_at": "2026-07-15T00:00:00+00:00",
    },
]


def _seed_scan_result(db_session, hardware_id: int, ports: list[int]) -> ScanResult:
    job = ScanJob(scan_types_json="[]", created_at=utcnow_iso())
    db_session.add(job)
    db_session.flush()
    result = ScanResult(
        scan_job_id=job.id,
        ip_address="192.0.2.10",
        open_ports_json=[{"port": p, "service": "svc"} for p in ports],
        matched_entity_type="hardware",
        matched_entity_id=hardware_id,
        created_at=utcnow_iso(),
    )
    db_session.add(result)
    db_session.flush()
    return result


def _set_windscribe(db_session, enabled: bool) -> None:
    settings_row = db_session.query(AppSettings).first()
    if settings_row is None:
        settings_row = AppSettings(id=1)
        db_session.add(settings_row)
    settings_row.windscribe_enabled = enabled
    db_session.flush()


def _patched_io():
    return (
        patch.object(
            privacy_score, "get_feed", AsyncMock(return_value=ThreatFeed(available=False))
        ),
        patch.object(privacy_score, "run_all_checks", AsyncMock(return_value=list(_CHECKS_ALL_OK))),
    )


@pytest.mark.asyncio
async def test_recompute_all_persists_device_scores_history_and_snapshot(db_session, factories):
    _set_windscribe(db_session, True)
    hardware = factories.hardware(role="server")
    _seed_scan_result(db_session, hardware.id, [23, 80])

    feed_patch, checks_patch = _patched_io()
    with feed_patch, checks_patch:
        snapshot = await privacy_score.recompute_all(db_session)

    assert snapshot is not None
    db_session.refresh(hardware)
    assert hardware.privacy_score == 85  # telnet −15
    assert hardware.threat_profile[0]["rule_id"] == "telnet_open"
    assert set(hardware.threat_profile[0]) == {
        "rule_id",
        "title",
        "points",
        "severity",
        "remediation_id",
        "hardware_id",
    }
    history = (
        db_session.query(PrivacyScoreHistory)
        .filter(PrivacyScoreHistory.hardware_id == hardware.id)
        .all()
    )
    assert len(history) == 1
    assert history[0].score == 85

    row = (
        db_session.query(NetworkPrivacySnapshot).order_by(NetworkPrivacySnapshot.id.desc()).first()
    )
    assert row is not None
    assert row.score == 85  # 100 − device aggregate 15
    assert row.grade == "B"
    assert any(d["rule_id"] == "telnet_open" for d in row.deductions)
    assert len(row.checks) == 3


@pytest.mark.asyncio
async def test_recompute_all_disabled_is_noop(db_session, factories):
    _set_windscribe(db_session, False)
    factories.hardware(role="server")

    feed_patch, checks_patch = _patched_io()
    with feed_patch, checks_patch:
        snapshot = await privacy_score.recompute_all(db_session)

    assert snapshot is None
    assert db_session.query(NetworkPrivacySnapshot).count() == 0


@pytest.mark.asyncio
async def test_recompute_all_uses_latest_matched_scan_result(db_session, factories):
    _set_windscribe(db_session, True)
    hardware = factories.hardware(role="server")
    _seed_scan_result(db_session, hardware.id, [23])  # older: telnet open
    _seed_scan_result(db_session, hardware.id, [443])  # newest: clean

    feed_patch, checks_patch = _patched_io()
    with feed_patch, checks_patch:
        await privacy_score.recompute_all(db_session)

    db_session.refresh(hardware)
    assert hardware.privacy_score == 100
    assert hardware.threat_profile == []


@pytest.mark.asyncio
async def test_periodic_job_respects_disabled_flag(db_session):
    _set_windscribe(db_session, False)
    feed_patch, checks_patch = _patched_io()
    with (
        feed_patch,
        checks_patch,
        patch.object(privacy_score, "_open_session", return_value=db_session),
    ):
        await privacy_score.run_privacy_periodic_job()
    assert db_session.query(NetworkPrivacySnapshot).count() == 0


@pytest.mark.asyncio
async def test_periodic_job_writes_snapshot_from_stored_profiles(db_session, factories):
    _set_windscribe(db_session, True)
    hardware = factories.hardware(role="server")
    hardware.threat_profile = [
        {
            "rule_id": "telnet_open",
            "title": "Telnet service exposed",
            "points": 15,
            "severity": "critical",
            "remediation_id": "disable_telnet",
            "hardware_id": hardware.id,
        }
    ]
    db_session.flush()

    feed_patch, checks_patch = _patched_io()
    with (
        feed_patch,
        checks_patch,
        patch.object(privacy_score, "_open_session", return_value=db_session),
    ):
        await privacy_score.run_privacy_periodic_job()

    row = db_session.query(NetworkPrivacySnapshot).first()
    assert row is not None
    assert row.score == 85
