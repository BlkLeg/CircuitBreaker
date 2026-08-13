from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_clear_lab_requires_confirmation_headers(client, auth_headers):
    resp = await client.post("/api/v1/admin/clear-lab", headers=auth_headers)
    assert resp.status_code == 428
    body = resp.json()
    assert "x-cb-confirmation: CLEAR_LAB" in body["detail"]["required"]


@pytest.mark.asyncio
async def test_import_with_wipe_requires_backup_confirmation(client, auth_headers):
    resp = await client.post(
        "/api/v1/admin/import",
        json={"wipe_before_import": True, "data": {"version": 2}},
        headers={
            **auth_headers,
            "x-cb-confirmation": "RESTORE_WITH_WIPE",
            "idempotency-key": "sec6-import-restore",
        },
    )
    assert resp.status_code == 428
    assert "x-cb-backup-verified: true" in resp.json()["detail"]["required"]


@pytest.mark.asyncio
async def test_clear_lab_with_confirmation_is_audited(client, auth_headers, db_session):
    from app.db.models import Log

    resp = await client.post(
        "/api/v1/admin/clear-lab",
        headers={
            **auth_headers,
            "x-cb-confirmation": "CLEAR_LAB",
            "idempotency-key": "sec6-clear-lab",
            "x-cb-backup-verified": "true",
        },
    )
    assert resp.status_code == 200, resp.text
    assert (db_session.query(Log).filter(Log.action == "clear_lab_completed").count()) == 1


# ── SEC-17: clearing the audit log is itself a destructive action ─────────────
# The wipe destroys the evidence every other guardrail writes, so it carries the
# same confirmation contract and must survive as the new chain genesis.


@pytest.mark.asyncio
async def test_clear_audit_log_requires_confirmation_headers(client, auth_headers):
    resp = await client.delete("/api/v1/logs", headers=auth_headers)

    assert resp.status_code == 428
    assert "x-cb-confirmation: CLEAR_AUDIT_LOG" in resp.json()["detail"]["required"]


@pytest.mark.asyncio
async def test_clear_audit_log_requires_verified_backup(client, auth_headers):
    resp = await client.delete(
        "/api/v1/logs",
        headers={
            **auth_headers,
            "x-cb-confirmation": "CLEAR_AUDIT_LOG",
            "idempotency-key": "sec17-clear-audit-log",
        },
    )

    assert resp.status_code == 428
    assert "x-cb-backup-verified: true" in resp.json()["detail"]["required"]


@pytest.mark.asyncio
async def test_cleared_audit_log_still_records_who_cleared_it(
    client, auth_headers, db_session
) -> None:
    from app.db.models import Log

    resp = await client.delete(
        "/api/v1/logs",
        headers={
            **auth_headers,
            "x-cb-confirmation": "CLEAR_AUDIT_LOG",
            "idempotency-key": "sec17-clear-audit-log",
            "x-cb-backup-verified": "true",
        },
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    survivors = db_session.query(Log).all()
    # The wipe removes everything that came before it — including its own
    # authorization record — so the completion event is what remains.
    assert [row.action for row in survivors] == ["clear_audit_log_completed"]
    assert survivors[0].actor_name is not None
