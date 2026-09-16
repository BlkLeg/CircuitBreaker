"""Route-level contract for the inventory transfer API (plan 02, T11).

Auth gate on every endpoint, summary counts, the preview→apply→result round
trip, idempotency behavior, and the audit event an applied import owes.
"""

from __future__ import annotations

import pytest

BASE = "/api/v1/inventory-transfer"


def _document(name="imported-host"):
    return {
        "format": "circuitbreaker.inventory",
        "version": 1,
        "exported_at": "2026-09-10T00:00:00+00:00",
        "manifest": {"included": [], "excluded": []},
        "entities": {"hardware": [{"id": 1, "name": name}]},
        "relationships": {},
    }


async def _preview(client, headers, document=None):
    resp = await client.post(
        f"{BASE}/preview",
        headers=headers,
        json={"document": document or _document(), "resolutions": []},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_every_endpoint_requires_admin(client, viewer_headers):
    resp = await client.get(f"{BASE}/summary", headers=viewer_headers)
    assert resp.status_code == 403
    resp = await client.get(f"{BASE}/export", headers=viewer_headers)
    assert resp.status_code == 403
    resp = await client.post(
        f"{BASE}/preview",
        headers=viewer_headers,
        json={"document": _document(), "resolutions": []},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_summary_counts_portable_kinds(client, auth_headers, db_session, factories):
    factories.hardware(name="pve-01")
    factories.service(name="grafana")

    resp = await client.get(f"{BASE}/summary", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "circuitbreaker.inventory"
    assert body["version"] == 1
    assert body["assets"]["hardware"] == 1
    assert body["assets"]["services"] == 1
    assert len(body["assets"]) == 7
    assert body["assets_total"] == sum(body["assets"].values())
    assert body["relationships_total"] == sum(body["relationships"].values())


@pytest.mark.asyncio
async def test_preview_apply_and_result_round_trip(client, auth_headers, db_session):
    preview = await _preview(client, auth_headers)
    assert preview["can_apply"] is True
    assert preview["creates"]["hardware"] == 1
    assert preview["warnings"]

    apply_headers = {**auth_headers, "Idempotency-Key": "api-flow-key-1"}
    resp = await client.post(
        f"{BASE}/plans/{preview['plan_id']}/apply",
        headers=apply_headers,
        json={"plan_digest": preview["plan_digest"]},
    )
    assert resp.status_code == 200, resp.text
    applied = resp.json()
    assert applied["state"] == "completed"
    assert applied["created"]["hardware"] == 1

    resp = await client.get(f"{BASE}/operations/{applied['operation_id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["operation_id"] == applied["operation_id"]

    replay = await client.post(
        f"{BASE}/plans/{preview['plan_id']}/apply",
        headers=apply_headers,
        json={"plan_digest": preview["plan_digest"]},
    )
    assert replay.status_code == 200
    assert replay.json()["operation_id"] == applied["operation_id"]


@pytest.mark.asyncio
async def test_apply_rejects_a_changed_digest(client, auth_headers):
    preview = await _preview(client, auth_headers)

    resp = await client.post(
        f"{BASE}/plans/{preview['plan_id']}/apply",
        headers={**auth_headers, "Idempotency-Key": "changed-digest-key"},
        json={"plan_digest": "0" * 64},
    )

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "preview_changed"


@pytest.mark.asyncio
async def test_a_reused_idempotency_key_cannot_apply_another_transfer(client, auth_headers):
    first = await _preview(client, auth_headers, _document("first-host"))
    resp = await client.post(
        f"{BASE}/plans/{first['plan_id']}/apply",
        headers={**auth_headers, "Idempotency-Key": "one-key-for-one-transfer"},
        json={"plan_digest": first["plan_digest"]},
    )
    assert resp.status_code == 200

    second = await _preview(client, auth_headers, _document("second-host"))
    resp = await client.post(
        f"{BASE}/plans/{second['plan_id']}/apply",
        headers={**auth_headers, "Idempotency-Key": "one-key-for-one-transfer"},
        json={"plan_digest": second["plan_digest"]},
    )

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "idempotency_conflict"


@pytest.mark.asyncio
async def test_preview_reports_unsupported_documents_as_a_domain_error(client, auth_headers):
    """Domain validation is the app's own 400, not pydantic's 422."""
    resp = await client.post(
        f"{BASE}/preview",
        headers=auth_headers,
        json={"document": {"version": 99}, "resolutions": []},
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_an_applied_import_writes_an_audit_event(
    client, auth_headers, db_session, monkeypatch
):
    calls: list[dict] = []

    def spy(db, request, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("app.api.inventory_transfer.log_audit", spy)

    preview = await _preview(client, auth_headers)
    resp = await client.post(
        f"{BASE}/plans/{preview['plan_id']}/apply",
        headers={**auth_headers, "Idempotency-Key": "audited-transfer-key"},
        json={"plan_digest": preview["plan_digest"]},
    )
    assert resp.status_code == 200

    applied = [c for c in calls if c.get("action") == "inventory_import_applied"]
    assert len(applied) == 1
    assert "operation=" in applied[0]["details"]
    assert "created=1" in applied[0]["details"]
