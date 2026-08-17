"""Tenancy contract (formerly "Teams" multi-tenancy).

The v0.2.0 Teams feature these tests were written against no longer exists in
the shape they assumed. ``teams`` became the ``tenants`` table, its ``team_id``
foreign keys became ``tenant_id``, and Circuit Breaker 1.0 deliberately dropped
tenant isolation as a security boundary (ADR 0003): the router at
``/api/v1/tenants`` is kept mounted only so stale clients get an explicit
410 Gone instead of silently reactivating dormant tenant behavior. What remains
real is the ``tenant_id`` column on the entity tables, so rows written by an
older install still load. These tests pin that contract.

Requires CB_TEST_DB_URL to be set to a real PostgreSQL database URL because
JSONB and the tenant_id FK constraints are PostgreSQL-specific.

Run:
    CB_TEST_DB_URL=postgresql://breaker:breaker@localhost:5432/circuitbreaker_test \
        pytest tests/integration/test_teams.py -v
"""

import os

import pytest
from sqlalchemy import inspect

pytestmark = pytest.mark.skipif(
    not os.environ.get("CB_TEST_DB_URL"),
    reason="CB_TEST_DB_URL not set — PG required for team tenancy tests",
)


def test_tenants_api_is_gone(client, auth_headers):
    """Creating a team/tenant is refused loudly, not quietly ignored."""
    resp = client.post("/api/v1/tenants", json={"name": "Engineering"}, headers=auth_headers)
    assert resp.status_code == 410, resp.text
    assert "multi-tenancy is not supported" in resp.json()["detail"].lower()

    listing = client.get("/api/v1/tenants", headers=auth_headers)
    assert listing.status_code == 410, listing.text


def test_oobe_creates_no_default_team(client, auth_headers, db):
    """OOBE bootstrap must not seed a "Default Team" row.

    The pre-1.0 contract was that bootstrap created tenant id=1 and stamped
    every entity with it. Single-tenant 1.0 stamps nothing, so the table stays
    empty — and the app is fully usable regardless, which is what the health
    check confirms. (``auth_headers`` performs the token-gated bootstrap;
    ``/bootstrap/initialize`` has required ``setup_token`` since the OOBE
    hardening work.)
    """
    from app.db import models

    assert db.query(models.Tenant).count() == 0

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    data = health.json()
    assert data["ready"] is True
    assert data["checks"]["db"] == "ok"


def test_health_confirms_a_working_postgres_backend(client, db):
    """The db check passes, and the backend behind it really is PostgreSQL.

    The endpoint itself no longer names the dialect: server fingerprinting
    material is withheld from unauthenticated callers, so the dialect is
    asserted against the live connection instead of read out of the response.
    """
    assert db.get_bind().dialect.name == "postgresql"

    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["checks"]["db"] == "ok"


def test_hardware_has_tenant_id_column(client, auth_headers, db):
    """Hardware carries the tenancy column (``team_id`` renamed to ``tenant_id``)."""
    columns = {col["name"] for col in inspect(db.get_bind()).get_columns("hardware")}
    assert "tenant_id" in columns

    # Every entity route is authenticated, so this needs real credentials; an
    # anonymous GET here returns 401 and proves nothing about the schema.
    resp = client.get("/api/v1/hardware", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)
