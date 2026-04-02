import asyncio
from unittest.mock import MagicMock, patch

import pytest


def test_arp_scan_rejects_oversized_subnet() -> None:
    from app.services.discovery_probes import _run_arp_scan

    with pytest.raises(ValueError, match="too large"):
        asyncio.run(_run_arp_scan("10.0.0.0/7"))


def test_arp_scan_accepts_16_subnet() -> None:
    from app.services.discovery_probes import _ARP_CAPABLE, _run_arp_scan

    if not _ARP_CAPABLE:
        pytest.skip("scapy not available")
    with patch("app.services.discovery_probes.srp", return_value=([], [])):
        result = asyncio.run(_run_arp_scan("192.168.0.0/16"))
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_host_discovery_sweep_returns_set_on_success() -> None:
    from app.services.discovery_probes import _run_host_discovery_sweep

    mock_nm: MagicMock = MagicMock()
    mock_nm.all_hosts.return_value = ["192.168.1.1", "192.168.1.5"]

    def mock_getitem(self: MagicMock, host: str) -> MagicMock:
        m = MagicMock()
        m.state.return_value = "up"
        return m

    mock_nm.__class__.__getitem__ = mock_getitem

    with patch("nmap.PortScanner", return_value=mock_nm):
        result = await _run_host_discovery_sweep("192.168.1.0/24")
    assert isinstance(result, set)


@pytest.mark.asyncio
async def test_host_discovery_sweep_returns_empty_on_nmap_failure() -> None:
    from app.services.discovery_probes import _run_host_discovery_sweep

    with patch("nmap.PortScanner", side_effect=Exception("nmap not found")):
        result = await _run_host_discovery_sweep("192.168.1.0/24")
    assert result == set()


@pytest.mark.asyncio
async def test_router_arp_table_returns_list_on_empty_walk() -> None:
    """_run_router_arp_table returns [] when SNMP yields nothing."""
    from unittest.mock import AsyncMock, MagicMock

    from app.services.discovery_probes import _run_router_arp_table

    with (
        patch("app.services.discovery_probes.UdpTransportTarget") as mt,
        patch("pysnmp.hlapi.v3arch.asyncio.cmdgen.next_cmd") as mnc,
    ):
        mt.create = AsyncMock(return_value=MagicMock())

        async def empty_iter(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            return
            yield  # make it an async generator

        mnc.side_effect = empty_iter
        result = await _run_router_arp_table("192.168.1.1", "public")

    assert result == []


@pytest.mark.asyncio
async def test_lldp_probe_returns_list_on_empty_switch() -> None:
    """_run_lldp_probe returns [] when SNMP yields nothing."""
    from unittest.mock import AsyncMock, MagicMock

    from app.services.discovery_probes import _run_lldp_probe

    with (
        patch("app.services.discovery_probes.UdpTransportTarget") as mt,
        patch("pysnmp.hlapi.v3arch.asyncio.cmdgen.next_cmd") as mnc,
    ):
        mt.create = AsyncMock(return_value=MagicMock())

        async def empty_iter(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            return
            yield

        mnc.side_effect = empty_iter
        result = await _run_lldp_probe("192.168.1.1", "public")

    assert result == []
