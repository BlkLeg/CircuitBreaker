"""Feature 4 — Real Timestamps tests.

Tests cover the app.core.time module (unit) and timestamp behaviour in log responses (integration).
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

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

def test_log_entry_has_utc_timestamp(client):
    client.post("/api/v1/hardware", json={"name": "test-hw"})
    logs = client.get("/api/v1/logs").json()["logs"]
    assert len(logs) > 0
    entry = logs[0]
    assert entry.get("created_at_utc") is not None
    parsed = datetime.fromisoformat(entry["created_at_utc"])
    assert parsed.tzinfo is not None
    assert "+00:00" in entry["created_at_utc"]


def test_log_entry_never_contains_just_now(client):
    for i in range(5):
        client.post("/api/v1/hardware", json={"name": f"hw-{i}"})

    logs = client.get("/api/v1/logs").json()["logs"]
    for entry in logs:
        assert entry.get("created_at_utc") != "just now", \
            f"Log entry {entry['id']} has created_at_utc='just now'"


def test_log_response_includes_elapsed_seconds(client):
    client.post("/api/v1/hardware", json={"name": "test-hw"})
    logs = client.get("/api/v1/logs").json()["logs"]
    assert len(logs) > 0
    entry = logs[0]
    assert entry.get("elapsed_seconds") is not None
    assert entry["elapsed_seconds"] >= 0


# ── Backfill behaviour ────────────────────────────────────────────────────────

def test_backfill_just_now_rows(db):
    """Log rows with an unparseable timestamp get the epoch sentinel UTC timestamp."""
    db.execute(text(
        "INSERT INTO logs (action, category, level, timestamp, created_at_utc)"
        " VALUES ('test', 'system', 'info', 'just now', NULL)"
    ))
    db.commit()

    from app.main import _backfill_log_timestamps
    _backfill_log_timestamps(db)

    row = db.execute(text(
        "SELECT created_at_utc FROM logs WHERE action='test' AND category='system'"
    )).fetchone()
    assert row is not None
    assert row[0] == "1970-01-01T00:00:00+00:00"


def test_backfill_parseable_timestamp_rows(db):
    """Log rows with a parseable timestamp get a valid UTC ISO timestamp."""
    db.execute(text(
        "INSERT INTO logs (action, category, level, timestamp, created_at_utc)"
        " VALUES ('test2', 'system', 'info', '2026-01-15 12:00:00', NULL)"
    ))
    db.commit()

    from app.main import _backfill_log_timestamps
    _backfill_log_timestamps(db)

    row = db.execute(text(
        "SELECT created_at_utc FROM logs WHERE action='test2' AND category='system'"
    )).fetchone()
    assert row is not None
    assert row[0] is not None
    parsed = datetime.fromisoformat(row[0])
    assert parsed.tzinfo is not None
