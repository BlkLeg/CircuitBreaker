"""
Tests for the environments API.

Routes (environments router mounted at /api/v1/environments):
  GET    /api/v1/environments              — list all environments
  POST   /api/v1/environments              — create environment (write auth)
  PATCH  /api/v1/environments/{id}         — update environment (write auth)
  DELETE /api/v1/environments/{id}         — delete environment (write auth)
"""

import pytest

pytestmark = pytest.mark.asyncio

_BASE = "/api/v1/environments"


# ── CRUD ─────────────────────────────────────────────────────────────────────


async def test_list_environments_empty(client, auth_headers):
    resp = await client.get(_BASE, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_environment(client, auth_headers):
    resp = await client.post(
        _BASE, headers=auth_headers, json={"name": "production", "color": "#00ff00"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "production"
    assert body["color"] == "#00ff00"
    assert "id" in body


async def test_create_duplicate_environment_returns_409(client, auth_headers):
    await client.post(_BASE, headers=auth_headers, json={"name": "dup-env"})
    resp = await client.post(_BASE, headers=auth_headers, json={"name": "dup-env"})
    assert resp.status_code == 409


async def test_update_environment(client, auth_headers):
    create = await client.post(_BASE, headers=auth_headers, json={"name": "staging"})
    env_id = create.json()["id"]
    resp = await client.patch(
        f"{_BASE}/{env_id}",
        headers=auth_headers,
        json={"name": "staging-v2", "color": "#0000ff"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "staging-v2"


async def test_delete_environment(client, auth_headers):
    create = await client.post(_BASE, headers=auth_headers, json={"name": "to-delete"})
    env_id = create.json()["id"]
    resp = await client.delete(f"{_BASE}/{env_id}", headers=auth_headers)
    assert resp.status_code == 204


async def test_delete_nonexistent_environment_returns_404(client, auth_headers):
    resp = await client.delete(f"{_BASE}/999999", headers=auth_headers)
    assert resp.status_code == 404


# ── Viewer RBAC ──────────────────────────────────────────────────────────────


async def test_viewer_can_list_environments(client, viewer_headers):
    resp = await client.get(_BASE, headers=viewer_headers)
    assert resp.status_code == 200


async def test_viewer_cannot_create_environment(client, viewer_headers):
    resp = await client.post(_BASE, headers=viewer_headers, json={"name": "blocked"})
    assert resp.status_code == 403


async def test_viewer_cannot_delete_environment(client, viewer_headers, factories):
    env = factories.environment(name="viewer-nodelete")
    resp = await client.delete(f"{_BASE}/{env.id}", headers=viewer_headers)
    assert resp.status_code == 403
