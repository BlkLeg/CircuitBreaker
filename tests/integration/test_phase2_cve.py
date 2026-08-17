"""Phase 2 tests — CVE service, API endpoints, and migration.

Two product contracts shape the arrangement here:

* Once an admin account exists, every route outside the bootstrap/auth/settings-read
  allowlist answers 401 (cd1724ff). The CVE routes are not on that list, so the
  API tests bootstrap through ``auth_headers`` and send the Bearer/CSRF pair.
* The app lifespan materialises the ``AppSettings`` singleton (id=1) at startup via
  ``get_or_create_settings``, so by the time a test body runs behind ``client`` the
  row is already there. Tests that need particular CVE settings mutate that row
  instead of inserting a second id=1, which would violate ``pk_app_settings``.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.models import CVEEntry


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


def _set_cve_settings(db, **values):
    """Point the AppSettings singleton at the CVE config a test needs.

    The lifespan already created id=1, so ``db.add(AppSettings(id=1, ...))`` here
    would insert a rival singleton and blow up on ``pk_app_settings``. Fetch the
    row the app created and mutate it — that is also what the product's own
    settings writes do.
    """
    from app.services.settings_service import get_or_create_settings

    row = get_or_create_settings(db)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    return row


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


def test_cve_search_api(client, auth_headers, db):
    """GET /api/v1/cve/search should return results."""
    _seed_cves(db, 3)
    r = client.get(
        "/api/v1/cve/search", params={"vendor": "testvendor"}, headers=auth_headers
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


def test_cve_search_with_query(client, auth_headers, db):
    """GET /api/v1/cve/search?q= should filter by text."""
    _seed_cves(db, 5)
    r = client.get(
        "/api/v1/cve/search", params={"q": "CVE-2024-1002"}, headers=auth_headers
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert any(item["cve_id"] == "CVE-2024-1002" for item in data["items"])


def test_cve_search_by_severity(client, auth_headers, db):
    _seed_cves(db, 5)
    r = client.get(
        "/api/v1/cve/search", params={"severity": "high"}, headers=auth_headers
    )
    assert r.status_code == 200
    data = r.json()
    assert all(item["severity"] == "high" for item in data["items"])


def test_cve_entity_endpoint_no_match(client, auth_headers, db):
    """GET /api/v1/cve/entity/unknown_type/999 should return empty for unrecognised entity types."""
    r = client.get("/api/v1/cve/entity/unknown_type/999", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_cve_status_endpoint(client, auth_headers, db):
    """GET /api/v1/cve/status should return sync status."""
    _set_cve_settings(db, cve_sync_enabled=False, cve_sync_interval_hours=24)

    import app.db.session as _db_session
    import app.services.cve_service as _cve_svc

    orig = _cve_svc.SessionLocal
    _cve_svc.SessionLocal = _db_session.SessionLocal
    try:
        r = client.get("/api/v1/cve/status", headers=auth_headers)
    finally:
        _cve_svc.SessionLocal = orig
    assert r.status_code == 200
    data = r.json()
    assert "enabled" in data
    assert "total_entries" in data
    assert "last_sync_at" in data


def test_cve_sync_trigger(client, auth_headers, db):
    """POST /api/v1/cve/sync should accept the request."""
    with patch("app.api.cve.cve_service.sync_nvd_feed", return_value=0):
        r = client.post("/api/v1/cve/sync", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "sync_started"


def test_settings_include_cve_fields(client, auth_headers, db):
    """GET /api/v1/settings should return CVE settings."""
    _set_cve_settings(db, cve_sync_enabled=True, cve_sync_interval_hours=12)

    r = client.get("/api/v1/settings", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["cve_sync_enabled"] is True
    assert data["cve_sync_interval_hours"] == 12


def test_settings_update_cve_fields(client, auth_headers, db):
    """PUT /api/v1/settings should accept CVE fields."""
    # Start from the opposite of what the PUT asks for, so a no-op handler cannot
    # pass this by leaving the lifespan-seeded defaults in place.
    _set_cve_settings(db, cve_sync_enabled=False, cve_sync_interval_hours=24)

    r = client.put(
        "/api/v1/settings",
        json={
            "cve_sync_enabled": True,
            "cve_sync_interval_hours": 6,
        },
        headers=auth_headers,
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
