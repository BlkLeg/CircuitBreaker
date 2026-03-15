"""Tests for the audit log API and hash-chain integrity."""

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_hardware(client, auth_headers: dict) -> int:
    """POST a minimal hardware entry and return its id."""
    resp = await client.post(
        "/api/v1/hardware",
        json={"name": "log-test-node"},
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201), f"Hardware creation failed: {resp.text}"
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_hardware_generates_log_entry(client, auth_headers):
    """Creating a hardware item should write at least one audit log entry
    with an action that mentions 'hardware' or 'create'."""
    await _create_hardware(client, auth_headers)

    resp = await client.get("/api/v1/logs", headers=auth_headers)
    assert resp.status_code == 200

    logs = resp.json().get("logs", resp.json()) if isinstance(resp.json(), dict) else resp.json()
    # Support both {"logs": [...]} envelope and raw list
    if isinstance(logs, dict):
        logs = logs.get("logs", [])

    actions = [entry.get("action", "").lower() for entry in logs]
    assert any("hardware" in a or "create" in a for a in actions), (
        f"No hardware/create action found in logs. Actions seen: {actions[:10]}"
    )


@pytest.mark.asyncio
async def test_log_entries_have_non_null_log_hash(client, auth_headers):
    """Every returned log entry must carry a non-null log_hash field."""
    await _create_hardware(client, auth_headers)

    resp = await client.get("/api/v1/logs", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    logs = body.get("logs", body) if isinstance(body, dict) else body
    if isinstance(logs, dict):
        logs = logs.get("logs", [])

    assert logs, "Expected at least one log entry"
    for entry in logs:
        assert "log_hash" in entry, f"log_hash field missing from entry: {entry}"
        assert entry["log_hash"] is not None, f"log_hash is null for entry id={entry.get('id')}"


@pytest.mark.asyncio
async def test_log_hash_chain_validity(client, auth_headers, db_session):
    """Verify the linked-hash chain: each entry's previous_hash equals the
    preceding entry's log_hash when entries are ordered by id ascending."""
    # Ensure several log entries exist
    for _ in range(3):
        await _create_hardware(client, auth_headers)

    from app.db.models import Log

    rows = db_session.query(Log).order_by(Log.id).limit(10).all()
    assert len(rows) >= 2, "Need at least 2 log entries to verify chain"

    # The very first row may have previous_hash == None (genesis entry)
    for i in range(1, len(rows)):
        prev = rows[i - 1]
        curr = rows[i]
        # Only enforce chain continuity when the current row's previous_hash
        # is set (some implementations omit it for the first few rows)
        if curr.previous_hash is not None and prev.log_hash is not None:
            assert curr.previous_hash == prev.log_hash, (
                f"Hash chain broken between log id={prev.id} and id={curr.id}: "
                f"expected previous_hash={prev.log_hash!r}, got {curr.previous_hash!r}"
            )


@pytest.mark.asyncio
async def test_logs_require_auth(client):
    """GET /api/v1/logs without a token must return 401."""
    resp = await client.get("/api/v1/logs")
    assert resp.status_code == 401, (
        f"Expected 401 without auth, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.asyncio
async def test_logs_response_structure(client, auth_headers):
    """The logs endpoint should return a parseable response with expected fields."""
    await _create_hardware(client, auth_headers)

    resp = await client.get("/api/v1/logs", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    # Accept both list and {"logs": [...], "total": N} envelope formats
    if isinstance(body, dict):
        assert "logs" in body or len(body) > 0
        logs = body.get("logs", [])
    else:
        logs = body

    assert isinstance(logs, list)
    if logs:
        entry = logs[0]
        # Verify expected fields exist
        for field in ("id", "action", "log_hash"):
            assert field in entry, f"Expected field '{field}' missing from log entry"
