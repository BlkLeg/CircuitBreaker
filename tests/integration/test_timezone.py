"""Feature 5 — Timezone setting tests.

cd1724ff withdrew the open first-run admin sentinel, so an un-bootstrapped
instance no longer acts as an admin: everything here except the settings read the
setup wizard renders from answers 401 until an admin exists and authenticates.
``auth_headers`` bootstraps and logs in, which is the state these endpoints are
actually exercised in.
"""


# ── Timezones endpoint ────────────────────────────────────────────────────────

def test_timezones_endpoint_returns_sorted_list(client, auth_headers):
    resp = client.get("/api/v1/timezones", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    tzs = data["timezones"]
    assert isinstance(tzs, list)
    assert len(tzs) > 400
    assert tzs == sorted(tzs)
    assert "UTC" in tzs
    assert "America/Denver" in tzs


# ── Settings default ──────────────────────────────────────────────────────────

def test_settings_default_timezone_is_utc(client):
    resp = client.get("/api/v1/settings")
    assert resp.status_code == 200
    assert resp.json()["timezone"] == "UTC"


# ── Settings update ───────────────────────────────────────────────────────────

def test_settings_update_valid_timezone(client, auth_headers):
    resp = client.put("/api/v1/settings", json={"timezone": "America/Denver"}, headers=auth_headers)
    assert resp.status_code == 200

    get_resp = client.get("/api/v1/settings", headers=auth_headers)
    assert get_resp.json()["timezone"] == "America/Denver"


def test_settings_update_invalid_timezone(client, auth_headers):
    resp = client.put("/api/v1/settings", json={"timezone": "Mars/Olympus"}, headers=auth_headers)
    assert resp.status_code == 422
    detail = str(resp.json())
    assert "timezone" in detail.lower() or "valid" in detail.lower() or "iana" in detail.lower()


def test_settings_update_empty_timezone(client, auth_headers):
    resp = client.put("/api/v1/settings", json={"timezone": ""}, headers=auth_headers)
    assert resp.status_code == 422


# ── Audit log on timezone change ──────────────────────────────────────────────

def test_timezone_log_on_change(client, auth_headers):
    client.put("/api/v1/settings", json={"timezone": "America/Denver"}, headers=auth_headers)

    logs = client.get("/api/v1/logs", headers=auth_headers).json()["logs"]
    entry = next(
        (log for log in logs if log.get("entity_type") == "settings" and log.get("action") == "settings_update"),
        None,
    )
    assert entry is not None, "Expected 'settings_update' settings log after timezone change"

    # Diff should reference timezone
    if entry.get("diff"):
        import json
        diff = json.loads(entry["diff"]) if isinstance(entry["diff"], str) else entry["diff"]
        before = diff.get("before") or {}
        after = diff.get("after") or {}
        assert "timezone" in before or "timezone" in after
