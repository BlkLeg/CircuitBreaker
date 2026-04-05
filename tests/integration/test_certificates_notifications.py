import pytest
from datetime import datetime

# ── Certificates ──────────────────────────────────────────────────────────────

def test_certificate_crud(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # 1. Create
    payload = {
        "domain": "test-backend.local",
        "type": "selfsigned",
        "auto_renew": True
    }
    resp = client.post("/api/v1/certificates", json=payload, headers=headers)
    assert resp.status_code in (200, 201)
    cert = resp.json()
    assert cert["domain"] == "test-backend.local"
    assert "cert_pem" not in cert  # List/Create summary doesn't include PEM
    
    # 2. List
    resp = client.get("/api/v1/certificates", headers=headers)
    assert resp.status_code == 200
    assert any(c["domain"] == "test-backend.local" for c in resp.json())
    
    # 3. Detail (should include PEM)
    cert_id = cert["id"]
    resp = client.get(f"/api/v1/certificates/{cert_id}", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert "cert_pem" in detail
    assert "-----BEGIN CERTIFICATE-----" in detail["cert_pem"]
    
    # 4. Renew
    resp = client.post(f"/api/v1/certificates/{cert_id}/renew", headers=headers)
    assert resp.status_code == 200
    
    # 5. Delete
    resp = client.delete(f"/api/v1/certificates/{cert_id}", headers=headers)
    assert resp.status_code == 200


# ── Notifications ─────────────────────────────────────────────────────────────

def test_notification_sinks_and_routes(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # 1. Create Sink
    sink_payload = {
        "name": "Test Slack",
        "provider_type": "slack",
        "provider_config": {"webhook_url": "https://hooks.slack.com/services/T00/B00/XXX"},
        "enabled": True
    }
    resp = client.post("/api/v1/notifications/sinks", json=sink_payload, headers=headers)
    assert resp.status_code == 200
    sink = resp.json()
    sink_id = sink["id"]
    
    # 2. Create Route
    route_payload = {
        "sink_id": sink_id,
        "alert_severity": "critical",
        "enabled": True
    }
    resp = client.post("/api/v1/notifications/routes", json=route_payload, headers=headers)
    assert resp.status_code == 200
    route = resp.json()
    assert route["sink_id"] == sink_id
    
    # 3. List
    resp = client.get("/api/v1/notifications/sinks", headers=headers)
    assert any(s["id"] == sink_id for s in resp.json())
    
    # 4. Test Sink (should attempt HTTP call)
    # Note: This might fail in CI if it tries to hit real Slack, 
    # but the API should return a handled error or success if mocked.
    resp = client.post(f"/api/v1/notifications/sinks/{sink_id}/test", headers=headers)
    assert resp.status_code == 200
    
    # 5. Cleanup
    client.delete(f"/api/v1/notifications/routes/{route['id']}", headers=headers)
    client.delete(f"/api/v1/notifications/sinks/{sink_id}", headers=headers)


# ── Helpers / Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def admin_token(client):
    # Try to bootstrap or login
    resp = client.post(
        "/api/v1/bootstrap/initialize",
        json={
            "email": f"test-admin-{datetime.now().timestamp()}@example.com",
            "password": "SecurePassword123!",
            "theme_preset": "one-dark",
        },
    )
    if resp.status_code == 200:
        return resp.json()["token"]
    
    # Fallback to login if already bootstrapped
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "bootstrap@example.com", "password": "SecurePassword123!"}
    )
    return resp.json()["token"]
