"""REL-08 / REL-07 — the sshpass DHCP fallback's failure paths.

The un-awaited-coroutine warning the RC run carried was created at
`discovery_dhcp._run_router_ssh_dhcp`'s `wait_for(proc.communicate(), ...)`:
`wait_for`'s first argument is built before the call, so anything that goes
wrong reaching the await abandons that coroutine. Replacing it with
`async with asyncio.timeout(...)` removes the object nothing owns — and, in
doing so, exposed two things the surrounding `except Exception` had been
hiding: a timed-out ssh child was never killed, and a failure to spawn
`sshpass` at all was reported at DEBUG.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest


class _HangingProc:
    """An ssh child that never answers, and remembers whether it was killed."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.killed = False

    async def communicate(self):
        await asyncio.sleep(60)
        raise AssertionError("communicate() should have been cut short by the deadline")

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        return -9


class _AnsweringProc:
    def __init__(self, stdout: bytes) -> None:
        self.returncode = 0
        self._stdout = stdout
        self.killed = False

    async def communicate(self):
        return (self._stdout, b"")

    def kill(self) -> None:  # pragma: no cover - must not be reached
        self.killed = True

    async def wait(self) -> int:  # pragma: no cover
        return 0


def _vault_passthrough():
    vault = MagicMock()
    vault.decrypt.side_effect = lambda value: value
    return vault


def _spawn(proc):
    async def _create(*_args, **_kwargs):
        return proc

    return _create


async def test_a_timed_out_ssh_child_is_killed_and_reaped():
    """`asyncio.timeout` cancels the await, not the process. Without an explicit
    kill the sshpass/ssh child survives every unresponsive router, once per
    scheduled DHCP sweep, for the life of the API process."""
    from app.services.discovery_dhcp import _run_router_ssh_dhcp

    proc = _HangingProc()
    with (
        patch("app.services.credential_vault.get_vault", return_value=_vault_passthrough()),
        patch.dict("sys.modules", {"asyncssh": None}),
        patch("shutil.which", return_value="/usr/bin/sshpass"),
        patch("asyncio.create_subprocess_exec", side_effect=_spawn(proc)),
    ):
        result = await _run_router_ssh_dhcp(
            "192.168.1.1", "admin", "secret", "cat /tmp/dhcp.leases", timeout=0.05
        )

    assert result == []
    assert proc.killed, "the timed-out ssh child was left running"


async def test_a_spawn_failure_is_reported_at_warning(caplog):
    """`sshpass` present in PATH but unusable used to be a DEBUG line, so a
    permission or exec failure on every router looked like "no leases"."""
    from app.services.discovery_dhcp import _run_router_ssh_dhcp

    async def _fail(*_args, **_kwargs):
        raise PermissionError("exec format error")

    with (
        patch("app.services.credential_vault.get_vault", return_value=_vault_passthrough()),
        patch.dict("sys.modules", {"asyncssh": None}),
        patch("shutil.which", return_value="/usr/bin/sshpass"),
        patch("asyncio.create_subprocess_exec", side_effect=_fail),
        caplog.at_level(logging.DEBUG, logger="app.services.discovery_dhcp"),
    ):
        result = await _run_router_ssh_dhcp(
            "192.168.1.1", "admin", "secret", "cat /tmp/dhcp.leases", timeout=1
        )

    assert result == []
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "a router whose ssh could not be spawned produced no warning"
    assert "could not start sshpass" in warnings[-1].getMessage()


@pytest.mark.filterwarnings("error::RuntimeWarning")
async def test_the_subprocess_fallback_parses_leases_without_abandoning_a_coroutine():
    """The success path, driven end to end with RuntimeWarning fatal: no
    coroutine may be created and left unawaited anywhere along it."""
    from app.services.discovery_dhcp import _run_router_ssh_dhcp

    leases = b"1699999999 aa:bb:cc:dd:ee:ff 192.168.1.50 printer *\n"
    proc = _AnsweringProc(leases)
    with (
        patch("app.services.credential_vault.get_vault", return_value=_vault_passthrough()),
        patch.dict("sys.modules", {"asyncssh": None}),
        patch("shutil.which", return_value="/usr/bin/sshpass"),
        patch("asyncio.create_subprocess_exec", side_effect=_spawn(proc)),
    ):
        result = await _run_router_ssh_dhcp(
            "192.168.1.1", "admin", "secret", "cat /tmp/dhcp.leases", timeout=1
        )

    assert result == [{"mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.1.50", "hostname": "printer"}]
    assert not proc.killed
