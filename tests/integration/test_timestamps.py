"""Feature 4 — Real Timestamps tests.

Tests cover the app.core.time module (unit) and timestamp behaviour in log responses (integration).

The integration cases take ``auth_headers``: cd1724ff withdrew the open first-run
admin sentinel, so both the /hardware write that produces a log and the /logs read
that inspects it answer 401 until an admin exists and authenticates.
"""
from datetime import UTC, datetime, timedelta


from app.core.time import elapsed_seconds, utcnow, utcnow_iso

# ── Unit tests for app.core.time ──────────────────────────────────────────────

def test_utcnow_is_timezone_aware():
    dt = utcnow()
    assert dt.tzinfo is not None
    assert dt.tzinfo == UTC


def test_utcnow_iso_format():
    result = utcnow_iso()
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None
    assert "+00:00" in result


def test_elapsed_seconds_valid_input():
    past = (utcnow() - timedelta(seconds=60)).isoformat()
    result = elapsed_seconds(past)
    assert result is not None
    assert 55 < result < 65


def test_elapsed_seconds_unparseable_input():
    assert elapsed_seconds("just now") is None
    assert elapsed_seconds(None) is None
    assert elapsed_seconds("") is None


# ── Integration: log entries have UTC timestamps ───────────────────────────────

def test_log_entry_has_utc_timestamp(client, auth_headers):
    client.post("/api/v1/hardware", json={"name": "test-hw"}, headers=auth_headers)
    logs = client.get("/api/v1/logs", headers=auth_headers).json()["logs"]
    assert len(logs) > 0
    entry = logs[0]
    assert entry.get("created_at_utc") is not None
    parsed = datetime.fromisoformat(entry["created_at_utc"])
    assert parsed.tzinfo is not None
    assert "+00:00" in entry["created_at_utc"]


def test_log_entry_never_contains_just_now(client, auth_headers):
    for i in range(5):
        client.post("/api/v1/hardware", json={"name": f"hw-{i}"}, headers=auth_headers)

    logs = client.get("/api/v1/logs", headers=auth_headers).json()["logs"]
    for entry in logs:
        assert entry.get("created_at_utc") != "just now", \
            f"Log entry {entry['id']} has created_at_utc='just now'"


def test_log_response_includes_elapsed_seconds(client, auth_headers):
    client.post("/api/v1/hardware", json={"name": "test-hw"}, headers=auth_headers)
    logs = client.get("/api/v1/logs", headers=auth_headers).json()["logs"]
    assert len(logs) > 0
    entry = logs[0]
    assert entry.get("elapsed_seconds") is not None
    assert entry["elapsed_seconds"] >= 0


# ── Backfill behaviour ────────────────────────────────────────────────────────

