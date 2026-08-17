"""Feature 6 — Audit Log tests.

Covers sanitise_diff unit tests, log filter/pagination, immutability,
and log entries produced by hardware/service/network/auth operations.
"""
import json
import time

import pytest
from app.db import models
from app.services.log_service import sanitise_diff

# ── Test constants ────────────────────────────────────────────────────────────
IP_INTERNAL_HOST = "10.0.0.1"      # host field value in sanitise_diff nested test
CIDR_AUDIT_LAN   = "192.168.1.0/24"  # network CIDR for audit-log create test

# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _authenticated_client(request):
    """Bootstrap + authenticate the HTTP client for every test that uses one.

    Every API route in this file is behind auth, so an unauthenticated client
    turns each audit assertion into an anonymous ``KeyError: 'logs'`` on a 401
    body. Attaching the headers to the client itself (rather than each call)
    also covers the mutating requests, whose audit entries are the actual
    subject here — an anonymous POST is rejected before it can be audited.
    Guarded on ``client`` being in the test's fixture closure so the pure
    ``sanitise_diff`` unit tests below do not pay for a TestClient + bootstrap.
    """
    if "client" not in request.fixturenames:
        return
    client = request.getfixturevalue("client")
    client.headers.update(request.getfixturevalue("auth_headers"))


# ── Audit-log read helpers ───────────────────────────────────────────────────
#
# LoggingMiddleware persists route-derived audit entries fire-and-forget in a
# worker thread so the mutating request is not delayed by the insert, and
# write_log takes the audit-chain advisory lock on its own connection. The row
# therefore lands a few milliseconds *after* the response the test already has:
# reading /logs exactly once is a race the test loses under load. These helpers
# retry the read until the entry under test shows up (or a short deadline
# passes, so a genuinely missing entry still fails). Only the read is retried —
# every assertion stays exactly as strict as before.

_LOG_WAIT_SECONDS = 5.0


def _logs_response(client, params=None, *, until=None, timeout=_LOG_WAIT_SECONDS):
    """GET /api/v1/logs, retrying until *until* holds for the response body."""
    deadline = time.monotonic() + timeout
    while True:
        resp = client.get("/api/v1/logs", params=params or {})
        assert resp.status_code == 200, (
            f"GET /api/v1/logs failed: HTTP {resp.status_code} {resp.text}"
        )
        data = resp.json()
        if until is None or until(data) or time.monotonic() >= deadline:
            return data
        time.sleep(0.05)


def _wait_for_logs(client, predicate, params=None, *, count=1):
    """Return all log entries matching *predicate*, waiting for *count* of them."""
    data = _logs_response(
        client,
        params,
        until=lambda d: sum(1 for log in d["logs"] if predicate(log)) >= count,
    )
    return [log for log in data["logs"] if predicate(log)]


def _wait_for_log(client, predicate, params=None):
    """Return the first log entry matching *predicate*, or None after the wait."""
    matches = _wait_for_logs(client, predicate, params)
    return matches[0] if matches else None


def _wait_for_actions(client, actions, predicate=None, params=None):
    """Return the set of logged actions once every action in *actions* is present."""
    keep = predicate or (lambda log: True)
    data = _logs_response(
        client,
        params,
        until=lambda d: actions <= {log.get("action") for log in d["logs"] if keep(log)},
    )
    return {log.get("action") for log in data["logs"] if keep(log)}


# ── sanitise_diff unit tests ──────────────────────────────────────────────────

def test_sanitise_diff_redacts_password_key():
    result = sanitise_diff({"password": "secret123", "name": "admin"})
    # Key name is masked so that 'password' does not appear in stored audit logs.
    # Longest-first replacement: "password" → "<hidden>"
    assert result.get("<hidden>") == "***REDACTED***"
    assert "password" not in result
    assert result["name"] == "admin"


def test_sanitise_diff_redacts_nested_keys():
    result = sanitise_diff({"config": {"token": "abc", "host": IP_INTERNAL_HOST}})
    # 'token' → '<hidden>'
    assert result["config"].get("<hidden>") == "***REDACTED***"
    assert "token" not in result["config"]
    assert result["config"]["host"] == IP_INTERNAL_HOST


def test_sanitise_diff_redacts_list_of_dicts():
    result = sanitise_diff([{"api_key": "xyz"}, {"name": "test"}])
    # Longest-first: "api_key" fully replaced → "<hidden>"
    assert result[0].get("<hidden>") == "***REDACTED***"
    assert "api_key" not in result[0]
    assert result[1]["name"] == "test"


# ── Hardware CRUD log entries ─────────────────────────────────────────────────

def test_hardware_create_produces_log(client):
    client.post("/api/v1/hardware", json={"name": "pve-01"})

    entry = _wait_for_log(
        client,
        lambda log: log.get("entity_type") == "hardware" and log.get("action") == "create_hardware",
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

    entry = _wait_for_log(
        client,
        lambda log: log.get("entity_type") == "hardware" and log.get("action") == "update_hardware",
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

    entry = _wait_for_log(
        client,
        lambda log: log.get("entity_type") == "hardware" and log.get("action") == "delete_hardware",
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

    actions = _wait_for_actions(
        client,
        {"create_service", "update_service", "delete_service"},
        predicate=lambda log: log.get("entity_type") == "service",
    )
    assert "create_service" in actions, "Expected 'create_service' log"
    assert "update_service" in actions, "Expected 'update_service' log"
    assert "delete_service" in actions, "Expected 'delete_service' log"


# ── Network CRUD log entries ──────────────────────────────────────────────────

def test_network_create_update_delete_logs(client):
    net = client.post("/api/v1/networks", json={"name": "LAN", "cidr": CIDR_AUDIT_LAN}).json()
    client.patch(f"/api/v1/networks/{net['id']}", json={"name": "LAN-Updated"})
    client.delete(f"/api/v1/networks/{net['id']}")

    actions = _wait_for_actions(
        client,
        {"create_network", "update_network", "delete_network"},
        predicate=lambda log: log.get("entity_type") == "network",
    )
    assert "create_network" in actions, "Expected 'create_network' log"
    assert "update_network" in actions, "Expected 'update_network' log"
    assert "delete_network" in actions, "Expected 'delete_network' log"


# ── Auth log entries ──────────────────────────────────────────────────────────

def test_login_success_produces_log(client, auth_headers):
    # auth_headers fixture performs bootstrap + login; we check the resulting log
    entry = _wait_for_log(
        client,
        lambda log: log.get("entity_type") == "auth" and log.get("action") == "login_success",
    )
    assert entry is not None, "Expected 'login_success' auth log"
    assert entry.get("ip_address") is not None


def test_login_failure_produces_warn_log(client):
    # The account already exists: the autouse fixture bootstraps it and logs in.
    # Bootstrap is one-shot and setup-token gated, so the test cannot mint its own
    # account a second time — it only needs to fail a login against the real one.
    client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "wrong-password",
    })

    entry = _wait_for_log(client, lambda log: log.get("action") == "login_failed")
    assert entry is not None, "Expected 'login_failed' log entry"
    assert entry.get("severity") == "warn"


def test_logs_enrich_actor_fields_with_name_fallback(client, db, auth_headers):
    user = db.query(models.User).filter(models.User.email == "test@example.com").one()
    user.profile_photo = "avatar-test.png"
    user.gravatar_hash = "fallbackhash123"
    db.add(
        models.Log(
            category="audit",
            action="name_fallback_enrichment",
            actor=user.email,
            actor_name=user.email,
            actor_id=None,
            actor_gravatar_hash=None,
            entity_type="service",
            level="info",
            severity="info",
        )
    )
    db.commit()

    logs = client.get("/api/v1/logs", headers=auth_headers).json()["logs"]
    entry = next((log for log in logs if log.get("action") == "name_fallback_enrichment"), None)
    assert entry is not None
    assert entry.get("actor_gravatar_hash") == "fallbackhash123"
    assert entry.get("actor_profile_photo_url") == "/uploads/profiles/avatar-test.png"


def test_logs_keep_stored_gravatar_while_resolving_profile_photo(client, db, auth_headers):
    user = db.query(models.User).filter(models.User.email == "test@example.com").one()
    user.profile_photo = "avatar-precedence.png"
    user.gravatar_hash = "dbhash123"
    db.add(
        models.Log(
            category="audit",
            action="name_fallback_gravatar_precedence",
            actor=user.email,
            actor_name=user.email,
            actor_id=None,
            actor_gravatar_hash="storedhash999",
            entity_type="service",
            level="info",
            severity="info",
        )
    )
    db.commit()

    logs = client.get("/api/v1/logs", headers=auth_headers).json()["logs"]
    entry = next(
        (log for log in logs if log.get("action") == "name_fallback_gravatar_precedence"),
        None,
    )
    assert entry is not None
    assert entry.get("actor_gravatar_hash") == "storedhash999"
    assert entry.get("actor_profile_photo_url") == "/uploads/profiles/avatar-precedence.png"


def test_logs_do_not_enrich_reserved_system_actor_name(client, db, auth_headers):
    db.add(
        models.Log(
            category="audit",
            action="reserved_actor_no_fallback",
            actor="system",
            actor_name="system",
            actor_id=None,
            actor_gravatar_hash=None,
            entity_type="service",
            level="info",
            severity="info",
        )
    )
    db.commit()

    logs = client.get("/api/v1/logs", headers=auth_headers).json()["logs"]
    entry = next((log for log in logs if log.get("action") == "reserved_actor_no_fallback"), None)
    assert entry is not None
    assert entry.get("actor_gravatar_hash") is None
    assert entry.get("actor_profile_photo_url") is None


# ── Credential safety ─────────────────────────────────────────────────────────

def test_settings_update_log_never_contains_credentials(client):
    client.put("/api/v1/settings", json={"timezone": "UTC"})

    logs = _logs_response(
        client,
        until=lambda d: any(log.get("action") == "update_settings" for log in d["logs"]),
    )["logs"]
    assert any(entry.get("action") == "update_settings" for entry in logs), (
        "Expected an 'update_settings' log — without it this test would scan a "
        "log set that never contained the settings payload it is checking."
    )
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

    logs = _logs_response(
        client,
        {"entity_type": "hardware"},
        until=lambda d: bool(d["logs"]),
    )["logs"]
    assert len(logs) > 0
    assert all(log["entity_type"] == "hardware" for log in logs)


def test_logs_filter_by_action(client):
    client.post("/api/v1/hardware", json={"name": "pve-01"})

    logs = _logs_response(
        client,
        {"action": "create_hardware"},
        until=lambda d: bool(d["logs"]),
    )["logs"]
    assert len(logs) > 0
    assert all(log["action"] == "create_hardware" for log in logs)


def test_logs_filter_by_severity(client):
    # Failed login against the bootstrapped account produces a 'warn' severity entry
    client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "badpass",
    })

    logs = _logs_response(client, {"severity": "warn"}, until=lambda d: bool(d["logs"]))["logs"]
    assert len(logs) > 0
    assert all(log.get("severity") == "warn" for log in logs)


def test_logs_search_by_entity_name(client):
    client.post("/api/v1/hardware", json={"name": "unique-device-xyz"})

    logs = _logs_response(client, {"search": "unique-device"}, until=lambda d: bool(d["logs"]))["logs"]
    assert len(logs) > 0
    names = [log.get("entity_name") or "" for log in logs]
    assert any("unique-device" in n for n in names)


# ── Pagination ────────────────────────────────────────────────────────────────

def test_logs_pagination(client):
    # Generate enough hardware entries to push log count past 100
    for i in range(110):
        client.post("/api/v1/hardware", json={"name": f"hw-{i}"})

    data_p1 = _logs_response(
        client,
        {"limit": 100, "offset": 0},
        until=lambda d: d["total_count"] > 100,
    )
    assert len(data_p1["logs"]) == 100
    assert data_p1["total_count"] > 100

    data_p2 = _logs_response(client, {"limit": 100, "offset": 100})
    assert len(data_p2["logs"]) > 0
    assert len(data_p2["logs"]) <= 100


# ── OOBE log entry ────────────────────────────────────────────────────────────

def test_oobe_complete_produces_log(client):
    # The bootstrap under test is the one the autouse fixture performs: it walks
    # the real setup-token flow through POST /bootstrap/initialize. Bootstrap only
    # ever runs once per install, so the test reads back that run's audit entry
    # rather than trying to initialise an already-initialised app.
    entry = _wait_for_log(client, lambda log: log.get("action") == "bootstrap_create_user")
    assert entry is not None, "Expected 'bootstrap_create_user' log entry"

    # Diff should not contain raw credentials
    raw_diff = json.dumps(entry.get("diff") or {})
    assert "password" not in raw_diff.lower().replace("***redacted***", "")


def test_graph_map_mutations_produce_graph_audit_logs(client, db, auth_headers):
    hw = models.Hardware(name="graph-host")
    db.add(hw)
    db.flush()

    cu = models.ComputeUnit(name="graph-vm", kind="vm", hardware_id=hw.id)
    net = models.Network(name="graph-net")
    db.add_all([cu, net])
    db.flush()

    link = models.ComputeNetwork(compute_id=cu.id, network_id=net.id, connection_type="ethernet")
    db.add(link)
    db.commit()

    edge_id = f"e-cn-{link.id}"

    layout_resp = client.post(
        "/api/v1/graph/layout",
        json={"name": "default", "layout_data": '{"nodes":{},"edges":{}}'},
        headers=auth_headers,
    )
    assert layout_resp.status_code == 200

    patch_resp = client.patch(
        f"/api/v1/graph/edges/{edge_id}",
        json={"connection_type": "wireguard"},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 200

    delete_resp = client.delete(f"/api/v1/graph/edges/{edge_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    actions = _wait_for_actions(
        client, {"save_graph_layout", "update_graph_edge", "delete_graph_edge"}
    )
    assert "save_graph_layout" in actions
    assert "update_graph_edge" in actions
    assert "delete_graph_edge" in actions


def test_nested_relationship_mutations_are_audited(client, db, auth_headers):
    hw = models.Hardware(name="rel-host")
    net = models.Network(name="rel-net")
    cluster = models.HardwareCluster(name="rel-cluster")
    db.add_all([hw, net, cluster])
    db.commit()

    add_member = client.post(
        f"/api/v1/networks/{net.id}/hardware-members",
        json={"hardware_id": hw.id},
        headers=auth_headers,
    )
    assert add_member.status_code == 201

    add_cluster_member = client.post(
        f"/api/v1/hardware-clusters/{cluster.id}/members",
        json={"hardware_id": hw.id, "role": "member"},
        headers=auth_headers,
    )
    assert add_cluster_member.status_code == 201
    member_id = add_cluster_member.json()["id"]

    remove_member = client.delete(
        f"/api/v1/networks/{net.id}/hardware-members/{hw.id}",
        headers=auth_headers,
    )
    assert remove_member.status_code == 204

    remove_cluster_member = client.delete(
        f"/api/v1/hardware-clusters/{cluster.id}/members/{member_id}",
        headers=auth_headers,
    )
    assert remove_cluster_member.status_code == 204

    actions = _wait_for_actions(
        client,
        {"add_hardware_member", "remove_hardware_member", "add_member", "remove_member"},
    )
    assert "add_hardware_member" in actions
    assert "remove_hardware_member" in actions
    assert "add_member" in actions
    assert "remove_member" in actions
