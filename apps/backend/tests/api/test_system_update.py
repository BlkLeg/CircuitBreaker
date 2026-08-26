"""The update endpoint: admin-only, cache-only, honest about its status."""

from app.core import update_check


async def test_requires_admin(client, viewer_headers):
    resp = await client.get("/api/v1/system/update", headers=viewer_headers)
    assert resp.status_code == 403


async def test_rejects_anonymous(client):
    resp = await client.get("/api/v1/system/update")
    assert resp.status_code in (401, 403)


async def test_reports_an_available_update(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        update_check,
        "_state",
        update_check.UpdateState(
            status="ok",
            current="1.0.0-rc.2",
            available="1.0.0-rc.4",
            channel="prerelease",
            checked_at="2026-08-25T21:00:00+00:00",
        ),
    )
    resp = await client.get("/api/v1/system/update", headers=auth_headers)
    body = resp.json()
    assert body["update_available"] is True
    assert body["available"] == "1.0.0-rc.4"
    assert body["channel"] == "prerelease"
    assert body["upgrade_command"].strip()
    assert body["release_url"].endswith("/v1.0.0-rc.4")


async def test_up_to_date_is_not_an_update(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        update_check,
        "_state",
        update_check.UpdateState(
            status="ok",
            current="1.0.0-rc.4",
            available=None,
            channel="prerelease",
            checked_at="2026-08-25T21:00:00+00:00",
        ),
    )
    resp = await client.get("/api/v1/system/update", headers=auth_headers)
    body = resp.json()
    assert body["update_available"] is False
    assert body["release_url"] is None


async def test_disabled_is_not_reported_as_up_to_date(client, auth_headers, monkeypatch):
    """An operator who turned the check off must not read 'you are current'."""
    monkeypatch.setattr(
        update_check,
        "_state",
        update_check.UpdateState(status="disabled", current="1.0.0-rc.2"),
    )
    resp = await client.get("/api/v1/system/update", headers=auth_headers)
    body = resp.json()
    assert body["status"] == "disabled"
    assert body["update_available"] is False


async def test_serves_cache_without_touching_the_network(client, auth_headers, monkeypatch):
    def _boom():
        raise AssertionError("the endpoint must never fetch")

    monkeypatch.setattr(update_check, "_transport", _boom)
    monkeypatch.setattr(update_check, "_state", update_check.UpdateState(status="never_checked"))
    resp = await client.get("/api/v1/system/update", headers=auth_headers)
    assert resp.status_code == 200
