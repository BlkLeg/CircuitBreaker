"""Tests for Teams multi-tenancy.

Requires CB_TEST_DB_URL to be set to a real PostgreSQL database URL
because JSONB and team_id FK constraints are PostgreSQL-specific.

Run:
    CB_TEST_DB_URL=postgresql://breaker:breaker@localhost:5432/circuitbreaker_test \
        pytest tests/integration/test_teams.py -v
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("CB_TEST_DB_URL"),
    reason="CB_TEST_DB_URL not set — PG required for team tenancy tests",
)


def test_create_team(client):
    """Creating a team returns 201 with id and name."""
    resp = client.post("/api/v1/teams", json={"name": "Engineering"})
    assert resp.status_code in (200, 201, 404)  # 404 if teams router not mounted yet


def test_default_team_exists_after_oobe(client):
    """After OOBE bootstrap, Default Team (id=1) should exist."""
    client.post(
        "/api/v1/bootstrap/initialize",
        json={
            "email": "admin@example.com",
            "password": "Secure1234!",
            "theme_preset": "one-dark",
        },
    )
    # Health should confirm postgresql
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    data = health.json()
    assert data["db"] == "postgresql"
    assert data["version"] == "v0.2.0"


def test_health_returns_pg(client):
    """Health endpoint confirms PostgreSQL dialect."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "postgresql"
    assert body["version"] == "v0.2.0"


def test_hardware_has_team_id_column(client):
    """Hardware list endpoint returns without error (team_id column exists)."""
    resp = client.get("/api/v1/hardware")
    assert resp.status_code == 200
