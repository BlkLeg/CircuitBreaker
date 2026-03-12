"""Phase 2 tests — CVE service, API endpoints, and migration."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.models import AppSettings, CVEEntry


@pytest.fixture(autouse=True)
def _patch_cve_session(db_engine, db):
    """Redirect CVESessionLocal to use the test in-memory DB for all CVE tests."""
    import app.db.cve_session as _cve_mod
    import app.services.cve_service as _cve_svc

    test_session = sessionmaker(bind=db_engine)
    orig_cve = _cve_mod.CVESessionLocal
    orig_svc = _cve_svc.CVESessionLocal

    _cve_mod.CVESessionLocal = test_session
    _cve_svc.CVESessionLocal = test_session
    yield
    _cve_mod.CVESessionLocal = orig_cve
    _cve_svc.CVESessionLocal = orig_svc


def _seed_cves(db, count=5):
    for i in range(count):
        db.add(
            CVEEntry(
                cve_id=f"CVE-2024-{1000 + i}",
                vendor="testvendor",
                product="testproduct",
                version_start="1.0",
                version_end="2.0",
                severity=["low", "medium", "high", "critical", "medium"][i % 5],
                cvss_score=3.0 + i * 1.5,
                summary=f"Test vulnerability {i}",
                published_at=datetime(2024, 1, 1, tzinfo=UTC),
            )
        )
    db.commit()


def test_cve_model_in_test_db(db):
    """CVEEntry table should be created in the test DB."""
    db.add(
        CVEEntry(
            cve_id="CVE-2024-9999",
            vendor="acme",
            product="widget",
            severity="high",
            cvss_score=8.1,
            summary="Test vulnerability",
        )
    )
    db.commit()
    result = db.query(CVEEntry).filter_by(cve_id="CVE-2024-9999").first()
    assert result is not None
    assert result.vendor == "acme"
    assert result.cvss_score == 8.1


def test_cve_search_api(client, db):
    """GET /api/v1/cve/search should return results."""
    _seed_cves(db, 3)
    r = client.get("/api/v1/cve/search", params={"vendor": "testvendor"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


def test_cve_search_with_query(client, db):
    """GET /api/v1/cve/search?q= should filter by text."""
    _seed_cves(db, 5)
    r = client.get("/api/v1/cve/search", params={"q": "CVE-2024-1002"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert any(item["cve_id"] == "CVE-2024-1002" for item in data["items"])


def test_cve_search_by_severity(client, db):
    _seed_cves(db, 5)
    r = client.get("/api/v1/cve/search", params={"severity": "high"})
    assert r.status_code == 200
    data = r.json()
    assert all(item["severity"] == "high" for item in data["items"])


def test_cve_entity_endpoint_no_match(client, db):
    """GET /api/v1/cve/entity/unknown_type/999 should return empty for unrecognised entity types."""
    r = client.get("/api/v1/cve/entity/unknown_type/999")
    assert r.status_code == 200
    data = r.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_cve_status_endpoint(client, db):
    """GET /api/v1/cve/status should return sync status."""
    db.add(AppSettings(id=1, cve_sync_enabled=False, cve_sync_interval_hours=24))
    db.commit()

    import app.db.session as _db_session
    import app.services.cve_service as _cve_svc

    orig = _cve_svc.SessionLocal
    _cve_svc.SessionLocal = _db_session.SessionLocal
    try:
        r = client.get("/api/v1/cve/status")
    finally:
        _cve_svc.SessionLocal = orig
    assert r.status_code == 200
    data = r.json()
    assert "enabled" in data
    assert "total_entries" in data
    assert "last_sync_at" in data


def test_cve_sync_trigger(client, db):
    """POST /api/v1/cve/sync should accept the request."""
    with patch("app.api.cve.cve_service.sync_nvd_feed", return_value=0):
        r = client.post("/api/v1/cve/sync")
    assert r.status_code == 200
    assert r.json()["status"] == "sync_started"


def test_settings_include_cve_fields(client, db):
    """GET /api/v1/settings should return CVE settings."""
    db.add(AppSettings(id=1, cve_sync_enabled=True, cve_sync_interval_hours=12))
    db.commit()

    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["cve_sync_enabled"] is True
    assert data["cve_sync_interval_hours"] == 12


def test_settings_update_cve_fields(client, db):
    """PUT /api/v1/settings should accept CVE fields."""
    db.add(AppSettings(id=1))
    db.commit()

    r = client.put(
        "/api/v1/settings",
        json={
            "cve_sync_enabled": True,
            "cve_sync_interval_hours": 6,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["cve_sync_enabled"] is True
    assert data["cve_sync_interval_hours"] == 6


def test_migration_creates_cve_settings_columns(db_engine):
    """The cve_sync_enabled and cve_sync_interval_hours columns should exist."""
    from sqlalchemy import inspect

    inspector = inspect(db_engine)
    columns = {col["name"] for col in inspector.get_columns("app_settings")}
    assert "cve_sync_enabled" in columns
    assert "cve_sync_interval_hours" in columns
    assert "cve_last_sync_at" in columns


def test_migration_creates_cve_entries_table(db_engine):
    """The cve_entries table should be created."""
    from sqlalchemy import inspect

    inspector = inspect(db_engine)
    tables = inspector.get_table_names()
    assert "cve_entries" in tables
