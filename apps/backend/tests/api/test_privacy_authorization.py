"""Role enforcement for the privacy surface (`api/windscribe.py`).

The router was mounted with bare `require_auth` and no route declared a role, so
`POST`/`DELETE /privacy-findings/ignore` — suppressing a security finding — was
reachable by any authenticated user, viewers included. Reads are deliberately open
to every authenticated user; only the writes are governance.
"""

from __future__ import annotations

import pytest

from app.db.models import PrivacyFindingIgnore


@pytest.mark.asyncio
async def test_viewer_may_read_the_privacy_score(client, viewer_headers):
    resp = await client.get("/api/v1/network/privacy-score", headers=viewer_headers)

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_viewer_may_read_the_ignore_list(client, viewer_headers):
    resp = await client.get("/api/v1/privacy-findings/ignores", headers=viewer_headers)

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_ignore_a_finding(client, viewer_headers, db_session):
    resp = await client.post(
        "/api/v1/privacy-findings/ignore",
        json={"rule_id": "telnet_open", "hardware_id": None},
        headers=viewer_headers,
    )

    assert resp.status_code == 403
    assert db_session.query(PrivacyFindingIgnore).count() == 0


@pytest.mark.asyncio
async def test_viewer_cannot_unignore_a_finding(client, viewer_headers):
    resp = await client.delete(
        "/api/v1/privacy-findings/ignore?rule_id=telnet_open", headers=viewer_headers
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_ignore_records_the_admin_id_not_the_user_object(
    client, auth_headers, admin_user, db_session
):
    """`created_by` is an int FK. `require_role` returns a User, `require_auth` returned
    an id — swapping the dependency without swapping the assignment stores the wrong thing."""
    resp = await client.post(
        "/api/v1/privacy-findings/ignore",
        json={"rule_id": "telnet_open", "hardware_id": None},
        headers=auth_headers,
    )

    assert resp.status_code == 201
    row = db_session.query(PrivacyFindingIgnore).one()
    assert row.created_by == admin_user.id


@pytest.mark.asyncio
async def test_admin_can_unignore(client, auth_headers, db_session):
    await client.post(
        "/api/v1/privacy-findings/ignore",
        json={"rule_id": "telnet_open", "hardware_id": None},
        headers=auth_headers,
    )

    resp = await client.delete(
        "/api/v1/privacy-findings/ignore?rule_id=telnet_open", headers=auth_headers
    )

    assert resp.status_code == 204
    assert db_session.query(PrivacyFindingIgnore).count() == 0
