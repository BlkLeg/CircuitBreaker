"""Proxmox client lifecycle, TLS helpers, and shared utilities."""

from __future__ import annotations

import asyncio
import json
import logging
import threading

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.models import Credential, IntegrationConfig
from app.integrations.proxmox_client import ProxmoxIntegration, build_client_from_token
from app.services.credential_vault import get_vault

_logger = logging.getLogger(__name__)

# Reuse one Proxmox client per integration to avoid urllib3 connection pool exhaustion
# (many clients to the same host each create a pool; one client per host reuses connections).
_proxmox_client_cache: dict[int, ProxmoxIntegration] = {}
_proxmox_client_cache_lock = threading.Lock()


def _invalidate_proxmox_client_cache(config_id: int) -> None:
    """Remove cached client when config is updated or deleted."""
    with _proxmox_client_cache_lock:
        _proxmox_client_cache.pop(config_id, None)


def _resolve_tls_cert(db: Session, config: IntegrationConfig) -> tuple[str | None, str | None]:
    """Return (cert_path, key_path) for mTLS if a certificate is attached, else (None, None).

    Writes ephemeral PEM files to /tmp so the requests library can use them.
    """
    cert_id = getattr(config, "tls_cert_id", None)
    if not cert_id:
        return None, None

    from app.db.models import Certificate

    cert_row = db.get(Certificate, cert_id)
    if not cert_row:
        return None, None

    import os
    import tempfile

    vault = get_vault()
    cert_pem = cert_row.cert_pem
    try:
        key_pem = vault.decrypt(cert_row.key_pem)
    except Exception:
        key_pem = cert_row.key_pem

    prefix = f"cb_mtls_{config.id}_"
    cert_path = os.path.join(tempfile.gettempdir(), f"{prefix}cert.pem")
    key_path = os.path.join(tempfile.gettempdir(), f"{prefix}key.pem")

    with open(cert_path, "w") as f:
        f.write(cert_pem)
    with open(key_path, "w") as f:
        f.write(key_pem)
    os.chmod(key_path, 0o600)

    return cert_path, key_path


def _get_client(db: Session, config: IntegrationConfig) -> ProxmoxIntegration:
    """Build or return cached ProxmoxIntegration for this integration.

    One client per config to avoid connection pool exhaustion.
    """
    config_id = config.id
    with _proxmox_client_cache_lock:
        if config_id in _proxmox_client_cache:
            return _proxmox_client_cache[config_id]
    vault = get_vault()
    cred = db.get(Credential, config.credential_id)
    if not cred:
        raise ValueError(f"Credential {config.credential_id} not found for integration {config.id}")

    try:
        token = vault.decrypt(cred.encrypted_value)
    except Exception as exc:
        raise ValueError(
            f"Cannot decrypt credentials for integration {config.id}. "
            "The vault key may have changed."
        ) from exc
    if isinstance(config.extra_config, str):
        extra = json.loads(config.extra_config) if config.extra_config else {}  # type: ignore[unreachable]
    else:
        extra = config.extra_config or {}
    verify_ssl = extra.get("verify_ssl", False)

    cert_path, key_path = _resolve_tls_cert(db, config)

    client = build_client_from_token(
        config.config_url,
        token,
        verify_ssl=verify_ssl,
        client_cert=cert_path,
        client_key=key_path,
    )
    with _proxmox_client_cache_lock:
        _proxmox_client_cache[config_id] = client
    return client


def _write_tls_files(cert_path: str, key_path: str, cert_pem: str, key_pem: str) -> None:
    """Write mTLS cert/key PEM files to disk (sync — call via asyncio.to_thread)."""
    import os

    with open(cert_path, "w") as f:
        f.write(cert_pem)
    with open(key_path, "w") as f:
        f.write(key_pem)
    os.chmod(key_path, 0o600)


async def _resolve_tls_cert_async(
    db: AsyncSession, config: IntegrationConfig
) -> tuple[str | None, str | None]:
    """Async variant of _resolve_tls_cert for use in polling coroutines."""
    cert_id = getattr(config, "tls_cert_id", None)
    if not cert_id:
        return None, None

    from app.db.models import Certificate

    cert_row = await db.get(Certificate, cert_id)
    if not cert_row:
        return None, None

    import tempfile

    vault = get_vault()
    cert_pem = cert_row.cert_pem
    try:
        key_pem = vault.decrypt(cert_row.key_pem)
    except Exception:
        key_pem = cert_row.key_pem

    import os

    prefix = f"cb_mtls_{config.id}_"
    cert_path = os.path.join(tempfile.gettempdir(), f"{prefix}cert.pem")
    key_path = os.path.join(tempfile.gettempdir(), f"{prefix}key.pem")

    await asyncio.to_thread(_write_tls_files, cert_path, key_path, cert_pem, key_pem)

    return cert_path, key_path


async def _get_client_async(db: AsyncSession, config: IntegrationConfig) -> ProxmoxIntegration:
    """Async variant of _get_client for use in polling coroutines.

    Uses AsyncSession for cache misses.
    """
    config_id = config.id
    with _proxmox_client_cache_lock:
        if config_id in _proxmox_client_cache:
            return _proxmox_client_cache[config_id]
    vault = get_vault()
    cred = await db.get(Credential, config.credential_id)
    if not cred:
        raise ValueError(f"Credential {config.credential_id} not found for integration {config.id}")

    try:
        token = vault.decrypt(cred.encrypted_value)
    except Exception as exc:
        raise ValueError(
            f"Cannot decrypt credentials for integration {config.id}. "
            "The vault key may have changed."
        ) from exc
    if isinstance(config.extra_config, str):
        extra = json.loads(config.extra_config) if config.extra_config else {}  # type: ignore[unreachable]
    else:
        extra = config.extra_config or {}
    verify_ssl = extra.get("verify_ssl", False)

    cert_path, key_path = await _resolve_tls_cert_async(db, config)

    client = build_client_from_token(
        config.config_url,
        token,
        verify_ssl=verify_ssl,
        client_cert=cert_path,
        client_key=key_path,
    )
    with _proxmox_client_cache_lock:
        _proxmox_client_cache[config_id] = client
    return client


async def _check_token_privsep(client: ProxmoxIntegration) -> str | None:
    """Detect Privilege Separation and return a targeted hint when actionable.

    Returns a warning only when token permissions appear insufficient.
    If the token already has VM.Audit, returning zero VMs/CTs can be legitimate
    (for example, an empty cluster), so no error is emitted.
    """
    try:
        perms = await client.get_permissions()
        has_vm_audit = any(
            "VM.Audit" in privs for privs in (perms.values() if isinstance(perms, dict) else [])
        )
    except Exception:
        has_vm_audit = False

    if not has_vm_audit:
        return (
            "0 VMs/containers returned — the API token likely has Privilege "
            "Separation enabled (the Proxmox default). When enabled, the token "
            "does NOT inherit the user's permissions and needs its own. Fix: "
            "Datacenter → Permissions → Add → API Token Permission, select "
            "your token, set Role = PVEAuditor, Path = /, Propagate = yes. "
            "Or, recreate the token with Privilege Separation unchecked."
        )
    return None


async def _publish(subject: str, payload: dict) -> None:
    from app.core.nats_client import nats_client

    try:
        await nats_client.publish(subject, payload)
    except Exception:
        _logger.debug("NATS publish to %s failed (non-critical)", subject, exc_info=True)


def _proxmox_error_message(e: Exception) -> str:
    """Return a user-facing error string. Maps known exception types to clear messages."""
    msg = str(e).strip()
    if type(e).__name__ == "InvalidToken":
        return (
            "Stored credential could not be decrypted. The vault key may have changed "
            "(e.g. after a reset or new deployment). Edit this integration and re-enter "
            "the Proxmox API token to save it with the current vault key."
        )
    return msg or f"{type(e).__name__} (no message)"
