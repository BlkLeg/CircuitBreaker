"""Feature 1 — Categories tests.

Category endpoints are auth-protected like the rest of the API, so every test
here runs against a bootstrapped app with admin credentials attached.
"""
import json
import time

import pytest


# ── Auth ─────────────────────────────────────────────────────────────────────
#
# First run stopped being an open admin session in cd1724ff: outside /bootstrap,
# /auth, the settings read and the OAuth provider write, every route answers 401
# until a real admin exists and presents a token. These tests drive ordinary
# CRUD, so they no longer ride on the un-bootstrapped app — they bootstrap and
# carry a Bearer header like any other caller.

@pytest.fixture(autouse=True)
def _authenticated_client(request):
    # Tests here that only touch the ORM never build a client; don't make them
    # pay for a bootstrap (and a bcrypt hash) they have no use for.
    if "client" not in request.fixturenames:
        return
    request.getfixturevalue("client").headers.update(request.getfixturevalue("auth_headers"))


# ── Log helpers ──────────────────────────────────────────────────────────────

def _await_log_entry(client, action, timeout_s=5.0):
    """Return the category audit entry for ``action``, waiting for it to land.

    The logging middleware writes audit rows fire-and-forget on an executor
    thread so the response is not held behind the audit-chain advisory lock, so
    the row is not guaranteed to be visible the instant the mutating call
    returns. Reading once races that thread; poll until the deadline instead.
    Returns None if it never arrives, leaving the assertion to the caller.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        logs = client.get("/api/v1/logs").json()["logs"]
        entry = next(
            (log for log in logs if log.get("entity_type") == "category" and log.get("action") == action),
            None,
        )
        if entry is not None or time.monotonic() >= deadline:
            return entry
        time.sleep(0.05)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _create_category(client, name="media", color="#6366f1"):
    return client.post("/api/v1/categories", json={"name": name, "color": color})


def _create_service(client, name="Plex", category_id=None, category=None):
    payload = {"name": name, "slug": name.lower().replace(" ", "-")}
    if category_id is not None:
        payload["category_id"] = category_id
    if category is not None:
        payload["category"] = category
    return client.post("/api/v1/services", json=payload)


# ── List / create ─────────────────────────────────────────────────────────────

def test_list_categories_empty(client):
    resp = client.get("/api/v1/categories")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_category_success(client):
    resp = _create_category(client, name="media", color="#6366f1")
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] is not None
    assert data["name"] == "media"
    assert data["color"] == "#6366f1"


def test_create_category_case_insensitive_duplicate(client):
    _create_category(client, name="media")
    resp = _create_category(client, name="Media")
    assert resp.status_code == 409


def test_create_category_no_color(client):
    resp = client.post("/api/v1/categories", json={"name": "infra"})
    assert resp.status_code == 201
    assert resp.json()["color"] is None


# ── service_count ─────────────────────────────────────────────────────────────

def test_list_categories_includes_service_count(client):
    cat = _create_category(client, name="media").json()
    _create_service(client, name="Plex", category_id=cat["id"])
    _create_service(client, name="Jellyfin", category_id=cat["id"])

    resp = client.get("/api/v1/categories")
    assert resp.status_code == 200
    cats = resp.json()
    found = next(c for c in cats if c["id"] == cat["id"])
    assert found["service_count"] == 2


# ── Rename ────────────────────────────────────────────────────────────────────

def test_rename_category(client):
    cat = _create_category(client, name="media").json()
    resp = client.patch(f"/api/v1/categories/{cat['id']}", json={"name": "streaming"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "streaming"
    assert resp.json()["service_count"] == 0


# ── Delete ────────────────────────────────────────────────────────────────────

def test_delete_category_unused(client):
    cat = _create_category(client).json()
    resp = client.delete(f"/api/v1/categories/{cat['id']}")
    assert resp.status_code == 204


def test_delete_category_in_use(client):
    cat = _create_category(client).json()
    _create_service(client, name="Plex", category_id=cat["id"])

    resp = client.delete(f"/api/v1/categories/{cat['id']}")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "blocking_services" in detail
    names = [s["name"] for s in detail["blocking_services"]]
    assert "Plex" in names


# ── Inline category on service ────────────────────────────────────────────────

def test_service_create_with_inline_category(client):
    resp = _create_service(client, name="Plex", category="newcat")
    assert resp.status_code == 201

    # The category should have been auto-created
    cats = client.get("/api/v1/categories").json()
    names = [c["name"] for c in cats]
    assert "newcat" in names

    # The service should reference it
    svc = resp.json()
    assert svc.get("category_id") is not None


def test_service_create_with_category_id(client):
    cat = _create_category(client, name="infra").json()
    resp = _create_service(client, name="Prometheus", category_id=cat["id"])
    assert resp.status_code == 201
    assert resp.json()["category_id"] == cat["id"]


def test_service_create_category_id_wins_over_string(client):
    cat = _create_category(client, name="infra").json()
    resp = _create_service(client, name="Grafana", category_id=cat["id"], category="other")
    assert resp.status_code == 201
    assert resp.json()["category_id"] == cat["id"]


# ── Audit log entries ─────────────────────────────────────────────────────────

def test_category_log_entry_on_create(client):
    _create_category(client, name="media")
    entry = _await_log_entry(client, "create_category")
    assert entry is not None, "Expected a 'create_category' log entry for category"
    assert entry["entity_name"] == "media"


def test_category_log_entry_on_rename(client):
    cat = _create_category(client, name="media").json()
    client.patch(f"/api/v1/categories/{cat['id']}", json={"name": "streaming"})

    entry = _await_log_entry(client, "update_category")
    assert entry is not None, "Expected a 'update_category' log entry for category"
    # Diff should capture before/after name
    if entry.get("diff"):
        diff = json.loads(entry["diff"]) if isinstance(entry["diff"], str) else entry["diff"]
        before = diff.get("before") or {}
        after = diff.get("after") or {}
        assert before.get("name") == "media" or after.get("name") == "streaming"


def test_category_log_entry_on_delete(client):
    cat = _create_category(client, name="media").json()
    client.delete(f"/api/v1/categories/{cat['id']}")

    entry = _await_log_entry(client, "delete_category")
    assert entry is not None, "Expected a 'delete_category' log entry for category"
