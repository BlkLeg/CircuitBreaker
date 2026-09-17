"""GET /api/v1/cve/fleet — the fleet assessment contract over HTTP."""

from __future__ import annotations

import pytest

from app.db.cve_session import init_cve_db
from app.db.models import Hardware
from app.db.session import SessionLocal


@pytest.fixture(scope="module", autouse=True)
def _cve_cache_schema():
    """The client fixture never runs the app lifespan, so the per-run CVE
    cache file has no tables until something creates them — this is what
    startup's schema step does, idempotently."""
    init_cve_db()


def _committed_hardware(**fields) -> Hardware:
    """A hardware row the service's own sessions can see.

    `fleet_assessment` opens `SessionLocal()` itself, so rows written through
    the test's SAVEPOINT-backed `db_session` are invisible to it. Write through
    a real connection instead; `db_session`'s teardown reaper deletes committed
    Hardware rows it did not observe at setup.
    """
    with SessionLocal() as writer:
        hardware = Hardware(**fields)
        writer.add(hardware)
        writer.commit()
        hardware_id = hardware.id
    with SessionLocal() as reader:
        return reader.get(Hardware, hardware_id)


@pytest.mark.asyncio
async def test_fleet_assessment_lists_every_assessable_entity(client, auth_headers):
    _committed_hardware(name="nas-01", vendor="acme", model="widget", os_version="1.9")

    response = await client.get("/api/v1/cve/fleet", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert "feed" in body and "summary" in body and "rows" in body and "limits" in body
    assert any(row["name"] == "nas-01" for row in body["rows"])


@pytest.mark.asyncio
async def test_an_un_ingested_feed_never_reads_as_clean(client, auth_headers):
    _committed_hardware(name="nas-01", vendor="acme", model="widget", os_version="1.9")

    body = (await client.get("/api/v1/cve/fleet", headers=auth_headers)).json()

    assert body["feed"]["state"] in {"unavailable", "incomplete"}
    assert {row["state"] for row in body["rows"]} == {"unavailable"}
    assert body["summary"]["entities_with_findings"] == 0


@pytest.mark.asyncio
async def test_a_viewer_may_read_the_fleet_console(client, viewer_headers):
    response = await client.get("/api/v1/cve/fleet", headers=viewer_headers)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_an_anonymous_caller_may_not(client):
    response = await client.get("/api/v1/cve/fleet")

    assert response.status_code in {401, 403}
