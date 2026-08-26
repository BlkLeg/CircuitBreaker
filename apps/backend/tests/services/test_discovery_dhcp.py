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


def _sshpass_capture():
    """Patch set that runs the sshpass fallback and records the argv it spawned.

    Returns (captured, contextmanagers) — the caller enters the context managers
    and reads captured["args"] afterwards.  `captured["spawned"]` stays False if
    the fallback bailed out before reaching create_subprocess_exec, which is how
    the rejection tests tell "refused" apart from "ran with a safe argv".
    """
    captured: dict = {"args": [], "env": {}, "spawned": False}

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    async def fake_create_subprocess(*args, **kwargs):
        captured["args"] = list(args)
        captured["env"] = dict(kwargs.get("env", {}))
        captured["spawned"] = True
        return mock_proc

    return captured, fake_create_subprocess


@pytest.mark.asyncio
async def test_sshpass_argv_terminates_option_parsing_before_the_destination() -> None:
    """A bare "--" must sit immediately before user@host in the sshpass argv.

    Without it, ssh parses the destination token as an option whenever the
    stored router username starts with a dash, which turns a settings write
    into local command execution via -oProxyCommand=.
    """
    from app.services.discovery_dhcp import _run_router_ssh_dhcp

    mock_vault = MagicMock()
    mock_vault.decrypt.side_effect = lambda x: x

    captured, fake_create_subprocess = _sshpass_capture()

    with patch("app.services.credential_vault.get_vault", return_value=mock_vault):
        with patch.dict("sys.modules", {"asyncssh": None}):
            with patch("shutil.which", return_value="/usr/bin/sshpass"):
                with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
                    await _run_router_ssh_dhcp(
                        "192.168.1.1", "admin", "secret", "cat /var/lib/misc/dnsmasq.leases"
                    )

    assert captured["spawned"] is True
    destination_index = captured["args"].index("admin@192.168.1.1")
    assert captured["args"][destination_index - 1] == "--"


@pytest.mark.asyncio
async def test_router_username_shaped_like_an_ssh_option_never_reaches_sshpass() -> None:
    """A stored username of "-oProxyCommand=..." must be refused, not executed.

    The "--" above already stops ssh reading it as an option, but the username
    is also handed straight to asyncssh on the preferred path, so the value is
    rejected outright — the same "log a warning and return []" treatment the
    router command gets when it fails _validate_router_command.
    """
    from app.services.discovery_dhcp import _run_router_ssh_dhcp

    mock_vault = MagicMock()
    mock_vault.decrypt.side_effect = lambda x: x

    captured, fake_create_subprocess = _sshpass_capture()

    with patch("app.services.credential_vault.get_vault", return_value=mock_vault):
        with patch.dict("sys.modules", {"asyncssh": None}):
            with patch("shutil.which", return_value="/usr/bin/sshpass"):
                with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
                    result = await _run_router_ssh_dhcp(
                        "192.168.1.1",
                        "-oProxyCommand=touch /tmp/pwned",  # noqa: S108 — payload, not a real path
                        "secret",
                        "cat /var/lib/misc/dnsmasq.leases",
                    )

    assert result == []
    assert captured["spawned"] is False


def test_router_usernames_that_routers_actually_use_are_accepted() -> None:
    """The username validator must not break ordinary router logins."""
    from app.services.discovery_dhcp import _validate_router_username

    for username in ("admin", "root", "ubnt", "net_admin", "svc.discovery", "admin@lab.local"):
        _validate_router_username(username)


def test_settings_update_rejects_a_router_username_shaped_like_an_ssh_option() -> None:
    """Storing the payload at all is refused, so the operator sees the error.

    Catching it only at discovery time would encrypt the value, report success
    to the settings page, and then fail silently on every sweep afterwards.
    """
    from fastapi import HTTPException

    from app.schemas.settings import AppSettingsUpdate
    from app.services.settings_service import update_settings

    db = MagicMock()
    payload = AppSettingsUpdate(dhcp_router_username="-oProxyCommand=touch /tmp/pwned")  # noqa: S108

    with pytest.raises(HTTPException) as exc_info:
        update_settings(db, payload)

    assert exc_info.value.status_code == 422
    db.commit.assert_not_called()
