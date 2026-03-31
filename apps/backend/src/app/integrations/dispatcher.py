import asyncio
import logging
from typing import Any

from app.integrations.apc_ups import APCUPSClient
from app.integrations.idrac import IDRACClient
from app.integrations.ilo import ILOClient
from app.integrations.snmp_generic import SNMPGenericClient
from app.integrations.snmp_network_device import SNMPNetworkDeviceClient
from app.services.credential_vault import CredentialVault

_logger = logging.getLogger(__name__)

# Reuse ILO/IDRAC clients per (profile, host, username) to avoid connection pool exhaustion.
_HW_CLIENT_CACHE_MAX = 64
_hw_client_cache: dict[tuple[str, str, str], Any] = {}

PROFILE_MAP = {
    "idrac6": IDRACClient,
    "idrac7": IDRACClient,
    "idrac8": IDRACClient,
    "idrac9": IDRACClient,
    "ilo4": ILOClient,
    "ilo5": ILOClient,
    "ilo6": ILOClient,
    "apc_ups": APCUPSClient,
    "cyberpower_ups": APCUPSClient,  # CyberPower uses same SNMP MIB structure as APC
    "snmp_generic": SNMPGenericClient,
    "ipmi_generic": SNMPGenericClient,  # Generic IPMI fallback (Supermicro, etc.)
    "snmp_network_device": SNMPNetworkDeviceClient,
}


def poll_hardware(hardware: Any, vault: CredentialVault) -> dict:
    """
    Resolves the correct client for a hardware node's telemetry profile,
    executes a poll, and returns normalized data + status string.
    """
    import json

    config = hardware.telemetry_config
    if not config:
        return {}

    # config may be a JSON string (from DB) or a dict
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except (json.JSONDecodeError, TypeError):
            return {"error": "Invalid telemetry_config JSON", "status": "unknown"}

    if not config.get("enabled", True):
        return {}

    profile = config.get("profile")
    ClientClass = PROFILE_MAP.get(profile)
    if not ClientClass:
        return {"error": f"Unknown telemetry profile: {profile}", "status": "unknown"}

    host = config.get("host")
    if not host:
        return {"error": "No host configured", "status": "unknown"}
    password = vault.decrypt(config["password"]) if config.get("password") else None

    try:
        client: Any
        if profile in ("ilo4", "ilo5", "ilo6"):
            cache_key = (profile, host, config.get("username") or "")
            client = _hw_client_cache.get(cache_key)
            if client is None:
                client = ClientClass(host, config.get("username"), password)
                if len(_hw_client_cache) >= _HW_CLIENT_CACHE_MAX:
                    _hw_client_cache.clear()
                _hw_client_cache[cache_key] = client
        elif profile in ("apc_ups", "cyberpower_ups"):
            client = ClientClass(host, config.get("snmp_community", "public"))
        elif profile in ("snmp_generic", "ipmi_generic"):
            client = ClientClass(
                host, config.get("snmp_community", "public"), config.get("custom_oids", {})
            )
        elif profile == "snmp_network_device":
            client = SNMPNetworkDeviceClient(
                host=config.get("host") or hardware.ip_address,
                community=config.get("snmp_community") or "public",
                port=config.get("port") or 161,
            )
        else:
            client = ClientClass(host, config.get("snmp_community", "public"))

        data = client.poll()
        status = client.get_status(data)
        result = {"data": data, "status": status}

        _fire_and_forget_publish(hardware.id, result)
        return result

    except Exception as e:
        error_result = {"error": str(e), "status": "unknown"}
        _fire_and_forget_publish(hardware.id, error_result, ttl=30)
        return error_result


def _fire_and_forget_publish(hardware_id: int, result: dict, ttl: int | None = None) -> None:
    """Schedule async Redis cache+publish without blocking the sync caller."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _logger.debug("Skipping async telemetry publish — no running event loop")
        return
    loop.create_task(_async_cache_and_publish(hardware_id, result, ttl))


async def _async_cache_and_publish(hardware_id: int, result: dict, ttl: int | None = None) -> None:
    from app.services.telemetry_cache import cache_telemetry, publish_telemetry

    try:
        await cache_telemetry(hardware_id, result, ttl=ttl)
        await publish_telemetry(hardware_id, result)
    except Exception as exc:
        _logger.debug("Redis cache/publish after poll failed: %s", exc)
