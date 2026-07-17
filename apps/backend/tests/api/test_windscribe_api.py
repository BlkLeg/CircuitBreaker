"""Contract tests for the privacy/threat endpoints — snapshot-served, never computed."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.models import AppSettings, NetworkPrivacySnapshot


def _set_windscribe(db_session, enabled: bool) -> None:
    settings_row = db_session.query(AppSettings).first()
    if settings_row is None:
        settings_row = AppSettings(id=1)
        db_session.add(settings_row)
    settings_row.windscribe_enabled = enabled
    db_session.flush()


def _seed_snapshot(
    db_session, *, score=72, grade="C", checks=None, deductions=None, created_at=None
):
    snapshot = NetworkPrivacySnapshot(
        score=score,
        grade=grade,
        deductions=deductions if deductions is not None else [],
        checks=checks if checks is not None else [],
    )
    if created_at is not None:
        snapshot.created_at = created_at
    db_session.add(snapshot)
    db_session.flush()
    return snapshot


def _deduction(severity: str) -> dict:
    return {
        "rule_id": "captive_portal",
        "title": "t",
        "points": 10,
        "severity": severity,
        "remediation_id": "captive_portal_info",
        "hardware_id": None,
        "category": "network",
    }


_WARNING_CHECK = {
    "check_id": "captive_portal",
    "status": "warning",
    "evidence": "generate_204 returned 302",
    "detected_at": "2026-07-15T00:00:00+00:00",
}
_CRITICAL_CHECK = {
    "check_id": "dns_tamper",
    "status": "critical",
    "evidence": "mismatch",
    "detected_at": "2026-07-15T00:00:00+00:00",
}
_OK_CHECK = {
    "check_id": "dns_tamper",
    "status": "ok",
    "evidence": "match",
    "detected_at": "2026-07-15T00:00:00+00:00",
}


# ── auth ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_privacy_endpoints_require_auth(client):
    for path in ("/api/v1/network/privacy-score", "/api/v1/network/threat-alerts"):
        resp = await client.get(path)
        assert resp.status_code == 401


# ── /network/privacy-score ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_privacy_score_disabled_returns_enabled_false(client, auth_headers, db_session):
    _set_windscribe(db_session, False)
    resp = await client.get("/api/v1/network/privacy-score", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["score"] is None
    assert body["history"] == []


@pytest.mark.asyncio
async def test_privacy_score_no_snapshot_is_empty_not_error(client, auth_headers, db_session):
    _set_windscribe(db_session, True)
    resp = await client.get("/api/v1/network/privacy-score", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["score"] is None
    assert body["deductions"] == []


@pytest.mark.asyncio
async def test_privacy_score_serves_latest_snapshot_with_history(client, auth_headers, db_session):
    _set_windscribe(db_session, True)
    _seed_snapshot(db_session, score=90, grade="A")
    deduction = {
        "rule_id": "telnet_open",
        "title": "Telnet service exposed",
        "points": 15,
        "severity": "critical",
        "remediation_id": "disable_telnet",
        "hardware_id": 1,
    }
    _seed_snapshot(db_session, score=72, grade="C", deductions=[deduction])

    resp = await client.get("/api/v1/network/privacy-score", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["score"] == 72
    assert body["grade"] == "C"
    assert body["deductions"] == [deduction]
    assert body["checks"] == []
    assert body["checked_at"]
    assert len(body["history"]) == 2
    assert {"score", "at"} == set(body["history"][0])


# ── /network/threat-alerts ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_threat_alerts_safe_when_checks_ok(client, auth_headers, db_session):
    _set_windscribe(db_session, True)
    _seed_snapshot(db_session, checks=[_OK_CHECK])
    resp = await client.get("/api/v1/network/threat-alerts", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "safe"
    assert body["alerts"] == []


@pytest.mark.asyncio
async def test_threat_alerts_critical_beats_warning(client, auth_headers, db_session):
    _set_windscribe(db_session, True)
    _seed_snapshot(db_session, checks=[_WARNING_CHECK, _CRITICAL_CHECK])
    resp = await client.get("/api/v1/network/threat-alerts", headers=auth_headers)
    body = resp.json()
    assert body["status"] == "critical"
    assert len(body["alerts"]) == 2
    alert = body["alerts"][0]
    assert {"check_id", "severity", "detail", "detected_at"} == set(alert)


@pytest.mark.asyncio
async def test_threat_alerts_disabled_or_missing_is_unknown(client, auth_headers, db_session):
    _set_windscribe(db_session, True)
    resp = await client.get("/api/v1/network/threat-alerts", headers=auth_headers)
    assert resp.json()["status"] == "unknown"

    _set_windscribe(db_session, False)
    resp = await client.get("/api/v1/network/threat-alerts", headers=auth_headers)
    body = resp.json()
    assert body["status"] == "unknown"
    assert body["enabled"] is False


# ── /devices/{id}/threat-profile ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_device_threat_profile_reads_stored_columns(
    client, auth_headers, db_session, factories
):
    hardware = factories.hardware(role="router")
    deduction = {
        "rule_id": "telnet_open",
        "title": "Telnet service exposed",
        "points": 23,
        "severity": "critical",
        "remediation_id": "disable_telnet",
        "hardware_id": hardware.id,
    }
    hardware.privacy_score = 77
    hardware.threat_profile = [deduction]
    db_session.flush()

    resp = await client.get(f"/api/v1/devices/{hardware.id}/threat-profile", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"hardware_id": hardware.id, "score": 77, "deductions": [deduction]}


@pytest.mark.asyncio
async def test_device_threat_profile_unscored_device_is_empty_not_error(
    client, auth_headers, factories
):
    hardware = factories.hardware()
    resp = await client.get(f"/api/v1/devices/{hardware.id}/threat-profile", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["score"] is None
    assert body["deductions"] == []


@pytest.mark.asyncio
async def test_device_threat_profile_missing_hardware_404(client, auth_headers):
    resp = await client.get("/api/v1/devices/999999/threat-profile", headers=auth_headers)
    assert resp.status_code == 404


# ── /network/privacy-score/history ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_privacy_score_history_requires_auth(client):
    resp = await client.get("/api/v1/network/privacy-score/history")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_privacy_score_history_empty_db_is_empty_not_error(client, auth_headers, db_session):
    _set_windscribe(db_session, True)
    resp = await client.get("/api/v1/network/privacy-score/history", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"days": []}


@pytest.mark.asyncio
async def test_privacy_score_history_disabled_is_empty(client, auth_headers, db_session):
    _set_windscribe(db_session, False)
    _seed_snapshot(db_session, score=90, grade="A")
    resp = await client.get("/api/v1/network/privacy-score/history", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"days": []}


@pytest.mark.asyncio
async def test_privacy_score_history_buckets_by_day_and_picks_latest(
    client, auth_headers, db_session
):
    _set_windscribe(db_session, True)
    day1 = datetime(2026, 7, 13, 9, 0, tzinfo=UTC)
    day1_later = datetime(2026, 7, 13, 21, 0, tzinfo=UTC)
    day2 = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)

    _seed_snapshot(db_session, score=80, grade="B", created_at=day1)
    _seed_snapshot(
        db_session,
        score=72,
        grade="C",
        created_at=day1_later,
        deductions=[_deduction("warning"), _deduction("info")],
    )
    _seed_snapshot(
        db_session, score=95, grade="A", created_at=day2, deductions=[_deduction("critical")]
    )

    resp = await client.get("/api/v1/network/privacy-score/history", headers=auth_headers)
    assert resp.status_code == 200
    days = resp.json()["days"]
    assert len(days) == 2

    by_date = {d["date"]: d for d in days}
    # day1's later (higher id) snapshot wins over the earlier one
    assert by_date["2026-07-13"]["score"] == 72
    assert by_date["2026-07-13"]["warning_count"] == 1
    assert by_date["2026-07-13"]["info_count"] == 1
    assert by_date["2026-07-13"]["critical_count"] == 0
    assert by_date["2026-07-14"]["score"] == 95
    assert by_date["2026-07-14"]["critical_count"] == 1


@pytest.mark.asyncio
async def test_privacy_score_history_days_param_clamped_to_90(client, auth_headers, db_session):
    _set_windscribe(db_session, True)
    old = datetime(2020, 1, 1, tzinfo=UTC)
    recent = datetime(2026, 7, 14, tzinfo=UTC)
    _seed_snapshot(db_session, score=50, grade="F", created_at=old)
    _seed_snapshot(db_session, score=90, grade="A", created_at=recent)

    resp = await client.get(
        "/api/v1/network/privacy-score/history?days=99999", headers=auth_headers
    )
    assert resp.status_code == 200
    days = resp.json()["days"]
    # clamped window (90 days back from the latest snapshot) excludes the 2020 row
    assert len(days) == 1
    assert days[0]["date"] == "2026-07-14"
