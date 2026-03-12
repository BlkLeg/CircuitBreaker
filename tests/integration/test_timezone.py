"""Feature 5 — Timezone setting tests.

Settings PUT is protected by require_write_auth. Tests run against a fresh DB
before OOBE, so calls succeed without a configured jwt_secret.
"""


# ── Timezones endpoint ────────────────────────────────────────────────────────

def test_timezones_endpoint_returns_sorted_list(client):
    resp = client.get("/api/v1/timezones")
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

def test_settings_update_valid_timezone(client):
    resp = client.put("/api/v1/settings", json={"timezone": "America/Denver"})
    assert resp.status_code == 200

    get_resp = client.get("/api/v1/settings")
    assert get_resp.json()["timezone"] == "America/Denver"


def test_settings_update_invalid_timezone(client):
    resp = client.put("/api/v1/settings", json={"timezone": "Mars/Olympus"})
    assert resp.status_code == 422
    detail = str(resp.json())
    assert "timezone" in detail.lower() or "valid" in detail.lower() or "iana" in detail.lower()


def test_settings_update_empty_timezone(client):
    resp = client.put("/api/v1/settings", json={"timezone": ""})
    assert resp.status_code == 422


# ── Audit log on timezone change ──────────────────────────────────────────────

def test_timezone_log_on_change(client):
    client.put("/api/v1/settings", json={"timezone": "America/Denver"})

    logs = client.get("/api/v1/logs").json()["logs"]
    entry = next(
        (log for log in logs if log.get("entity_type") == "settings" and log.get("action") == "update_settings"),
        None,
    )
    assert entry is not None, "Expected 'update_settings' settings log after timezone change"

    # Diff should reference timezone
    if entry.get("diff"):
        import json
        diff = json.loads(entry["diff"]) if isinstance(entry["diff"], str) else entry["diff"]
        before = diff.get("before") or {}
        after = diff.get("after") or {}
        assert "timezone" in before or "timezone" in after
