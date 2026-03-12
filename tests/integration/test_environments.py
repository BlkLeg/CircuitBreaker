"""Feature 2 — Environments tests.

Auth is always enabled after bootstrap. These tests run on a fresh DB
before bootstrap completes, so writes succeed without auth headers.
The auth_headers fixture is only used in tests that explicitly need auth.
"""

from app.db.models import Environment
from app.services.environments_service import resolve_environment_id

# ── Helpers ──────────────────────────────────────────────────────────────────

def _create_env(client, name="prod", color=None):
    payload = {"name": name}
    if color:
        payload["color"] = color
    return client.post("/api/v1/environments", json=payload)


def _create_hardware(client, name="pve-01", environment=None, environment_id=None):
    payload = {"name": name}
    if environment:
        payload["environment"] = environment
    if environment_id:
        payload["environment_id"] = environment_id
    return client.post("/api/v1/hardware", json=payload)


def _create_compute(client, name="vm-01", environment=None, environment_id=None):
    hw = client.post("/api/v1/hardware", json={"name": f"host-for-{name}"}).json()
    payload = {"name": name, "kind": "vm", "hardware_id": hw["id"]}
    if environment:
        payload["environment"] = environment
    if environment_id:
        payload["environment_id"] = environment_id
    return client.post("/api/v1/compute-units", json=payload)


def _create_service(client, name="Plex", environment=None, environment_id=None):
    payload = {"name": name, "slug": name.lower().replace(" ", "-")}
    if environment:
        payload["environment"] = environment
    if environment_id:
        payload["environment_id"] = environment_id
    return client.post("/api/v1/services", json=payload)


# ── List / create ─────────────────────────────────────────────────────────────

def test_list_environments_empty(client):
    resp = client.get("/api/v1/environments")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_environment_success(client):
    resp = _create_env(client, name="prod", color="#00ff00")
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] is not None
    assert data["name"] == "prod"


def test_create_environment_case_insensitive_duplicate(client):
    _create_env(client, name="prod")
    resp = _create_env(client, name="Prod")
    assert resp.status_code == 409


# ── usage_count across tables ────────────────────────────────────────────────

def test_list_environments_usage_count_across_all_tables(client):
    env = _create_env(client, name="prod").json()
    env_id = env["id"]

    _create_hardware(client, name="pve-01", environment_id=env_id)
    _create_compute(client, name="vm-01", environment_id=env_id)
    _create_service(client, name="Plex", environment_id=env_id)
    _create_service(client, name="Jellyfin", environment_id=env_id)

    resp = client.get("/api/v1/environments")
    assert resp.status_code == 200
    envs = resp.json()
    found = next(e for e in envs if e["id"] == env_id)
    assert found["usage_count"] == 4


# ── Delete (unlinks entities; no blockers) ─────────────────────────────────────

def test_delete_environment_in_use_unlinks_and_deletes(client):
    """Deleting an environment in use clears entity references and deletes the env."""
    env = _create_env(client, name="prod").json()
    env_id = env["id"]
    _create_hardware(client, name="pve-01", environment_id=env_id)
    _create_service(client, name="Plex", environment_id=env_id)

    resp = client.delete(f"/api/v1/environments/{env_id}")
    assert resp.status_code == 204

    envs = client.get("/api/v1/environments").json()
    assert not any(e["id"] == env_id for e in envs)

    hw = client.get("/api/v1/hardware").json()
    pve = next((h for h in hw if h.get("name") == "pve-01"), None)
    assert pve is not None
    assert pve.get("environment_id") is None

    svc = client.get("/api/v1/services").json()
    plex = next((s for s in svc if s.get("name") == "Plex"), None)
    assert plex is not None
    assert plex.get("environment_id") is None


# ── Backfill ─────────────────────────────────────────────────────────────────

def test_environment_backfill_on_startup(db):
    """resolve_environment_id with an unknown name creates an Environment row."""
    env_id = resolve_environment_id(db, None, "prod")
    assert env_id is not None

    # The environment row should now exist
    env_row = db.query(Environment).filter(Environment.name == "prod").first()
    assert env_row is not None
    assert env_row.id == env_id


def test_environment_case_insensitive_backfill_dedup(db):
    """'Prod' and 'prod' from two different entities should map to one environment row."""
    env_id_1 = resolve_environment_id(db, None, "Prod")
    env_id_2 = resolve_environment_id(db, None, "prod")

    # Both resolve to the same environment
    assert env_id_1 == env_id_2

    count = db.query(Environment).filter(
        Environment.name.ilike("prod")
    ).count()
    assert count == 1


# ── Inline environment on entities ───────────────────────────────────────────

def test_hardware_create_with_inline_environment(client):
    resp = _create_hardware(client, name="pve-01", environment="staging")
    assert resp.status_code == 201
    assert resp.json().get("environment_id") is not None

    envs = client.get("/api/v1/environments").json()
    names = [e["name"] for e in envs]
    assert "staging" in names


def test_compute_create_with_inline_environment(client):
    resp = _create_compute(client, name="vm-01", environment="staging")
    assert resp.status_code == 201
    assert resp.json().get("environment_id") is not None


def test_service_create_with_inline_environment(client):
    resp = _create_service(client, name="Plex", environment="staging")
    assert resp.status_code == 201
    assert resp.json().get("environment_id") is not None


# ── Audit log entries ─────────────────────────────────────────────────────────

def test_environment_log_on_create(client):
    _create_env(client, name="prod")
    logs = client.get("/api/v1/logs").json()["logs"]
    entry = next(
        (log for log in logs if log.get("entity_type") == "environment" and log.get("action") == "create_environment"),
        None,
    )
    assert entry is not None, "Expected a 'create_environment' log for environment"
    assert entry["entity_name"] == "prod"


def test_environment_log_on_rename(client):
    env = _create_env(client, name="prod").json()
    client.patch(f"/api/v1/environments/{env['id']}", json={"name": "production"})

    logs = client.get("/api/v1/logs").json()["logs"]
    entry = next(
        (log for log in logs if log.get("entity_type") == "environment" and log.get("action") == "update_environment"),
        None,
    )
    assert entry is not None, "Expected a 'update_environment' log for environment"


def test_environment_log_on_delete(client):
    env = _create_env(client, name="prod").json()
    client.delete(f"/api/v1/environments/{env['id']}")

    logs = client.get("/api/v1/logs").json()["logs"]
    entry = next(
        (log for log in logs if log.get("entity_type") == "environment" and log.get("action") == "delete_environment"),
        None,
    )
    assert entry is not None, "Expected a 'delete_environment' log for environment"
