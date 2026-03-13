"""Tests for telemetry config write and secret-masking in hardware GET responses."""

import pytest

_TELEMETRY_BASE_CONFIG = {
    "profile": "snmp_generic",
    "host": "192.168.1.1",
    "port": 161,
    "protocol": "snmp",
    "snmp_version": "v2c",
    "poll_interval_seconds": 60,
    "enabled": True,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_hardware(client, auth_headers: dict) -> int:
    resp = await client.post(
        "/api/v1/hardware",
        json={"name": "telemetry-test-node"},
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201), f"Hardware creation failed: {resp.text}"
    return resp.json()["id"]


async def _write_telemetry_config(client, auth_headers: dict, hw_id: int, config: dict) -> dict:
    resp = await client.post(
        f"/api/v1/hardware/{hw_id}/telemetry/config",
        json=config,
        headers=auth_headers,
    )
    return resp


async def _get_hardware(client, auth_headers: dict, hw_id: int) -> dict:
    resp = await client.get(
        f"/api/v1/hardware/{hw_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"Hardware GET failed: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_telemetry_config_returns_message(client, auth_headers, factories):
    """POST to telemetry/config should return a success message and hardware_id."""
    hw = factories.hardware()
    config = {**_TELEMETRY_BASE_CONFIG, "snmp_community": "public"}

    resp = await _write_telemetry_config(client, auth_headers, hw.id, config)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "message" in body, f"Response missing 'message': {body}"
    assert body.get("hardware_id") == hw.id


@pytest.mark.asyncio
async def test_snmp_community_masked_in_hardware_get(client, auth_headers, factories):
    """After writing snmp_community, a hardware GET must not expose the plaintext."""
    hw = factories.hardware()
    secret_community = "my-secret-community"

    config = {**_TELEMETRY_BASE_CONFIG, "snmp_community": secret_community}
    resp = await _write_telemetry_config(client, auth_headers, hw.id, config)
    assert resp.status_code == 200, f"Config write failed: {resp.text}"

    # Re-fetch as raw text for the GET response
    get_resp = await client.get(f"/api/v1/hardware/{hw.id}", headers=auth_headers)
    assert get_resp.status_code == 200

    response_text = get_resp.text
    assert secret_community not in response_text, (
        f"Plaintext snmp_community '{secret_community}' found in GET response body"
    )
    assert "****" in response_text, "Expected masked value '****' not found in GET response body"


@pytest.mark.asyncio
async def test_password_masked_in_hardware_get(client, auth_headers, factories):
    """After writing a telemetry password, a hardware GET must not expose the plaintext."""
    hw = factories.hardware()
    secret_password = "my-secret-pass"

    config = {
        **_TELEMETRY_BASE_CONFIG,
        "profile": "idrac9",
        "protocol": "snmp",
        "username": "root",
        "password": secret_password,
        "snmp_community": "public",
    }
    resp = await _write_telemetry_config(client, auth_headers, hw.id, config)
    assert resp.status_code == 200, f"Config write failed: {resp.text}"

    get_resp = await client.get(f"/api/v1/hardware/{hw.id}", headers=auth_headers)
    assert get_resp.status_code == 200

    response_text = get_resp.text
    assert secret_password not in response_text, (
        f"Plaintext password '{secret_password}' found in GET response body"
    )


@pytest.mark.asyncio
async def test_telemetry_config_returns_masked_stars(client, auth_headers, factories):
    """When both snmp_community and password are set, GET hardware must show '****'
    for each masked field."""
    hw = factories.hardware()

    config = {
        **_TELEMETRY_BASE_CONFIG,
        "snmp_community": "community-string-xyz",
        "password": "pass-xyz",
        "username": "admin",
    }
    resp = await _write_telemetry_config(client, auth_headers, hw.id, config)
    assert resp.status_code == 200, f"Config write failed: {resp.text}"

    get_resp = await client.get(f"/api/v1/hardware/{hw.id}", headers=auth_headers)
    assert get_resp.status_code == 200

    body = get_resp.json()
    tc = body.get("telemetry_config")
    assert tc is not None, "telemetry_config not present in hardware GET response"

    assert tc.get("snmp_community") == "****", (
        f"Expected snmp_community='****', got {tc.get('snmp_community')!r}"
    )
    assert tc.get("password") == "****", f"Expected password='****', got {tc.get('password')!r}"


@pytest.mark.asyncio
async def test_telemetry_config_write_requires_auth(client, factories):
    """Writing telemetry config without auth must return 401."""
    hw = factories.hardware()
    config = {**_TELEMETRY_BASE_CONFIG, "snmp_community": "public"}

    resp = await client.post(
        f"/api/v1/hardware/{hw.id}/telemetry/config",
        json=config,
    )
    assert resp.status_code == 401, (
        f"Expected 401 without auth, got {resp.status_code}: {resp.text}"
    )
