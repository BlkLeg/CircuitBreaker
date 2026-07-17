import pytest


@pytest.mark.asyncio
async def test_scan_progress_style_defaults_and_round_trips(client, auth_headers):
    resp = await client.get("/api/v1/settings", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["scan_progress_style"] == "circuit"

    resp = await client.put(
        "/api/v1/settings", headers=auth_headers, json={"scan_progress_style": "segmented"}
    )
    assert resp.status_code == 200
    assert resp.json()["scan_progress_style"] == "segmented"

    resp = await client.get("/api/v1/settings", headers=auth_headers)
    assert resp.json()["scan_progress_style"] == "segmented"


@pytest.mark.asyncio
async def test_scan_progress_style_rejects_invalid_value(client, auth_headers):
    resp = await client.put(
        "/api/v1/settings", headers=auth_headers, json={"scan_progress_style": "not_a_style"}
    )
    assert resp.status_code == 422
