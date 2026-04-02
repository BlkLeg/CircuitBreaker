from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_ssh_fallback_returns_empty_when_sshpass_missing() -> None:
    """Subprocess fallback returns [] when sshpass is not in PATH."""
    from app.services.discovery_dhcp import _run_router_ssh_dhcp

    # Mock the vault so credential decryption succeeds (local import inside function)
    mock_vault = MagicMock()
    mock_vault.decrypt.side_effect = lambda x: x  # identity — returns input as-is

    with patch("app.services.credential_vault.get_vault", return_value=mock_vault):
        # Make asyncssh unavailable by raising ImportError on connect
        with patch.dict("sys.modules", {"asyncssh": None}):
            # sshpass not available — subprocess fallback bails out
            with patch("shutil.which", return_value=None):
                result = await _run_router_ssh_dhcp(
                    "192.168.1.1", "admin", "secret", "cat /var/lib/misc/dnsmasq.leases"
                )

    assert result == []


@pytest.mark.asyncio
async def test_ssh_fallback_uses_sshpass_env() -> None:
    """When sshpass is present, subprocess is called with SSHPASS set in env."""
    from app.services.discovery_dhcp import _run_router_ssh_dhcp

    mock_vault = MagicMock()
    mock_vault.decrypt.side_effect = lambda x: x

    captured: dict = {"args": [], "env": {}}

    # Fake process that returns empty stdout
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    async def fake_create_subprocess(*args, **kwargs):
        captured["args"] = list(args)
        captured["env"] = dict(kwargs.get("env", {}))
        return mock_proc

    async def fake_wait_for(coro, _timeout):
        # coro is the coroutine from create_subprocess_exec; await it
        return await coro

    with patch("app.services.credential_vault.get_vault", return_value=mock_vault):
        with patch.dict("sys.modules", {"asyncssh": None}):
            with patch("shutil.which", return_value="/usr/bin/sshpass"):
                with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
                    with patch("asyncio.wait_for", side_effect=fake_wait_for):
                        result = await _run_router_ssh_dhcp(
                            "192.168.1.1", "admin", "secret", "cat /var/lib/misc/dnsmasq.leases"
                        )

    # Empty output → empty result, no exception
    assert result == []
    # First arg to create_subprocess_exec must be "sshpass"
    assert captured["args"][0] == "sshpass"
    assert captured["args"][1] == "-e"
    assert captured["args"][2] == "ssh"
    # SSHPASS must be in env
    assert "SSHPASS" in captured["env"]
    assert captured["env"]["SSHPASS"] == "secret"
