import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.discovery_probes import _run_lldp_probe


@pytest.mark.asyncio
async def test_lldp_probe_returns_empty_on_snmp_failure():
    with patch("app.services.discovery_probes.UdpTransportTarget") as mock_transport:
        mock_transport.create = AsyncMock(side_effect=Exception("timeout"))
        result = await _run_lldp_probe("192.168.1.1", "public")
    assert result == []


@pytest.mark.asyncio
async def test_lldp_probe_parses_neighbor_row():
    """Verify the function parses a well-formed lldpRemTable row into the expected dict shape."""
    from app.services.discovery_probes import _parse_lldp_neighbor_row
    row = {
        "lldpRemChassisId": "aa:bb:cc:dd:ee:ff",
        "lldpRemPortId": "Gi0/0",
        "lldpRemPortDescr": "GigabitEthernet0/0",
        "lldpRemSysName": "router-01",
        "lldpRemManAddr": "192.168.1.1",
        "lldpLocPortDescr": "GigabitEthernet0/1",
        "capabilities": ["bridge"],
    }
    parsed = _parse_lldp_neighbor_row(row)
    assert parsed["remote_chassis_id"] == "aa:bb:cc:dd:ee:ff"
    assert parsed["remote_sys_name"] == "router-01"
    assert parsed["remote_mgmt_ip"] == "192.168.1.1"
    assert parsed["local_port_desc"] == "GigabitEthernet0/1"
    assert "bridge" in parsed["capabilities"]
