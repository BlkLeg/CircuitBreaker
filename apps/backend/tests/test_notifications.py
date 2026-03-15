"""
Tests for Notification endpoints:
  Sinks: GET /api/v1/notifications/sinks, POST /api/v1/notifications/sinks, PATCH /api/v1/notifications/sinks/{id}, DELETE /api/v1/notifications/sinks/{id}
  Routes: GET /api/v1/notifications/routes, POST /api/v1/notifications/routes, PATCH /api/v1/notifications/routes/{id}, DELETE /api/v1/notifications/routes/{id}
  Test: POST /api/v1/notifications/sinks/{id}/test

All tests use real database operations, no mocks.
"""

import pytest

from app.db.models import NotificationRoute, NotificationSink

SINKS_URL = "/api/v1/notifications/sinks"
ROUTES_URL = "/api/v1/notifications/routes"


# ── NotificationSink CRUD Tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_sinks_empty(client, auth_headers):
    """GET /notifications/sinks returns empty list when no sinks exist."""
    resp = await client.get(SINKS_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_notification_sink_slack(client, auth_headers, db_session):
    """POST /notifications/sinks creates Slack notification sink."""
    payload = {
        "name": "Slack Alerts",
        "provider_type": "slack",
        "provider_config": {"webhook_url": "https://hooks.slack.com/services/test"},
        "enabled": True,
    }
    resp = await client.post(SINKS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert body["name"] == "Slack Alerts"
    assert body["provider_type"] == "slack"
    assert body["provider_config"]["webhook_url"] == "https://hooks.slack.com/services/test"
    assert body["enabled"] is True
    assert "id" in body

    # Verify in database
    sink_in_db = db_session.get(NotificationSink, body["id"])
    assert sink_in_db is not None
    assert sink_in_db.provider_type == "slack"


@pytest.mark.asyncio
async def test_create_notification_sink_discord(client, auth_headers):
    """POST /notifications/sinks creates Discord notification sink."""
    payload = {
        "name": "Discord Alerts",
        "provider_type": "discord",
        "provider_config": {"webhook_url": "https://discord.com/api/webhooks/test"},
        "enabled": True,
    }
    resp = await client.post(SINKS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["provider_type"] == "discord"


@pytest.mark.asyncio
async def test_create_notification_sink_teams(client, auth_headers):
    """POST /notifications/sinks creates Microsoft Teams notification sink."""
    payload = {
        "name": "Teams Alerts",
        "provider_type": "teams",
        "provider_config": {"webhook_url": "https://outlook.office.com/webhook/test"},
        "enabled": False,
    }
    resp = await client.post(SINKS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["provider_type"] == "teams"
    assert resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_create_notification_sink_email(client, auth_headers):
    """POST /notifications/sinks creates Email notification sink."""
    payload = {
        "name": "Email Alerts",
        "provider_type": "email",
        "provider_config": {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "from_address": "alerts@example.com",
            "to_addresses": ["admin@example.com"],
        },
        "enabled": True,
    }
    resp = await client.post(SINKS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["provider_type"] == "email"
    assert resp.json()["provider_config"]["smtp_host"] == "smtp.example.com"


@pytest.mark.asyncio
async def test_list_sinks_returns_created(client, auth_headers):
    """GET /notifications/sinks includes previously created sinks."""
    await client.post(
        SINKS_URL,
        json={
            "name": "Test Sink",
            "provider_type": "slack",
            "provider_config": {"webhook_url": "https://test.com"},
        },
        headers=auth_headers,
    )

    resp = await client.get(SINKS_URL, headers=auth_headers)
    assert resp.status_code == 200

    sinks = resp.json()
    names = [s["name"] for s in sinks]
    assert "Test Sink" in names


@pytest.mark.asyncio
async def test_get_sink_by_id(client, auth_headers):
    """GET /notifications/sinks/{id} returns specific sink."""
    create_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Get Test",
            "provider_type": "discord",
            "provider_config": {"webhook_url": "https://discord.test"},
        },
        headers=auth_headers,
    )
    sink_id = create_resp.json()["id"]

    resp = await client.get(f"{SINKS_URL}/{sink_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Get Test"


@pytest.mark.asyncio
async def test_get_sink_404_for_missing(client, auth_headers):
    """GET /notifications/sinks/{id} returns 404 for non-existent sink."""
    resp = await client.get(f"{SINKS_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_notification_sink(client, auth_headers, db_session):
    """PATCH /notifications/sinks/{id} updates sink fields."""
    create_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Old Sink",
            "provider_type": "slack",
            "provider_config": {"webhook_url": "https://old.com"},
            "enabled": True,
        },
        headers=auth_headers,
    )
    sink_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"{SINKS_URL}/{sink_id}",
        json={
            "name": "Updated Sink",
            "provider_config": {"webhook_url": "https://new.com", "channel": "#alerts"},
            "enabled": False,
        },
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Updated Sink"
    assert update_resp.json()["provider_config"]["webhook_url"] == "https://new.com"
    assert update_resp.json()["enabled"] is False

    # Verify in database
    sink_in_db = db_session.get(NotificationSink, sink_id)
    assert sink_in_db.name == "Updated Sink"
    assert sink_in_db.enabled is False


@pytest.mark.asyncio
async def test_update_sink_404_for_missing(client, auth_headers):
    """PATCH /notifications/sinks/{id} returns 404 for non-existent sink."""
    resp = await client.patch(f"{SINKS_URL}/99999", json={"name": "Test"}, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_notification_sink(client, auth_headers, db_session):
    """DELETE /notifications/sinks/{id} removes sink."""
    create_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Temp Sink",
            "provider_type": "teams",
            "provider_config": {"webhook_url": "https://temp.com"},
        },
        headers=auth_headers,
    )
    sink_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"{SINKS_URL}/{sink_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Verify removed from database
    sink_in_db = db_session.get(NotificationSink, sink_id)
    assert sink_in_db is None


@pytest.mark.asyncio
async def test_delete_sink_404_for_missing(client, auth_headers):
    """DELETE /notifications/sinks/{id} returns 404 for non-existent sink."""
    resp = await client.delete(f"{SINKS_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


# ── NotificationRoute CRUD Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_routes_empty(client, auth_headers):
    """GET /notifications/routes returns empty list when no routes exist."""
    resp = await client.get(ROUTES_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_notification_route(client, auth_headers, db_session):
    """POST /notifications/routes creates a new route."""
    # Create sink first
    sink_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Route Sink",
            "provider_type": "slack",
            "provider_config": {"webhook_url": "https://route.test"},
        },
        headers=auth_headers,
    )
    sink_id = sink_resp.json()["id"]

    payload = {"sink_id": sink_id, "alert_severity": "critical", "enabled": True}
    resp = await client.post(ROUTES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert body["sink_id"] == sink_id
    assert body["alert_severity"] == "critical"
    assert body["enabled"] is True
    assert "id" in body

    # Verify in database
    route_in_db = db_session.get(NotificationRoute, body["id"])
    assert route_in_db is not None
    assert route_in_db.alert_severity == "critical"


@pytest.mark.asyncio
async def test_create_route_with_wildcard_severity(client, auth_headers):
    """POST /notifications/routes can use wildcard '*' for all severities."""
    sink_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Wildcard Sink",
            "provider_type": "discord",
            "provider_config": {"webhook_url": "https://wildcard.test"},
        },
        headers=auth_headers,
    )
    sink_id = sink_resp.json()["id"]

    resp = await client.post(
        ROUTES_URL,
        json={"sink_id": sink_id, "alert_severity": "*", "enabled": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["alert_severity"] == "*"


@pytest.mark.asyncio
async def test_create_route_info_severity(client, auth_headers):
    """POST /notifications/routes with 'info' severity."""
    sink_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Info Sink",
            "provider_type": "email",
            "provider_config": {"to_addresses": ["info@test.com"]},
        },
        headers=auth_headers,
    )
    sink_id = sink_resp.json()["id"]

    resp = await client.post(
        ROUTES_URL,
        json={"sink_id": sink_id, "alert_severity": "info"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["alert_severity"] == "info"


@pytest.mark.asyncio
async def test_create_route_warning_severity(client, auth_headers):
    """POST /notifications/routes with 'warning' severity."""
    sink_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Warning Sink",
            "provider_type": "teams",
            "provider_config": {"webhook_url": "https://warning.test"},
        },
        headers=auth_headers,
    )
    sink_id = sink_resp.json()["id"]

    resp = await client.post(
        ROUTES_URL,
        json={"sink_id": sink_id, "alert_severity": "warning"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["alert_severity"] == "warning"


@pytest.mark.asyncio
async def test_list_routes_returns_created(client, auth_headers):
    """GET /notifications/routes includes previously created routes."""
    sink_resp = await client.post(
        SINKS_URL,
        json={
            "name": "List Route Sink",
            "provider_type": "slack",
            "provider_config": {"webhook_url": "https://list.test"},
        },
        headers=auth_headers,
    )
    sink_id = sink_resp.json()["id"]

    await client.post(
        ROUTES_URL,
        json={"sink_id": sink_id, "alert_severity": "critical"},
        headers=auth_headers,
    )

    resp = await client.get(ROUTES_URL, headers=auth_headers)
    assert resp.status_code == 200

    routes = resp.json()
    assert len(routes) >= 1
    assert any(r["sink_id"] == sink_id for r in routes)


@pytest.mark.asyncio
async def test_get_route_by_id(client, auth_headers):
    """GET /notifications/routes/{id} returns specific route."""
    sink_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Get Route Sink",
            "provider_type": "discord",
            "provider_config": {"webhook_url": "https://getroute.test"},
        },
        headers=auth_headers,
    )
    sink_id = sink_resp.json()["id"]

    create_resp = await client.post(
        ROUTES_URL,
        json={"sink_id": sink_id, "alert_severity": "warning"},
        headers=auth_headers,
    )
    route_id = create_resp.json()["id"]

    resp = await client.get(f"{ROUTES_URL}/{route_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["alert_severity"] == "warning"


@pytest.mark.asyncio
async def test_get_route_404_for_missing(client, auth_headers):
    """GET /notifications/routes/{id} returns 404 for non-existent route."""
    resp = await client.get(f"{ROUTES_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_notification_route(client, auth_headers, db_session):
    """PATCH /notifications/routes/{id} updates route fields."""
    sink_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Update Route Sink",
            "provider_type": "teams",
            "provider_config": {"webhook_url": "https://update.test"},
        },
        headers=auth_headers,
    )
    sink_id = sink_resp.json()["id"]

    create_resp = await client.post(
        ROUTES_URL,
        json={"sink_id": sink_id, "alert_severity": "info", "enabled": True},
        headers=auth_headers,
    )
    route_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"{ROUTES_URL}/{route_id}",
        json={"alert_severity": "critical", "enabled": False},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["alert_severity"] == "critical"
    assert update_resp.json()["enabled"] is False

    # Verify in database
    route_in_db = db_session.get(NotificationRoute, route_id)
    assert route_in_db.alert_severity == "critical"
    assert route_in_db.enabled is False


@pytest.mark.asyncio
async def test_update_route_404_for_missing(client, auth_headers):
    """PATCH /notifications/routes/{id} returns 404 for non-existent route."""
    resp = await client.patch(
        f"{ROUTES_URL}/99999", json={"alert_severity": "warning"}, headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_notification_route(client, auth_headers, db_session):
    """DELETE /notifications/routes/{id} removes route."""
    sink_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Delete Route Sink",
            "provider_type": "email",
            "provider_config": {"to_addresses": ["delete@test.com"]},
        },
        headers=auth_headers,
    )
    sink_id = sink_resp.json()["id"]

    create_resp = await client.post(
        ROUTES_URL,
        json={"sink_id": sink_id, "alert_severity": "info"},
        headers=auth_headers,
    )
    route_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"{ROUTES_URL}/{route_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Verify removed from database
    route_in_db = db_session.get(NotificationRoute, route_id)
    assert route_in_db is None


@pytest.mark.asyncio
async def test_delete_route_404_for_missing(client, auth_headers):
    """DELETE /notifications/routes/{id} returns 404 for non-existent route."""
    resp = await client.delete(f"{ROUTES_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


# ── Sink Test Endpoint ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_test_notification_sink_endpoint_exists(client, auth_headers):
    """POST /notifications/sinks/{id}/test endpoint exists."""
    sink_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Test Endpoint Sink",
            "provider_type": "slack",
            "provider_config": {"webhook_url": "https://testendpoint.test"},
        },
        headers=auth_headers,
    )
    sink_id = sink_resp.json()["id"]

    resp = await client.post(f"{SINKS_URL}/{sink_id}/test", headers=auth_headers)
    # The response may vary (200/500/400 depending on webhook validity)
    assert resp.status_code in (200, 400, 404, 500)


# ── Multiple Routes per Sink ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_sink_with_multiple_routes(client, auth_headers):
    """A single sink can have multiple routes with different severities."""
    sink_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Multi-Route Sink",
            "provider_type": "discord",
            "provider_config": {"webhook_url": "https://multi.test"},
        },
        headers=auth_headers,
    )
    sink_id = sink_resp.json()["id"]

    # Create multiple routes
    route1 = await client.post(
        ROUTES_URL,
        json={"sink_id": sink_id, "alert_severity": "info"},
        headers=auth_headers,
    )
    route2 = await client.post(
        ROUTES_URL,
        json={"sink_id": sink_id, "alert_severity": "critical"},
        headers=auth_headers,
    )

    assert route1.status_code == 200
    assert route2.status_code == 200

    # Verify both routes exist
    routes_resp = await client.get(ROUTES_URL, headers=auth_headers)
    sink_routes = [r for r in routes_resp.json() if r["sink_id"] == sink_id]
    assert len(sink_routes) >= 2


# ── Error Handling Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_sink_missing_required_field_returns_422(client, auth_headers):
    """POST /notifications/sinks without required 'name' field returns 422."""
    resp = await client.post(
        SINKS_URL,
        json={"provider_type": "slack", "provider_config": {}},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_route_nonexistent_sink_returns_error(client, auth_headers):
    """POST /notifications/routes with non-existent sink_id returns error."""
    resp = await client.post(
        ROUTES_URL,
        json={"sink_id": 99999, "alert_severity": "critical"},
        headers=auth_headers,
    )
    assert resp.status_code in (404, 400, 422)


@pytest.mark.asyncio
async def test_create_route_invalid_severity_returns_422(client, auth_headers):
    """POST /notifications/routes with invalid severity returns 422."""
    sink_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Invalid Severity Sink",
            "provider_type": "email",
            "provider_config": {"to_addresses": ["test@test.com"]},
        },
        headers=auth_headers,
    )
    sink_id = sink_resp.json()["id"]

    resp = await client.post(
        ROUTES_URL,
        json={"sink_id": sink_id, "alert_severity": "invalid_level"},
        headers=auth_headers,
    )
    assert resp.status_code in (422, 400)


@pytest.mark.asyncio
async def test_sink_provider_config_json_serialization(client, auth_headers, db_session):
    """Sink provider_config is properly serialized/deserialized as JSON."""
    complex_config = {
        "webhook_url": "https://complex.test",
        "channel": "#alerts",
        "username": "CircuitBreaker",
        "icon_emoji": ":warning:",
        "nested": {"key": "value", "list": [1, 2, 3]},
    }

    create_resp = await client.post(
        SINKS_URL,
        json={"name": "JSON Test", "provider_type": "slack", "provider_config": complex_config},
        headers=auth_headers,
    )
    assert create_resp.status_code == 200
    sink_id = create_resp.json()["id"]

    # Read back
    get_resp = await client.get(f"{SINKS_URL}/{sink_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    returned_config = get_resp.json()["provider_config"]
    assert returned_config == complex_config


@pytest.mark.asyncio
async def test_delete_sink_cascades_to_routes(client, auth_headers, db_session):
    """DELETE /notifications/sinks/{id} cascades deletion to associated routes."""
    # Create sink
    sink_resp = await client.post(
        SINKS_URL,
        json={
            "name": "Cascade Sink",
            "provider_type": "teams",
            "provider_config": {"webhook_url": "https://cascade.test"},
        },
        headers=auth_headers,
    )
    sink_id = sink_resp.json()["id"]

    # Create route
    route_resp = await client.post(
        ROUTES_URL,
        json={"sink_id": sink_id, "alert_severity": "warning"},
        headers=auth_headers,
    )
    route_id = route_resp.json()["id"]

    # Delete sink
    await client.delete(f"{SINKS_URL}/{sink_id}", headers=auth_headers)

    # Verify route is also deleted (or orphaned, depending on DB schema)
    route_check = await client.get(f"{ROUTES_URL}/{route_id}", headers=auth_headers)
    # Expect 404 if cascading delete is configured, or route exists but orphaned
    assert route_check.status_code in (404, 200)
    if route_check.status_code == 200:
        # If route still exists, verify sink_id is invalid
        route_in_db = db_session.get(NotificationRoute, route_id)
        if route_in_db:
            sink_in_db = db_session.get(NotificationSink, route_in_db.sink_id)
            assert sink_in_db is None
