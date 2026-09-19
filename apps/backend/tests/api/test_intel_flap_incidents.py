"""GET /api/v1/intel/flap-incidents — the first reader for flap detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import FlapIncident, Hardware


def _incident(hardware_id, *, active=True, transitions=7):
    now = datetime.now(UTC)
    return FlapIncident(
        asset_type="hardware",
        asset_id=hardware_id,
        window_start=now - timedelta(minutes=30),
        window_end=now,
        transition_count=transitions,
        is_active=active,
        resolved_at=None if active else now,
    )


@pytest.mark.asyncio
async def test_lists_active_incidents_with_the_asset_name(client, db_session, auth_headers):
    hardware = Hardware(name="flappy-01")
    db_session.add(hardware)
    db_session.commit()
    db_session.add(_incident(hardware.id))
    db_session.commit()

    response = await client.get("/api/v1/intel/flap-incidents", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body[0]["asset_name"] == "flappy-01"
    assert body[0]["transition_count"] == 7
    assert body[0]["is_active"] is True


@pytest.mark.asyncio
async def test_active_false_returns_resolved_incidents(client, db_session, auth_headers):
    hardware = Hardware(name="settled-01")
    db_session.add(hardware)
    db_session.commit()
    db_session.add(_incident(hardware.id, active=False))
    db_session.commit()

    active = (
        await client.get("/api/v1/intel/flap-incidents?active=true", headers=auth_headers)
    ).json()
    resolved = (
        await client.get("/api/v1/intel/flap-incidents?active=false", headers=auth_headers)
    ).json()

    assert all(row["is_active"] for row in active)
    assert any(row["asset_name"] == "settled-01" for row in resolved)


@pytest.mark.asyncio
async def test_a_deleted_asset_yields_a_null_name_not_a_failure(client, db_session, auth_headers):
    db_session.add(_incident(999_999))
    db_session.commit()

    response = await client.get("/api/v1/intel/flap-incidents", headers=auth_headers)

    assert response.status_code == 200
    assert any(row["asset_name"] is None for row in response.json())
