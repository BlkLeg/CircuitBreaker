"""Tests for Proxmox permission probing."""

from __future__ import annotations

import pytest

from app.services.proxmox_client import _check_token_privsep


class _DummyClient:
    def __init__(self, permissions: dict | None) -> None:
        self._permissions = permissions

    async def get_permissions(self) -> dict | None:
        return self._permissions


class _ErrorClient:
    async def get_permissions(self) -> dict:
        raise RuntimeError("403 Forbidden")


pytestmark = pytest.mark.asyncio


async def test_check_token_privsep_accepts_permission_map() -> None:
    client = _DummyClient({"/": {"Sys.Audit": True, "VM.Audit": True}})

    assert await _check_token_privsep(client) is None


async def test_check_token_privsep_reports_missing_vm_audit() -> None:
    client = _DummyClient({"/": {"Sys.Audit": True}})

    hint = await _check_token_privsep(client)

    assert hint is not None
    assert "VM.Audit" in hint
    assert "Sys.Audit" not in hint


async def test_check_token_privsep_hint_covers_both_privsep_states() -> None:
    client = _DummyClient({})

    hint = await _check_token_privsep(client)

    assert hint is not None
    assert "User Permission" in hint
    assert "API Token Permission" in hint


async def test_check_token_privsep_skips_inconclusive_probe_errors() -> None:
    client = _ErrorClient()

    assert await _check_token_privsep(client) is None
