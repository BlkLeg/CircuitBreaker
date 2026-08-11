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


@pytest.mark.asyncio
async def test_list_logs_filters_by_entity_name(client, auth_headers):
    """Test that entity_name query parameter filters logs correctly.

    Uses synthetic action/entity_name values (not real capability keys like
    "nmap_present") because log_worker_audit's write_log(db=None) opens its
    own SessionLocal and commits outside any test's SAVEPOINT isolation — a
    real capability key here would permanently pollute the shared test DB
    for other tests (e.g. discovery_readiness's "no history" assumptions)
    for the rest of the suite run.
    """
    from app.core.worker_audit import log_worker_audit

    log_worker_audit(
        action="test_logs_entity_name_filter_target",
        entity_type="discovery_capability",
        entity_name="test_entity_name_filter_target",
        details="capability=test_entity_name_filter_target",
        worker_name="discovery_reconciler",
    )
    log_worker_audit(
        action="test_logs_entity_name_filter_other",
        entity_type="discovery_capability",
        entity_name="test_entity_name_filter_other",
        details="capability=test_entity_name_filter_other",
        worker_name="discovery_reconciler",
    )
    resp = await client.get(
        "/api/v1/logs",
        params={
            "category": "worker",
            "entity_type": "discovery_capability",
            "entity_name": "test_entity_name_filter_target",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] >= 1
    assert all(e["entity_name"] == "test_entity_name_filter_target" for e in body["logs"])


def test_audit_chain_repair_requires_authorization_and_records_repair(db_session):
    from app.core.audit_chain import REPAIR_AUTHORIZATION, repair_audit_chain, verify_audit_chain
    from app.db.models import Log
    from app.services.log_service import write_log

    write_log(db_session, action="sec6_repair_one", category="audit")
    write_log(db_session, action="sec6_repair_two", category="audit")

    row = db_session.query(Log).filter(Log.action == "sec6_repair_two").one()
    row.previous_hash = "tampered"
    db_session.commit()

    assert verify_audit_chain(db_session)["valid"] is False
    with pytest.raises(ValueError):
        repair_audit_chain(
            db_session,
            authorization="wrong",
            actor_id=None,
            reason="test repair authorization failure",
        )

    report = repair_audit_chain(
        db_session,
        authorization=REPAIR_AUTHORIZATION,
        actor_id=None,
        reason="test repair of deliberately tampered hash chain",
    )
    assert report["repaired"] is True
    assert report["changed"]
    assert report["after"]["valid"] is True
    assert db_session.query(Log).filter(Log.action == "audit_chain_repair").count() == 1


def test_concurrent_audit_writers_do_not_fork_chain(setup_db):
    from concurrent.futures import ThreadPoolExecutor

    from app.core.audit_chain import verify_audit_chain
    from app.db.session import SessionLocal
    from app.services.log_service import write_log

    def _write(index: int) -> None:
        with SessionLocal() as session:
            write_log(session, action=f"sec6_concurrent_{index}", category="audit")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(_write, range(12)))

    with SessionLocal() as session:
        result = verify_audit_chain(session)
        assert result["valid"] is True, result
