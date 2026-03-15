"""
Tests for Status Page endpoints:
  Pages: GET /api/v1/status/pages, POST /api/v1/status/pages, PATCH /api/v1/status/pages/{id}, DELETE /api/v1/status/pages/{id}
  Groups: GET /api/v1/status/pages/{id}/groups, POST /api/v1/status/groups, PATCH /api/v1/status/groups/{id}, DELETE /api/v1/status/groups/{id}
  History: GET /api/v1/status/history
  Dashboard: GET /api/v1/status/dashboard, GET /api/v1/status/dashboard/v2

All tests use real database operations, no mocks.
"""

import pytest
from sqlalchemy import select

from app.core.time import utcnow
from app.db.models import StatusGroup, StatusHistory, StatusPage

PAGES_URL = "/api/v1/status/pages"
GROUPS_URL = "/api/v1/status/groups"
HISTORY_URL = "/api/v1/status/history"
DASHBOARD_URL = "/api/v1/status/dashboard"
DASHBOARD_V2_URL = "/api/v1/status/dashboard/v2"


# ── StatusPage CRUD Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_pages_creates_default(client, auth_headers, db_session):
    """GET /status/pages auto-creates default page if none exist."""
    resp = await client.get(PAGES_URL, headers=auth_headers)
    assert resp.status_code == 200
    pages = resp.json()
    assert len(pages) >= 1

    # Verify default page exists in database
    default_page = db_session.execute(
        select(StatusPage).where(StatusPage.slug == "default")
    ).scalar_one_or_none()
    assert default_page is not None


@pytest.mark.asyncio
async def test_create_status_page(client, auth_headers, db_session):
    """POST /status/pages creates a new page."""
    payload = {
        "name": "Production Status",
        "slug": "production",
        "config": {"theme": "dark", "refresh_interval": 30},
    }
    resp = await client.post(PAGES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert body["name"] == "Production Status"
    assert body["slug"] == "production"
    assert body["config"]["theme"] == "dark"
    assert "id" in body

    # Verify in database
    page_in_db = db_session.get(StatusPage, body["id"])
    assert page_in_db is not None
    assert page_in_db.name == "Production Status"


@pytest.mark.asyncio
async def test_create_page_duplicate_slug_returns_409(client, auth_headers):
    """POST /status/pages with duplicate slug returns 409."""
    await client.post(PAGES_URL, json={"name": "Page 1", "slug": "duplicate"}, headers=auth_headers)
    resp = await client.post(
        PAGES_URL, json={"name": "Page 2", "slug": "duplicate"}, headers=auth_headers
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_get_page_by_id(client, auth_headers):
    """GET /status/pages/{id} returns specific page."""
    create_resp = await client.post(
        PAGES_URL, json={"name": "Test Page", "slug": "test-page"}, headers=auth_headers
    )
    page_id = create_resp.json()["id"]

    resp = await client.get(f"{PAGES_URL}/{page_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Test Page"


@pytest.mark.asyncio
async def test_get_page_404_for_missing(client, auth_headers):
    """GET /status/pages/{id} returns 404 for non-existent page."""
    resp = await client.get(f"{PAGES_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_status_page(client, auth_headers, db_session):
    """PATCH /status/pages/{id} updates page fields."""
    create_resp = await client.post(
        PAGES_URL, json={"name": "Old Name", "slug": "old-slug"}, headers=auth_headers
    )
    page_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"{PAGES_URL}/{page_id}",
        json={"name": "New Name", "config": {"banner": "Under Maintenance"}},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "New Name"
    assert update_resp.json()["config"]["banner"] == "Under Maintenance"

    # Verify in database
    page_in_db = db_session.get(StatusPage, page_id)
    assert page_in_db.name == "New Name"


@pytest.mark.asyncio
async def test_update_page_404_for_missing(client, auth_headers):
    """PATCH /status/pages/{id} returns 404 for non-existent page."""
    resp = await client.patch(f"{PAGES_URL}/99999", json={"name": "Test"}, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_status_page(client, auth_headers, db_session):
    """DELETE /status/pages/{id} removes page."""
    create_resp = await client.post(
        PAGES_URL, json={"name": "Temp Page", "slug": "temp"}, headers=auth_headers
    )
    page_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"{PAGES_URL}/{page_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Verify removed from database
    page_in_db = db_session.get(StatusPage, page_id)
    assert page_in_db is None


@pytest.mark.asyncio
async def test_delete_page_404_for_missing(client, auth_headers):
    """DELETE /status/pages/{id} returns 404 for non-existent page."""
    resp = await client.delete(f"{PAGES_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


# ── StatusGroup CRUD Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_groups_for_page_empty(client, auth_headers):
    """GET /status/pages/{id}/groups returns empty list for page with no groups."""
    create_resp = await client.post(
        PAGES_URL, json={"name": "Empty Page", "slug": "empty"}, headers=auth_headers
    )
    page_id = create_resp.json()["id"]

    resp = await client.get(f"{PAGES_URL}/{page_id}/groups", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_groups_404_for_missing_page(client, auth_headers):
    """GET /status/pages/{id}/groups returns 404 for non-existent page."""
    resp = await client.get(f"{PAGES_URL}/99999/groups", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_status_group(client, auth_headers, db_session, factories):
    """POST /status/groups creates a new group."""
    hw = factories.hardware(name="status-hw", ip_address="10.10.1.1")

    create_resp = await client.post(
        PAGES_URL, json={"name": "Group Test Page", "slug": "group-test"}, headers=auth_headers
    )
    page_id = create_resp.json()["id"]

    payload = {
        "page_id": page_id,
        "name": "Infrastructure",
        "entity_type": "hardware",
        "entity_id": hw.id,
    }
    resp = await client.post(GROUPS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert body["name"] == "Infrastructure"
    assert body["entity_type"] == "hardware"
    assert body["entity_id"] == hw.id
    assert "id" in body

    # Verify in database
    group_in_db = db_session.get(StatusGroup, body["id"])
    assert group_in_db is not None
    assert group_in_db.name == "Infrastructure"


@pytest.mark.asyncio
async def test_bulk_create_status_groups(client, auth_headers, db_session, factories):
    """POST /status/groups/bulk creates multiple groups."""
    hw1 = factories.hardware(name="bulk-hw-1", ip_address="10.11.1.1")
    hw2 = factories.hardware(name="bulk-hw-2", ip_address="10.11.1.2")

    create_resp = await client.post(
        PAGES_URL, json={"name": "Bulk Page", "slug": "bulk"}, headers=auth_headers
    )
    page_id = create_resp.json()["id"]

    payload = {
        "page_id": page_id,
        "groups": [
            {"name": "Group 1", "entity_type": "hardware", "entity_id": hw1.id},
            {"name": "Group 2", "entity_type": "hardware", "entity_id": hw2.id},
        ],
    }
    resp = await client.post(f"{GROUPS_URL}/bulk", json=payload, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert len(body["groups"]) == 2
    assert body["created"] == 2

    # Verify in database
    groups_in_db = (
        db_session.execute(select(StatusGroup).where(StatusGroup.page_id == page_id))
        .scalars()
        .all()
    )
    assert len(groups_in_db) == 2


@pytest.mark.asyncio
async def test_update_status_group(client, auth_headers, db_session, factories):
    """PATCH /status/groups/{id} updates group fields."""
    hw = factories.hardware(name="update-hw", ip_address="10.12.1.1")

    create_page_resp = await client.post(
        PAGES_URL, json={"name": "Update Page", "slug": "update"}, headers=auth_headers
    )
    page_id = create_page_resp.json()["id"]

    create_group_resp = await client.post(
        GROUPS_URL,
        json={
            "page_id": page_id,
            "name": "Old Group",
            "entity_type": "hardware",
            "entity_id": hw.id,
        },
        headers=auth_headers,
    )
    group_id = create_group_resp.json()["id"]

    update_resp = await client.patch(
        f"{GROUPS_URL}/{group_id}",
        json={"name": "Updated Group", "display_order": 5},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Updated Group"

    # Verify in database
    group_in_db = db_session.get(StatusGroup, group_id)
    assert group_in_db.name == "Updated Group"
    assert group_in_db.display_order == 5


@pytest.mark.asyncio
async def test_update_group_404_for_missing(client, auth_headers):
    """PATCH /status/groups/{id} returns 404 for non-existent group."""
    resp = await client.patch(f"{GROUPS_URL}/99999", json={"name": "Test"}, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_status_group(client, auth_headers, db_session, factories):
    """DELETE /status/groups/{id} removes group."""
    hw = factories.hardware(name="delete-hw", ip_address="10.13.1.1")

    create_page_resp = await client.post(
        PAGES_URL, json={"name": "Delete Page", "slug": "delete"}, headers=auth_headers
    )
    page_id = create_page_resp.json()["id"]

    create_group_resp = await client.post(
        GROUPS_URL,
        json={
            "page_id": page_id,
            "name": "Temp Group",
            "entity_type": "hardware",
            "entity_id": hw.id,
        },
        headers=auth_headers,
    )
    group_id = create_group_resp.json()["id"]

    delete_resp = await client.delete(f"{GROUPS_URL}/{group_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Verify removed from database
    group_in_db = db_session.get(StatusGroup, group_id)
    assert group_in_db is None


@pytest.mark.asyncio
async def test_delete_group_404_for_missing(client, auth_headers):
    """DELETE /status/groups/{id} returns 404 for non-existent group."""
    resp = await client.delete(f"{GROUPS_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


# ── StatusHistory Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_status_history_empty(client, auth_headers):
    """GET /status/history returns empty list when no history exists."""
    resp = await client.get(HISTORY_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_status_history_with_data(client, auth_headers, db_session, factories):
    """GET /status/history returns StatusHistory entries."""
    hw = factories.hardware(name="history-hw", ip_address="10.14.1.1")

    # Create a status history entry manually
    history = StatusHistory(
        entity_type="hardware",
        entity_id=hw.id,
        status="up",
        check_method="icmp",
        checked_at=utcnow(),
    )
    db_session.add(history)
    db_session.commit()

    resp = await client.get(HISTORY_URL, headers=auth_headers)
    assert resp.status_code == 200

    entries = resp.json()
    assert len(entries) >= 1
    hw_entries = [e for e in entries if e["entity_id"] == hw.id]
    assert len(hw_entries) >= 1
    assert hw_entries[0]["status"] == "up"


@pytest.mark.asyncio
async def test_filter_status_history_by_entity(client, auth_headers, factories, db_session):
    """GET /status/history?entity_type=hardware&entity_id={id} filters correctly."""
    hw1 = factories.hardware(name="filter-hw-1", ip_address="10.15.1.1")
    hw2 = factories.hardware(name="filter-hw-2", ip_address="10.15.1.2")

    db_session.add(
        StatusHistory(entity_type="hardware", entity_id=hw1.id, status="up", checked_at=utcnow())
    )
    db_session.add(
        StatusHistory(entity_type="hardware", entity_id=hw2.id, status="down", checked_at=utcnow())
    )
    db_session.commit()

    resp = await client.get(
        f"{HISTORY_URL}?entity_type=hardware&entity_id={hw1.id}", headers=auth_headers
    )
    assert resp.status_code == 200

    entries = resp.json()
    assert all(e["entity_id"] == hw1.id for e in entries)


# ── Dashboard Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_dashboard_returns_summary(client, auth_headers, factories):
    """GET /status/dashboard returns global summary."""
    # Create some test entities
    factories.hardware(name="dashboard-hw", ip_address="10.16.1.1")
    factories.service(name="dashboard-svc", ip_address="10.16.1.2")

    resp = await client.get(DASHBOARD_URL, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert "global_summary" in body
    assert "groups" in body
    assert isinstance(body["global_summary"], dict)


@pytest.mark.asyncio
async def test_get_dashboard_v2_returns_data(client, auth_headers):
    """GET /status/dashboard/v2 returns enhanced dashboard."""
    resp = await client.get(DASHBOARD_V2_URL, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert "pages" in body
    assert isinstance(body["pages"], list)


# ── StatusGroup Entity Association Tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_create_group_with_service(client, auth_headers, factories):
    """POST /status/groups can associate with service entity."""
    svc = factories.service(name="web-service", ip_address="10.17.1.1")

    create_page_resp = await client.post(
        PAGES_URL, json={"name": "Service Page", "slug": "services"}, headers=auth_headers
    )
    page_id = create_page_resp.json()["id"]

    payload = {
        "page_id": page_id,
        "name": "Web Services",
        "entity_type": "service",
        "entity_id": svc.id,
    }
    resp = await client.post(GROUPS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["entity_type"] == "service"


@pytest.mark.asyncio
async def test_create_group_with_invalid_entity_type_returns_422(client, auth_headers):
    """POST /status/groups with invalid entity_type returns 422."""
    create_page_resp = await client.post(
        PAGES_URL, json={"name": "Test Page", "slug": "test"}, headers=auth_headers
    )
    page_id = create_page_resp.json()["id"]

    payload = {
        "page_id": page_id,
        "name": "Bad Group",
        "entity_type": "invalid_type",
        "entity_id": 1,
    }
    resp = await client.post(GROUPS_URL, json=payload, headers=auth_headers)
    assert resp.status_code in (422, 400)


# ── Status Refresh Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_status_endpoint(client, auth_headers):
    """POST /status/refresh triggers status refresh."""
    resp = await client.post(
        f"{DASHBOARD_URL.replace('/dashboard', '/refresh')}", headers=auth_headers
    )
    assert resp.status_code in (200, 202, 204)


# ── Available Entities Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_available_entities(client, auth_headers, factories):
    """GET /status/available-entities returns hardware/services for status tracking."""
    factories.hardware(name="available-hw", ip_address="10.18.1.1")
    factories.service(name="available-svc", ip_address="10.18.1.2")

    resp = await client.get(
        f"{DASHBOARD_URL.replace('/dashboard', '/available-entities')}", headers=auth_headers
    )
    assert resp.status_code == 200

    body = resp.json()
    assert "hardware" in body
    assert "services" in body


# ── Error Handling Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_page_missing_required_field_returns_422(client, auth_headers):
    """POST /status/pages without required 'name' field returns 422."""
    resp = await client.post(PAGES_URL, json={"slug": "test"}, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_group_invalid_page_id_returns_error(client, auth_headers, factories):
    """POST /status/groups with non-existent page_id returns error."""
    hw = factories.hardware(name="err-hw", ip_address="10.19.1.1")

    payload = {
        "page_id": 99999,
        "name": "Bad Group",
        "entity_type": "hardware",
        "entity_id": hw.id,
    }
    resp = await client.post(GROUPS_URL, json=payload, headers=auth_headers)
    assert resp.status_code in (404, 400, 422)


@pytest.mark.asyncio
async def test_dashboard_handles_missing_groups_gracefully(client, auth_headers):
    """GET /status/dashboard returns valid response even with no groups."""
    resp = await client.get(DASHBOARD_URL, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "global_summary" in body
    assert "groups" in body
    assert isinstance(body["groups"], list)
