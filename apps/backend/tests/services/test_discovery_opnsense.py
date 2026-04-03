"""Unit tests for discovery_opnsense.py — merge logic, error contract."""

from __future__ import annotations

import pytest

from app.services.discovery_opnsense import _merge_devices, fetch_opnsense_devices

# ── _merge_devices unit tests ─────────────────────────────────────────────────


def _arp(ip: str, mac: str) -> dict:
    return {"ip": ip, "mac": mac}


def _lease(address: str, mac: str, hostname: str = "", ends: str = "") -> dict:
    return {"address": address, "mac": mac, "hostname": hostname, "ends": ends}


def test_merge_arp_only_entry_is_active():
    """ARP-only entries (no lease) → is_active=True, source=opnsense_arp."""
    devices = _merge_devices(
        leases_data={"rows": []},
        arp_data=[_arp("10.0.0.1", "aa:bb:cc:dd:ee:ff")],
    )
    assert len(devices) == 1
    d = devices[0]
    assert d["ip"] == "10.0.0.1"
    assert d["mac"] == "aa:bb:cc:dd:ee:ff"
    assert d["is_active"] is True
    assert d["source"] == "opnsense_arp"
    assert d["hostname"] is None


def test_merge_lease_enriches_arp_entry():
    """Lease data wins on conflict; matched ARP entry stays is_active=True."""
    devices = _merge_devices(
        leases_data={"rows": [_lease("10.0.0.1", "aa:bb:cc:dd:ee:ff", hostname="router")]},
        arp_data=[_arp("10.0.0.1", "aa:bb:cc:dd:ee:ff")],
    )
    assert len(devices) == 1
    d = devices[0]
    assert d["hostname"] == "router"
    assert d["is_active"] is True
    assert d["source"] == "opnsense_lease"


def test_merge_lease_only_is_inactive():
    """Lease-only entry (not in ARP) → is_active=False."""
    devices = _merge_devices(
        leases_data={"rows": [_lease("10.0.0.2", "11:22:33:44:55:66", hostname="old-phone")]},
        arp_data=[],
    )
    assert len(devices) == 1
    d = devices[0]
    assert d["is_active"] is False
    assert d["source"] == "opnsense_lease"
    assert d["hostname"] == "old-phone"


def test_merge_empty_hostname_normalised_to_none():
    """Empty hostname string from OPNsense → None."""
    devices = _merge_devices(
        leases_data={"rows": [_lease("10.0.0.3", "aa:00:00:00:00:01", hostname="")]},
        arp_data=[],
    )
    assert devices[0]["hostname"] is None


def test_merge_both_arp_and_leases_no_duplicates():
    """3 ARP + 2 leases (overlapping IPs) → 4 unique devices."""
    arp = [
        _arp("10.0.0.1", "aa:bb:cc:00:00:01"),
        _arp("10.0.0.2", "aa:bb:cc:00:00:02"),
        _arp("10.0.0.3", "aa:bb:cc:00:00:03"),
    ]
    leases = {
        "rows": [
            _lease("10.0.0.1", "aa:bb:cc:00:00:01", hostname="router"),
            _lease("10.0.0.4", "aa:bb:cc:00:00:04", hostname="expired"),  # lease-only
        ]
    }
    devices = _merge_devices(leases, arp)
    by_ip = {d["ip"]: d for d in devices}

    assert len(by_ip) == 4
    assert by_ip["10.0.0.1"]["hostname"] == "router"
    assert by_ip["10.0.0.1"]["is_active"] is True
    assert by_ip["10.0.0.2"]["source"] == "opnsense_arp"
    assert by_ip["10.0.0.4"]["is_active"] is False


def test_merge_list_format_arp():
    """ARP data as a plain list (not wrapped in 'rows') is handled."""
    arp = [_arp("192.168.1.1", "de:ad:be:ef:00:01")]
    devices = _merge_devices(leases_data=[], arp_data=arp)
    assert len(devices) == 1


# ── fetch_opnsense_devices error contract ────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_returns_error_when_host_missing():
    devices, err = await fetch_opnsense_devices({"opnsense_host": ""})
    assert devices == []
    assert err is not None
    assert "host not configured" in err


@pytest.mark.asyncio
async def test_fetch_returns_error_when_creds_missing():
    devices, err = await fetch_opnsense_devices(
        {
            "opnsense_host": "192.168.1.1",
            "opnsense_api_key_enc": "",
            "opnsense_api_secret_enc": "",
        }
    )
    assert devices == []
    assert err is not None
    assert "credentials not configured" in err


@pytest.mark.asyncio
async def test_fetch_returns_error_on_connection_refused(respx_mock):
    """Mock connection refused → returns ([], 'OPNsense: connection refused ...')"""
    from unittest.mock import MagicMock, patch

    import httpx

    # ARP endpoint (GET snake_case) raises ConnectError
    respx_mock.get("https://192.168.1.1/api/kea/leases4/search").mock(
        return_value=httpx.Response(404)
    )
    respx_mock.get("https://192.168.1.1/api/dhcpv4/leases/search_lease").mock(
        return_value=httpx.Response(404)
    )
    respx_mock.get("https://192.168.1.1/api/diagnostics/interface/get_arp").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    mock_vault = MagicMock()
    mock_vault.decrypt.side_effect = lambda x: "plaintext"

    with patch("app.services.credential_vault.get_vault", return_value=mock_vault):
        devices, err = await fetch_opnsense_devices(
            {
                "opnsense_host": "192.168.1.1",
                "opnsense_api_key_enc": "fake_enc",
                "opnsense_api_secret_enc": "fake_enc",
                "opnsense_verify_ssl": False,
            }
        )

    assert devices == []
    assert err is not None
    assert "connection refused" in err.lower()


@pytest.mark.asyncio
async def test_fetch_returns_error_on_arp_401(respx_mock):
    """ARP 401 Unauthorized → returns ([], 'OPNsense: unauthorized ...')"""
    from unittest.mock import MagicMock, patch

    import httpx

    respx_mock.get("https://192.168.1.1/api/kea/leases4/search").mock(
        return_value=httpx.Response(404)
    )
    respx_mock.get("https://192.168.1.1/api/dhcpv4/leases/search_lease").mock(
        return_value=httpx.Response(404)
    )
    respx_mock.get("https://192.168.1.1/api/diagnostics/interface/get_arp").mock(
        return_value=httpx.Response(401)
    )

    mock_vault = MagicMock()
    mock_vault.decrypt.side_effect = lambda x: "plaintext"

    with patch("app.services.credential_vault.get_vault", return_value=mock_vault):
        devices, err = await fetch_opnsense_devices(
            {
                "opnsense_host": "192.168.1.1",
                "opnsense_api_key_enc": "fake_enc",
                "opnsense_api_secret_enc": "fake_enc",
            }
        )

    assert devices == []
    assert err is not None
    assert "unauthorized" in err.lower()


@pytest.mark.asyncio
async def test_fetch_returns_error_on_arp_403(respx_mock):
    """ARP 403 Forbidden → hard error with privilege hint."""
    from unittest.mock import MagicMock, patch

    import httpx

    respx_mock.get("https://192.168.1.1/api/kea/leases4/search").mock(
        return_value=httpx.Response(404)
    )
    respx_mock.get("https://192.168.1.1/api/dhcpv4/leases/search_lease").mock(
        return_value=httpx.Response(404)
    )
    respx_mock.get("https://192.168.1.1/api/diagnostics/interface/get_arp").mock(
        return_value=httpx.Response(403)
    )

    mock_vault = MagicMock()
    mock_vault.decrypt.side_effect = lambda x: "plaintext"

    with patch("app.services.credential_vault.get_vault", return_value=mock_vault):
        devices, err = await fetch_opnsense_devices(
            {
                "opnsense_host": "192.168.1.1",
                "opnsense_api_key_enc": "fake_enc",
                "opnsense_api_secret_enc": "fake_enc",
            }
        )

    assert devices == []
    assert err is not None
    assert "403" in err or "forbidden" in err.lower()


@pytest.mark.asyncio
async def test_fetch_returns_error_on_arp_404(respx_mock):
    """ARP 404 → hard error (wrong URL or missing module)."""
    from unittest.mock import MagicMock, patch

    import httpx

    respx_mock.get("https://192.168.1.1/api/kea/leases4/search").mock(
        return_value=httpx.Response(404)
    )
    respx_mock.get("https://192.168.1.1/api/dhcpv4/leases/search_lease").mock(
        return_value=httpx.Response(404)
    )
    respx_mock.get("https://192.168.1.1/api/diagnostics/interface/get_arp").mock(
        return_value=httpx.Response(404)
    )

    mock_vault = MagicMock()
    mock_vault.decrypt.side_effect = lambda x: "plaintext"

    with patch("app.services.credential_vault.get_vault", return_value=mock_vault):
        devices, err = await fetch_opnsense_devices(
            {
                "opnsense_host": "192.168.1.1",
                "opnsense_api_key_enc": "fake_enc",
                "opnsense_api_secret_enc": "fake_enc",
            }
        )

    assert devices == []
    assert err is not None
    assert "404" in err or "not found" in err.lower()


@pytest.mark.asyncio
async def test_fetch_success_kea_leases(respx_mock):
    """Happy path — Kea leases + ARP merged, no error."""
    from unittest.mock import MagicMock, patch

    import httpx

    lease_payload = {
        "rows": [
            {"address": "10.0.0.1", "mac": "aa:bb:cc:00:00:01", "hostname": "router", "ends": ""},
            {"address": "10.0.0.2", "mac": "aa:bb:cc:00:00:02", "hostname": "nas", "ends": ""},
        ]
    }
    arp_payload = [
        {"ip": "10.0.0.1", "mac": "aa:bb:cc:00:00:01"},
        {"ip": "10.0.0.3", "mac": "aa:bb:cc:00:00:03"},  # ARP-only
    ]

    # Kea leases succeed on first attempt
    respx_mock.get("https://10.0.0.254/api/kea/leases4/search").mock(
        return_value=httpx.Response(200, json=lease_payload)
    )
    # ARP snake_case GET endpoint
    respx_mock.get("https://10.0.0.254/api/diagnostics/interface/get_arp").mock(
        return_value=httpx.Response(200, json=arp_payload)
    )

    mock_vault = MagicMock()
    mock_vault.decrypt.side_effect = lambda x: "key"

    with patch("app.services.credential_vault.get_vault", return_value=mock_vault):
        devices, err = await fetch_opnsense_devices(
            {
                "opnsense_host": "10.0.0.254",
                "opnsense_api_key_enc": "enc_key",
                "opnsense_api_secret_enc": "enc_secret",
            }
        )

    assert err is None
    by_ip = {d["ip"]: d for d in devices}
    assert len(by_ip) == 3
    assert by_ip["10.0.0.1"]["is_active"] is True
    assert by_ip["10.0.0.1"]["hostname"] == "router"
    assert by_ip["10.0.0.2"]["is_active"] is False  # lease-only
    assert by_ip["10.0.0.3"]["is_active"] is True  # ARP-only
    assert by_ip["10.0.0.3"]["hostname"] is None


@pytest.mark.asyncio
async def test_fetch_success_isc_leases_fallback(respx_mock):
    """Kea 404 → falls back to ISC DHCP endpoint."""
    from unittest.mock import MagicMock, patch

    import httpx

    lease_payload = {
        "rows": [
            {"address": "10.0.0.10", "mac": "bb:cc:dd:00:00:01", "hostname": "switch", "ends": ""},
        ]
    }
    arp_payload = [{"ip": "10.0.0.10", "mac": "bb:cc:dd:00:00:01"}]

    respx_mock.get("https://10.0.0.1/api/kea/leases4/search").mock(return_value=httpx.Response(404))
    respx_mock.get("https://10.0.0.1/api/dhcpv4/leases/search_lease").mock(
        return_value=httpx.Response(200, json=lease_payload)
    )
    respx_mock.get("https://10.0.0.1/api/diagnostics/interface/get_arp").mock(
        return_value=httpx.Response(200, json=arp_payload)
    )

    mock_vault = MagicMock()
    mock_vault.decrypt.side_effect = lambda x: "key"

    with patch("app.services.credential_vault.get_vault", return_value=mock_vault):
        devices, err = await fetch_opnsense_devices(
            {
                "opnsense_host": "10.0.0.1",
                "opnsense_api_key_enc": "enc_key",
                "opnsense_api_secret_enc": "enc_secret",
            }
        )

    assert err is None
    by_ip = {d["ip"]: d for d in devices}
    assert by_ip["10.0.0.10"]["hostname"] == "switch"
    assert by_ip["10.0.0.10"]["is_active"] is True
