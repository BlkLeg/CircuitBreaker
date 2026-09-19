"""API tests for GET /telemetry/batch — the batch telemetry endpoint (H5).

The map's fallback poll issues one HTTP request per node against a
per-client budget shared across all nodes; at >=8 nodes that blows the
"telemetry" rate limit. This endpoint lets the frontend fetch N nodes'
telemetry in one request instead. See app/api/telemetry.py for the route.
"""

from __future__ import annotations

import pytest

from app.api import telemetry as telemetry_api

_BATCH_PATH = "/api/v1/hardware/telemetry/batch"


def _single_url(hardware_id: int) -> str:
    return f"/api/v1/hardware/{hardware_id}/telemetry"


@pytest.mark.asyncio
async def test_batch_returns_each_id_in_the_single_node_response_shape(
    client, auth_headers, factories
):
    """A batch of valid ids returns each one, matching the single-node schema."""
    hw1 = factories.hardware()
    hw2 = factories.hardware()

    single_resp = await client.get(_single_url(hw1.id), headers=auth_headers)
    assert single_resp.status_code == 200, single_resp.text
    single_keys = set(single_resp.json().keys())

    batch_resp = await client.get(
        _BATCH_PATH,
        params={"hardware_ids": f"{hw1.id},{hw2.id}"},
        headers=auth_headers,
    )

    assert batch_resp.status_code == 200, batch_resp.text
    body = batch_resp.json()
    assert set(body.keys()) == {str(hw1.id), str(hw2.id)}
    for entry in body.values():
        # Same TelemetryResponse shape as the single-node endpoint — one
        # parser on the frontend, not two.
        assert set(entry.keys()) == single_keys
    assert body[str(hw1.id)]["hardware_id"] == hw1.id
    assert body[str(hw2.id)]["hardware_id"] == hw2.id
    assert body[str(hw1.id)]["status"] == "unconfigured"


@pytest.mark.asyncio
async def test_batch_omits_an_id_the_caller_is_not_authorized_for(
    client, auth_headers, factories, monkeypatch
):
    """The privilege-escalation guard.

    `_visible_hardware_ids` is the batch endpoint's per-id authorization
    boundary (see its docstring in app/api/telemetry.py) — the same check
    (existence) the single-node route performs on its own `hardware_id`
    before returning data. Patch it to deny one id that genuinely EXISTS,
    simulating a caller who may not see it, and confirm the response omits
    exactly that id — with no marker distinguishing "forbidden" from
    "absent" — while the other requested id still comes back.
    """
    visible_hw = factories.hardware()
    forbidden_hw = factories.hardware()

    real_check = telemetry_api._visible_hardware_ids

    def _deny_forbidden_hw(db, hardware_ids):
        allowed = real_check(db, hardware_ids)
        allowed.discard(forbidden_hw.id)
        return allowed

    monkeypatch.setattr(telemetry_api, "_visible_hardware_ids", _deny_forbidden_hw)

    resp = await client.get(
        _BATCH_PATH,
        params={"hardware_ids": f"{visible_hw.id},{forbidden_hw.id}"},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert str(visible_hw.id) in body
    assert str(forbidden_hw.id) not in body
    assert len(body) == 1


@pytest.mark.asyncio
async def test_batch_omits_a_nonexistent_id_instead_of_500ing(client, auth_headers, factories):
    """A nonexistent id is dropped from the mapping, not a 500 for the whole batch."""
    real_hw = factories.hardware()
    nonexistent_id = real_hw.id + 999_000

    resp = await client.get(
        _BATCH_PATH,
        params={"hardware_ids": f"{real_hw.id},{nonexistent_id}"},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert str(real_hw.id) in body
    assert str(nonexistent_id) not in body
    assert len(body) == 1


@pytest.mark.asyncio
async def test_batch_over_cap_is_400_with_detail(client, auth_headers):
    """More ids than the cap is a 400, not a partial/best-effort response."""
    ids = ",".join(str(i) for i in range(1, telemetry_api._TELEMETRY_BATCH_MAX_IDS + 2))

    resp = await client.get(_BATCH_PATH, params={"hardware_ids": ids}, headers=auth_headers)

    assert resp.status_code == 400, resp.text
    assert "detail" in resp.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_ids", ["", "   ", "abc", "1,,2", "1, two, 3"])
async def test_batch_malformed_hardware_ids_is_400_not_500(client, auth_headers, raw_ids):
    """Empty/malformed hardware_ids is a clean 400, never a 500 or a silent empty result."""
    resp = await client.get(_BATCH_PATH, params={"hardware_ids": raw_ids}, headers=auth_headers)

    assert resp.status_code == 400, resp.text
    assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_batch_missing_hardware_ids_param_is_422(client, auth_headers):
    """No hardware_ids at all is FastAPI's own required-query-param 422, not a 500."""
    resp = await client.get(_BATCH_PATH, headers=auth_headers)

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_batch_has_its_own_limit_that_does_not_affect_the_single_node_budget(
    client, auth_headers, factories
):
    """Exhausting telemetry_batch's budget must not touch telemetry's own budget."""
    hw = factories.hardware()

    for i in range(15):
        resp = await client.get(
            _BATCH_PATH, params={"hardware_ids": str(hw.id)}, headers=auth_headers
        )
        assert resp.status_code == 200, f"request {i}: {resp.text}"

    exhausted = await client.get(
        _BATCH_PATH, params={"hardware_ids": str(hw.id)}, headers=auth_headers
    )
    assert exhausted.status_code == 429, exhausted.text

    single = await client.get(_single_url(hw.id), headers=auth_headers)
    assert single.status_code == 200, (
        "single-node telemetry endpoint must keep its own budget even after the "
        f"batch endpoint's limit is exhausted: {single.text}"
    )
