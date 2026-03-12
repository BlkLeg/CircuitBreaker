"""Proxmox VE API client wrapper.

Wraps ``proxmoxer`` (synchronous) with async-safe methods via
``asyncio.to_thread`` so the FastAPI event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import urllib3

from app.core.retry import run_sync_with_retry

urllib3.disable_warnings()

_logger = logging.getLogger(__name__)

# Limit concurrent API calls per host so we never exceed the underlying
# requests.Session pool (default 10). Proxmoxer does not expose a larger pool.
PROXMOX_MAX_CONCURRENT = 8


class ProxmoxIntegration:
    """Thin async wrapper around the proxmoxer ProxmoxAPI.
    Uses a semaphore to cap concurrent requests per host and avoid
    urllib3 'Connection pool is full' errors."""

    def __init__(
        self,
        host: str,
        user: str,
        token_name: str,
        token_value: str,
        verify_ssl: bool = False,
        client_cert: str | None = None,
        client_key: str | None = None,
    ) -> None:
        from proxmoxer import ProxmoxAPI

        self.host = host

        kwargs: dict[str, Any] = {
            "user": user,
            "token_name": token_name,
            "token_value": token_value,
            "verify_ssl": verify_ssl,
            "timeout": 15,
        }

        if client_cert and client_key:
            import requests

            session = requests.Session()
            session.cert = (client_cert, client_key)
            if not verify_ssl:
                session.verify = False
            kwargs["session"] = session

        self._px = ProxmoxAPI(host, **kwargs)
        self._semaphore = asyncio.Semaphore(PROXMOX_MAX_CONCURRENT)

    # ── helpers ────────────────────────────────────────────────────────────

    def _get(self, path: str) -> Any:
        """Synchronous GET — always call via ``asyncio.to_thread``."""
        return self._px.get(path)

    def _post(self, path: str, **kwargs: Any) -> Any:
        return self._px.post(path, **kwargs)

    # ── public async API ──────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        """Return PVE version and cluster name."""

        def _sync() -> dict:
            version_info = self._px.get("version")
            try:
                cluster_status = self._px.get("cluster/status")
                cluster_name = next(
                    (
                        item.get("name", "unknown")
                        for item in cluster_status
                        if item.get("type") == "cluster"
                    ),
                    None,
                )
            except Exception as exc:
                _logger.warning("Could not fetch cluster/status (standalone node?): %s", exc)
                cluster_name = None
            return {
                "version": version_info.get("version", "unknown"),
                "release": version_info.get("release", ""),
                "cluster_name": cluster_name,
            }

        async with self._semaphore:
            return await run_sync_with_retry(_sync, log_context="Proxmox")

    async def discover_cluster(self) -> dict:
        """Fetch full cluster resource inventory."""

        def _sync() -> dict:
            resources = self._px.get("cluster/resources")
            try:
                cluster_status = self._px.get("cluster/status")
            except Exception as exc:
                _logger.warning("Could not fetch cluster/status during discovery: %s", exc)
                cluster_status = []
            return {"cluster_status": cluster_status, "resources": resources}

        async with self._semaphore:
            return await run_sync_with_retry(_sync, log_context="Proxmox")

    async def get_cluster_status(self) -> list[dict]:
        """Return cluster/status list (quorate, nodes, name, master per node/cluster).
        PVEAuditor can read this; used for cluster overview dashboard."""

        def _sync() -> list:
            return self._px.get("cluster/status")

        async with self._semaphore:
            return await run_sync_with_retry(_sync, log_context="Proxmox")

    async def get_node_status(self, node: str) -> dict:
        def _sync() -> dict:
            return self._px.get(f"nodes/{node}/status")

        async with self._semaphore:
            return await run_sync_with_retry(_sync, log_context="Proxmox")

    async def get_vm_config(self, node: str, vmid: int, vm_type: str = "qemu") -> dict:
        def _sync() -> dict:
            return self._px.get(f"nodes/{node}/{vm_type}/{vmid}/config")

        async with self._semaphore:
            return await run_sync_with_retry(_sync, log_context="Proxmox")

    async def get_vm_status(self, node: str, vmid: int, vm_type: str = "qemu") -> dict:
        def _sync() -> dict:
            return self._px.get(f"nodes/{node}/{vm_type}/{vmid}/status/current")

        async with self._semaphore:
            return await run_sync_with_retry(_sync, log_context="Proxmox")

    async def get_permissions(self) -> dict:
        """Return the effective permissions for the current token."""

        def _sync() -> dict:
            return self._px.get("access/permissions")

        async with self._semaphore:
            return await run_sync_with_retry(_sync, log_context="Proxmox")

    async def get_node_vms(self, node: str, vm_type: str = "qemu") -> list[dict]:
        """List VMs or LXCs on a specific node (fallback for limited tokens)."""

        def _sync() -> list[dict]:
            return self._px.get(f"nodes/{node}/{vm_type}")

        async with self._semaphore:
            return await run_sync_with_retry(_sync, log_context="Proxmox")

    async def get_node_storage(self, node: str) -> list[dict]:
        """List storage pools on a specific node."""

        def _sync() -> list[dict]:
            return self._px.get(f"nodes/{node}/storage")

        async with self._semaphore:
            return await run_sync_with_retry(_sync, log_context="Proxmox")

    async def get_node_networks(self, node: str) -> list[dict]:
        def _sync() -> list[dict]:
            return self._px.get(f"nodes/{node}/network")

        async with self._semaphore:
            return await run_sync_with_retry(_sync, log_context="Proxmox")

    async def get_node_rrddata(self, node: str, timeframe: str = "hour") -> list[dict]:
        def _sync() -> list[dict]:
            return self._px.get(f"nodes/{node}/rrddata", timeframe=timeframe)

        async with self._semaphore:
            return await run_sync_with_retry(_sync, log_context="Proxmox")

    # ── VM/CT actions ─────────────────────────────────────────────────────

    async def vm_action(self, node: str, vmid: int, vm_type: str, action: str) -> str:
        """Execute a VM/CT lifecycle action. Returns the UPID task string."""

        def _sync() -> str:
            return self._px.post(f"nodes/{node}/{vm_type}/{vmid}/status/{action}")

        async with self._semaphore:
            return await run_sync_with_retry(_sync, log_context="Proxmox")


def build_client_from_token(
    url: str,
    api_token: str,
    verify_ssl: bool = False,
    client_cert: str | None = None,
    client_key: str | None = None,
) -> ProxmoxIntegration:
    """Parse a PVE API token string and build a client.

    Token format: ``user@realm!tokenname=secret-value``
    """
    host = url.replace("https://", "").replace("http://", "").rstrip("/")

    if "!" not in api_token or "=" not in api_token:
        raise ValueError("Invalid Proxmox API token format. Expected: user@realm!tokenname=secret")

    user_and_token, token_value = api_token.split("=", 1)
    user, token_name = user_and_token.split("!", 1)

    return ProxmoxIntegration(
        host=host,
        user=user,
        token_name=token_name,
        token_value=token_value,
        verify_ssl=verify_ssl,
        client_cert=client_cert,
        client_key=client_key,
    )
