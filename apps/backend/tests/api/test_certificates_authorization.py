"""`GET /certificates` carried no role dependency while every other route in
`api/certificates.py` required admin, so a viewer could list every certificate."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_viewer_cannot_list_certificates(client, viewer_headers):
    resp = await client.get("/api/v1/certificates", headers=viewer_headers)

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_certificates(client, auth_headers):
    resp = await client.get("/api/v1/certificates", headers=auth_headers)

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
