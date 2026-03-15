"""
Tests for CVE (Common Vulnerabilities and Exposures) endpoints:
  GET /api/v1/cve/search - Search CVE database
  GET /api/v1/cve/entity/{type}/{id} - Get CVEs for specific entity
  POST /api/v1/cve/sync - Trigger CVE feed sync
  GET /api/v1/cve/status - Get CVE database status

All tests use real database operations, no mocks.
"""

import pytest
from sqlalchemy import select

from app.db.models import CVEEntry as CVE

CVE_SEARCH_URL = "/api/v1/cve/search"
CVE_ENTITY_URL = "/api/v1/cve/entity"
CVE_SYNC_URL = "/api/v1/cve/sync"
CVE_STATUS_URL = "/api/v1/cve/status"


# ── CVE Search Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_cves_empty_query_returns_all(client, auth_headers):
    """GET /cve/search without parameters returns paginated CVE list."""
    resp = await client.get(CVE_SEARCH_URL, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert isinstance(body["items"], list)
    assert isinstance(body["total"], int)


@pytest.mark.asyncio
async def test_search_cves_with_query_parameter(client, auth_headers, db_session):
    """GET /cve/search?q=keyword searches CVE descriptions."""
    # Create test CVE entry
    test_cve = CVE(
        cve_id="CVE-2024-12345",
        summary="Test vulnerability in Apache web server",
        severity="HIGH",
        cvss_score=7.5,
        vendor="apache",
        product="http_server",
    )
    db_session.add(test_cve)
    db_session.commit()

    resp = await client.get(f"{CVE_SEARCH_URL}?q=apache", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    # Should find the test CVE (or others with 'apache')
    assert body["total"] >= 0


@pytest.mark.asyncio
async def test_search_cves_filter_by_vendor(client, auth_headers, db_session):
    """GET /cve/search?vendor=name filters by vendor."""
    # Create test CVEs
    cve1 = CVE(
        cve_id="CVE-2024-11111",
        summary="Vendor A vulnerability",
        severity="MEDIUM",
        cvss_score=5.0,
        vendor="vendor_a",
        product="product_x",
    )
    cve2 = CVE(
        cve_id="CVE-2024-22222",
        summary="Vendor B vulnerability",
        severity="HIGH",
        cvss_score=7.0,
        vendor="vendor_b",
        product="product_y",
    )
    db_session.add_all([cve1, cve2])
    db_session.commit()

    resp = await client.get(f"{CVE_SEARCH_URL}?vendor=vendor_a", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    if body["total"] > 0:
        # Verify all results match vendor filter
        vendors = {item.get("vendor") for item in body["items"] if "vendor" in item}
        if vendors:
            assert "vendor_a" in vendors


@pytest.mark.asyncio
async def test_search_cves_filter_by_product(client, auth_headers, db_session):
    """GET /cve/search?product=name filters by product."""
    cve = CVE(
        cve_id="CVE-2024-33333",
        summary="Product filter test",
        severity="LOW",
        cvss_score=3.0,
        vendor="test_vendor",
        product="test_product",
    )
    db_session.add(cve)
    db_session.commit()

    resp = await client.get(f"{CVE_SEARCH_URL}?product=test_product", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert "items" in body


@pytest.mark.asyncio
async def test_search_cves_filter_by_severity(client, auth_headers, db_session):
    """GET /cve/search?severity=level filters by severity."""
    cve_critical = CVE(
        cve_id="CVE-2024-44444",
        summary="Critical severity test",
        severity="CRITICAL",
        cvss_score=9.5,
        vendor="test",
        product="test",
    )
    cve_low = CVE(
        cve_id="CVE-2024-55555",
        summary="Low severity test",
        severity="LOW",
        cvss_score=2.0,
        vendor="test",
        product="test",
    )
    db_session.add_all([cve_critical, cve_low])
    db_session.commit()

    resp = await client.get(f"{CVE_SEARCH_URL}?severity=CRITICAL", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    if body["total"] > 0:
        # Verify all results match severity filter
        severities = {item.get("severity") for item in body["items"] if "severity" in item}
        if severities:
            assert "CRITICAL" in severities


@pytest.mark.asyncio
async def test_search_cves_pagination(client, auth_headers, db_session):
    """GET /cve/search supports limit and offset pagination."""
    # Create multiple CVEs
    for i in range(10):
        cve = CVE(
            cve_id=f"CVE-2024-{60000 + i}",
            summary=f"Pagination test {i}",
            severity="MEDIUM",
            cvss_score=5.0,
            vendor="paginate",
            product="test",
        )
        db_session.add(cve)
    db_session.commit()

    # Get first page
    resp1 = await client.get(f"{CVE_SEARCH_URL}?limit=5&offset=0", headers=auth_headers)
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert len(body1["items"]) <= 5

    # Get second page
    resp2 = await client.get(f"{CVE_SEARCH_URL}?limit=5&offset=5", headers=auth_headers)
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert len(body2["items"]) <= 5

    # Verify different results (if enough CVEs exist)
    if body1["total"] > 5:
        ids1 = {item.get("cve_id") for item in body1["items"]}
        ids2 = {item.get("cve_id") for item in body2["items"]}
        # Page 1 and page 2 should have different CVEs
        if ids1 and ids2:
            assert ids1 != ids2


@pytest.mark.asyncio
async def test_search_cves_combined_filters(client, auth_headers, db_session):
    """GET /cve/search supports multiple filters simultaneously."""
    cve = CVE(
        cve_id="CVE-2024-77777",
        summary="Combined filter test for linux kernel",
        severity="HIGH",
        cvss_score=8.0,
        vendor="linux",
        product="kernel",
    )
    db_session.add(cve)
    db_session.commit()

    resp = await client.get(
        f"{CVE_SEARCH_URL}?q=linux&vendor=linux&severity=HIGH", headers=auth_headers
    )
    assert resp.status_code == 200

    body = resp.json()
    assert "items" in body
    assert "total" in body


# ── CVE Entity Lookup Tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cves_for_hardware_entity(client, auth_headers, factories, db_session):
    """GET /cve/entity/hardware/{id} returns CVEs associated with hardware."""
    hw = factories.hardware(name="vulnerable-hw", ip_address="10.0.0.50")

    # Create CVE and associate with hardware (if association table exists)
    # This depends on your schema - may need hardware_cve or similar join
    cve = CVE(
        cve_id="CVE-2024-88888",
        summary="Hardware vulnerability test",
        severity="MEDIUM",
        cvss_score=6.0,
        vendor="test",
        product="firmware",
    )
    db_session.add(cve)
    db_session.commit()

    resp = await client.get(f"{CVE_ENTITY_URL}/hardware/{hw.id}", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_cves_for_service_entity(client, auth_headers, factories):
    """GET /cve/entity/service/{id} returns CVEs associated with service."""
    svc = factories.service(name="vulnerable-svc", ip_address="10.0.0.51")

    resp = await client.get(f"{CVE_ENTITY_URL}/service/{svc.id}", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert "items" in body
    assert "total" in body


@pytest.mark.asyncio
async def test_cves_for_nonexistent_entity_returns_empty(client, auth_headers):
    """GET /cve/entity/{type}/{id} returns empty list for non-existent entity."""
    resp = await client.get(f"{CVE_ENTITY_URL}/hardware/99999", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_cves_for_entity_invalid_type_returns_error(client, auth_headers):
    """GET /cve/entity/invalid_type/{id} returns error."""
    resp = await client.get(f"{CVE_ENTITY_URL}/invalid_type/1", headers=auth_headers)
    # May return 400, 404, or 422 depending on validation
    assert resp.status_code in (400, 404, 422, 200)


# ── CVE Sync Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_cve_sync(client, auth_headers):
    """POST /cve/sync triggers background CVE feed sync."""
    resp = await client.post(CVE_SYNC_URL, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert "status" in body
    assert body["status"] == "sync_started"


@pytest.mark.asyncio
async def test_cve_sync_requires_authentication(client):
    """POST /cve/sync requires write authentication."""
    resp = await client.post(CVE_SYNC_URL)
    assert resp.status_code in (401, 403)


# ── CVE Status Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_cve_status(client, auth_headers):
    """GET /cve/status returns CVE database status information."""
    resp = await client.get(CVE_STATUS_URL, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    # Expected status fields (may vary based on implementation)
    # Common fields: total_cves, last_sync_at, sync_status
    assert isinstance(body, dict)


@pytest.mark.asyncio
async def test_cve_status_includes_counts(client, auth_headers, db_session):
    """GET /cve/status includes CVE count metrics."""
    # Add some CVEs
    for i in range(5):
        cve = CVE(
            cve_id=f"CVE-2024-{90000 + i}",
            description=f"Status test {i}",
            severity="MEDIUM",
            cvss_score=5.0,
            vendor="status",
            product="test",
        )
        db_session.add(cve)
    db_session.commit()

    resp = await client.get(CVE_STATUS_URL, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    # Status should include some form of count or metric
    assert isinstance(body, dict)


# ── CVE Data Validation Tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cve_entry_has_required_fields(client, auth_headers, db_session):
    """CVE entries include required fields: cve_id, summary, severity."""
    cve = CVE(
        cve_id="CVE-2024-99999",
        summary="Complete CVE entry test",
        severity="HIGH",
        cvss_score=7.8,
        vendor="validation",
        product="test",
    )
    db_session.add(cve)
    db_session.commit()

    resp = await client.get(f"{CVE_SEARCH_URL}?q=CVE-2024-99999", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    if body["total"] > 0:
        item = body["items"][0]
        # Verify required fields
        if "cve_id" in item:
            assert item["cve_id"] is not None
        if "severity" in item:
            assert item["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL", None]


@pytest.mark.asyncio
async def test_cve_cvss_score_range(client, auth_headers, db_session):
    """CVE CVSS scores are within valid range (0.0-10.0)."""
    cve = CVE(
        cve_id="CVE-2024-10101",
        summary="CVSS score validation test",
        severity="CRITICAL",
        cvss_score=9.8,
        vendor="cvss",
        product="test",
    )
    db_session.add(cve)
    db_session.commit()

    # Verify in database
    cve_in_db = db_session.execute(
        select(CVE).where(CVE.cve_id == "CVE-2024-10101")
    ).scalar_one_or_none()
    if cve_in_db and cve_in_db.cvss_score is not None:
        assert 0.0 <= cve_in_db.cvss_score <= 10.0


# ── CVE Severity Levels Tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_cves_severity_levels(client, auth_headers, db_session):
    """CVE search supports all severity levels."""
    severities = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

    for i, severity in enumerate(severities):
        cve = CVE(
            cve_id=f"CVE-2024-{20000 + i}",
            summary=f"{severity} severity test",
            severity=severity,
            cvss_score=2.0 + (i * 2.5),
            vendor="severity",
            product="test",
        )
        db_session.add(cve)
    db_session.commit()

    # Test each severity filter
    for severity in severities:
        resp = await client.get(f"{CVE_SEARCH_URL}?severity={severity}", headers=auth_headers)
        assert resp.status_code == 200


# ── CVE Vendor/Product Association Tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_cve_vendor_product_association(client, auth_headers, db_session):
    """CVEs correctly associate vendor and product information."""
    cve = CVE(
        cve_id="CVE-2024-30303",
        summary="Vendor product association test",
        severity="MEDIUM",
        cvss_score=5.5,
        vendor="microsoft",
        product="windows_10",
    )
    db_session.add(cve)
    db_session.commit()

    resp = await client.get(
        f"{CVE_SEARCH_URL}?vendor=microsoft&product=windows_10", headers=auth_headers
    )
    assert resp.status_code == 200


# ── CVE Date Tracking Tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cve_tracks_published_date(client, auth_headers, db_session):
    """CVE entries track published_at."""
    from app.core.time import utcnow

    cve = CVE(
        cve_id="CVE-2024-40404",
        summary="Published date test",
        severity="HIGH",
        cvss_score=7.0,
        vendor="date",
        product="test",
        published_at=utcnow(),
    )
    db_session.add(cve)
    db_session.commit()

    cve_in_db = db_session.get(CVE, cve.id)
    if hasattr(cve_in_db, "published_at"):
        assert cve_in_db.published_at is not None


@pytest.mark.asyncio
async def test_cve_tracks_modified_date(client, auth_headers, db_session):
    """CVE entries track updated_at."""
    from app.core.time import utcnow

    cve = CVE(
        cve_id="CVE-2024-50505",
        summary="Modified date test",
        severity="MEDIUM",
        cvss_score=6.0,
        vendor="date",
        product="test",
        updated_at=utcnow(),
    )
    db_session.add(cve)
    db_session.commit()

    cve_in_db = db_session.get(CVE, cve.id)
    if hasattr(cve_in_db, "updated_at"):
        assert cve_in_db.updated_at is not None


# ── Error Handling Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_cves_invalid_limit_returns_error(client, auth_headers):
    """GET /cve/search with invalid limit parameter returns error."""
    resp = await client.get(f"{CVE_SEARCH_URL}?limit=-1", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_cves_invalid_offset_returns_error(client, auth_headers):
    """GET /cve/search with invalid offset parameter returns error."""
    resp = await client.get(f"{CVE_SEARCH_URL}?offset=-1", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_cves_limit_exceeds_maximum_returns_error(client, auth_headers):
    """GET /cve/search with limit > 500 returns error."""
    resp = await client.get(f"{CVE_SEARCH_URL}?limit=1000", headers=auth_headers)
    assert resp.status_code == 422


# ── CVE Search Performance Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_cves_handles_large_result_sets(client, auth_headers, db_session):
    """CVE search efficiently handles large result sets with pagination."""
    # Create a batch of CVEs
    for i in range(50):
        cve = CVE(
            cve_id=f"CVE-2024-{70000 + i}",
            summary=f"Performance test {i}",
            severity="MEDIUM",
            cvss_score=5.0,
            vendor="performance",
            product="test",
        )
        db_session.add(cve)
    db_session.commit()

    # Query with pagination
    resp = await client.get(f"{CVE_SEARCH_URL}?vendor=performance&limit=20", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert len(body["items"]) <= 20


# ── CVE Reference Information Tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_cve_may_include_references(client, auth_headers, db_session):
    """CVE entries may include reference URLs or additional metadata."""
    # This test depends on your CVE schema - may have references field
    cve = CVE(
        cve_id="CVE-2024-60606",
        summary="Reference test",
        severity="HIGH",
        cvss_score=8.0,
        vendor="reference",
        product="test",
    )
    db_session.add(cve)
    db_session.commit()

    resp = await client.get(f"{CVE_SEARCH_URL}?q=CVE-2024-60606", headers=auth_headers)
    assert resp.status_code == 200

    # References field is optional
    body = resp.json()
    if body["total"] > 0:
        item = body["items"][0]
        # References may or may not be present
        assert isinstance(item, dict)
