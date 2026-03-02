"""Feature 6 — Audit Log tests.

Covers sanitise_diff unit tests, log filter/pagination, immutability,
and log entries produced by hardware/service/network/auth operations.
"""
import json

from app.services.log_service import sanitise_diff


# ── sanitise_diff unit tests ──────────────────────────────────────────────────

def test_sanitise_diff_redacts_password_key():
    result = sanitise_diff({"password": "secret123", "name": "admin"})
    assert result["password"] == "***REDACTED***"
    assert result["name"] == "admin"


def test_sanitise_diff_redacts_nested_keys():
    result = sanitise_diff({"config": {"token": "abc", "host": "10.0.0.1"}})
    assert result["config"]["token"] == "***REDACTED***"
    assert result["config"]["host"] == "10.0.0.1"


def test_sanitise_diff_redacts_list_of_dicts():
    result = sanitise_diff([{"api_key": "xyz"}, {"name": "test"}])
    assert result[0]["api_key"] == "***REDACTED***"
    assert result[1]["name"] == "test"


# ── Hardware CRUD log entries ─────────────────────────────────────────────────

def test_hardware_create_produces_log(client):
    client.post("/api/v1/hardware", json={"name": "pve-01"})

    logs = client.get("/api/v1/logs").json()["logs"]
    entry = next(
        (log for log in logs if log.get("entity_type") == "hardware" and log.get("action") == "create_hardware"),
        None,
    )
    assert entry is not None, "Expected 'create_hardware' log"
    assert entry["entity_name"] == "pve-01"

    if entry.get("diff"):
        diff = json.loads(entry["diff"]) if isinstance(entry["diff"], str) else entry["diff"]
        assert diff.get("before") is None
        assert diff.get("after") is not None
        assert "name" in diff["after"]


def test_hardware_update_produces_log_with_diff(client):
    hw = client.post("/api/v1/hardware", json={"name": "pve-01"}).json()
    client.patch(f"/api/v1/hardware/{hw['id']}", json={"name": "pve-02"})

    logs = client.get("/api/v1/logs").json()["logs"]
    entry = next(
        (log for log in logs if log.get("entity_type") == "hardware" and log.get("action") == "update_hardware"),
        None,
    )
    assert entry is not None, "Expected 'update_hardware' log"

    if entry.get("diff"):
        diff = json.loads(entry["diff"]) if isinstance(entry["diff"], str) else entry["diff"]
        before = diff.get("before") or {}
        after = diff.get("after") or {}
        assert before.get("name") == "pve-01" or after.get("name") == "pve-02"


def test_hardware_delete_produces_log(client):
    hw = client.post("/api/v1/hardware", json={"name": "pve-01"}).json()
    client.delete(f"/api/v1/hardware/{hw['id']}")

    logs = client.get("/api/v1/logs").json()["logs"]
    entry = next(
        (log for log in logs if log.get("entity_type") == "hardware" and log.get("action") == "delete_hardware"),
        None,
    )
    assert entry is not None, "Expected 'delete_hardware' log"

    if entry.get("diff"):
        diff = json.loads(entry["diff"]) if isinstance(entry["diff"], str) else entry["diff"]
        assert diff.get("after") is None


# ── Service CRUD log entries ──────────────────────────────────────────────────

def test_service_create_update_delete_logs(client):
    svc = client.post("/api/v1/services", json={"name": "Plex", "slug": "plex"}).json()
    client.patch(f"/api/v1/services/{svc['id']}", json={"name": "Plex Media"})
    client.delete(f"/api/v1/services/{svc['id']}")

    logs = client.get("/api/v1/logs").json()["logs"]
    svc_logs = [log for log in logs if log.get("entity_type") == "service"]
    actions = {log["action"] for log in svc_logs}
    assert "create_service" in actions, "Expected 'create_service' log"
    assert "update_service" in actions, "Expected 'update_service' log"
    assert "delete_service" in actions, "Expected 'delete_service' log"


# ── Network CRUD log entries ──────────────────────────────────────────────────

def test_network_create_update_delete_logs(client):
    net = client.post("/api/v1/networks", json={"name": "LAN", "cidr": "192.168.1.0/24"}).json()
    client.patch(f"/api/v1/networks/{net['id']}", json={"name": "LAN-Updated"})
    client.delete(f"/api/v1/networks/{net['id']}")

    logs = client.get("/api/v1/logs").json()["logs"]
    net_logs = [log for log in logs if log.get("entity_type") == "network"]
    actions = {log["action"] for log in net_logs}
    assert "create_network" in actions, "Expected 'create_network' log"
    assert "update_network" in actions, "Expected 'update_network' log"
    assert "delete_network" in actions, "Expected 'delete_network' log"


# ── Auth log entries ──────────────────────────────────────────────────────────

def test_login_success_produces_log(client, auth_headers):
    # auth_headers fixture performs bootstrap + login; we check the resulting log
    logs = client.get("/api/v1/logs", headers=auth_headers).json()["logs"]
    entry = next(
        (log for log in logs if log.get("entity_type") == "auth" and log.get("action") == "login_success"),
        None,
    )
    assert entry is not None, "Expected 'login_success' auth log"
    assert entry.get("ip_address") is not None


def test_login_failure_produces_warn_log(client):
    # Bootstrap so that an account exists, then fail to log in
    client.post("/api/v1/bootstrap/initialize", json={
        "email": "test@example.com",
        "password": "Secure1234!",
        "theme_preset": "one-dark",
    })
    client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "wrong-password",
    })

    logs = client.get("/api/v1/logs").json()["logs"]
    entry = next(
        (log for log in logs if log.get("action") == "login_failed"),
        None,
    )
    assert entry is not None, "Expected 'login_failed' log entry"
    assert entry.get("severity") == "warn"


# ── Credential safety ─────────────────────────────────────────────────────────

def test_settings_update_log_never_contains_credentials(client):
    client.put("/api/v1/settings", json={"timezone": "UTC"})

    logs = client.get("/api/v1/logs").json()["logs"]
    for entry in logs:
        raw_diff = entry.get("diff") or ""
        if isinstance(raw_diff, dict):
            raw_diff = json.dumps(raw_diff)
        # No raw credential values should appear in any diff
        for bad in ("password", "secret", "token"):
            assert bad not in raw_diff.lower().replace("***redacted***", ""), \
                f"Log entry {entry.get('id')} diff contains unredacted '{bad}'"


# ── Immutability ─────────────────────────────────────────────────────────────

def test_logs_no_delete_endpoint_exists(client):
    resp = client.delete("/api/v1/logs/1")
    assert resp.status_code in (404, 405)


def test_logs_no_update_endpoint_exists(client):
    resp = client.patch("/api/v1/logs/1", json={})
    assert resp.status_code in (404, 405)


# ── Filter parameters ─────────────────────────────────────────────────────────

def test_logs_filter_by_entity_type(client):
    client.post("/api/v1/hardware", json={"name": "pve-01"})
    client.post("/api/v1/services", json={"name": "Plex"})

    resp = client.get("/api/v1/logs", params={"entity_type": "hardware"})
    assert resp.status_code == 200
    logs = resp.json()["logs"]
    assert len(logs) > 0
    assert all(log["entity_type"] == "hardware" for log in logs)


def test_logs_filter_by_action(client):
    client.post("/api/v1/hardware", json={"name": "pve-01"})

    resp = client.get("/api/v1/logs", params={"action": "create_hardware"})
    assert resp.status_code == 200
    logs = resp.json()["logs"]
    assert len(logs) > 0
    assert all(log["action"] == "create_hardware" for log in logs)


def test_logs_filter_by_severity(client):
    # Bootstrap + failed login to produce a 'warn' severity entry
    client.post("/api/v1/bootstrap/initialize", json={
        "email": "test@example.com",
        "password": "Secure1234!",
        "theme_preset": "one-dark",
    })
    client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "badpass",
    })

    resp = client.get("/api/v1/logs", params={"severity": "warn"})
    assert resp.status_code == 200
    logs = resp.json()["logs"]
    assert len(logs) > 0
    assert all(log.get("severity") == "warn" for log in logs)


def test_logs_search_by_entity_name(client):
    client.post("/api/v1/hardware", json={"name": "unique-device-xyz"})

    resp = client.get("/api/v1/logs", params={"search": "unique-device"})
    assert resp.status_code == 200
    logs = resp.json()["logs"]
    assert len(logs) > 0
    names = [log.get("entity_name") or "" for log in logs]
    assert any("unique-device" in n for n in names)


# ── Pagination ────────────────────────────────────────────────────────────────

def test_logs_pagination(client):
    # Generate enough hardware entries to push log count past 100
    for i in range(110):
        client.post("/api/v1/hardware", json={"name": f"hw-{i}"})

    resp_p1 = client.get("/api/v1/logs", params={"limit": 100, "offset": 0})
    assert resp_p1.status_code == 200
    data_p1 = resp_p1.json()
    assert len(data_p1["logs"]) == 100
    assert data_p1["total_count"] > 100

    resp_p2 = client.get("/api/v1/logs", params={"limit": 100, "offset": 100})
    assert resp_p2.status_code == 200
    data_p2 = resp_p2.json()
    assert len(data_p2["logs"]) > 0
    assert len(data_p2["logs"]) < 100


# ── OOBE log entry ────────────────────────────────────────────────────────────

def test_oobe_complete_produces_log(client):
    client.post("/api/v1/bootstrap/initialize", json={
        "email": "admin@example.com",
        "password": "Secure1234!",
        "theme_preset": "one-dark",
        "timezone": "UTC",
    })

    logs = client.get("/api/v1/logs").json()["logs"]
    entry = next(
        (log for log in logs if log.get("action") == "bootstrap_create_user"),
        None,
    )
    assert entry is not None, "Expected 'bootstrap_create_user' log entry"

    # Diff should not contain raw credentials
    raw_diff = json.dumps(entry.get("diff") or {})
    assert "password" not in raw_diff.lower().replace("***redacted***", "")
