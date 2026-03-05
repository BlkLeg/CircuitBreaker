from app.integrations.apc_ups import APCUPSClient
from app.integrations.idrac import IDRACClient
from app.integrations.ilo import ILOClient
from app.integrations.snmp_generic import SNMPGenericClient
from app.services.credential_vault import CredentialVault

PROFILE_MAP = {
    "idrac6":        IDRACClient,
    "idrac7":        IDRACClient,
    "idrac8":        IDRACClient,
    "idrac9":        IDRACClient,
    "ilo4":          ILOClient,
    "ilo5":          ILOClient,
    "ilo6":          ILOClient,
    "apc_ups":       APCUPSClient,
    "cyberpower_ups": APCUPSClient,   # CyberPower uses same SNMP MIB structure as APC
    "snmp_generic":  SNMPGenericClient,
    "ipmi_generic":  SNMPGenericClient,  # Generic IPMI fallback (Supermicro, etc.)
}


def poll_hardware(hardware, vault: CredentialVault) -> dict:
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

    host = config["host"]
    password = vault.decrypt(config["password"]) if config.get("password") else None

    try:
        if profile in ("ilo4", "ilo5", "ilo6"):
            client = ClientClass(host, config.get("username"), password)
        elif profile in ("apc_ups", "cyberpower_ups"):
            client = ClientClass(host, config.get("snmp_community", "public"))
        elif profile in ("snmp_generic", "ipmi_generic"):
            client = ClientClass(host, config.get("snmp_community", "public"), config.get("custom_oids", {}))
        else:
            client = ClientClass(host, config.get("snmp_community", "public"))

        data = client.poll()
        status = client.get_status(data)
        return {"data": data, "status": status}

    except Exception as e:
        return {"error": str(e), "status": "unknown"}
