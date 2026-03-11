import subprocess

from app.core.validation import validate_snmp_community


def _snmp_get_one(host: str, community: str, oid: str) -> str | None:
    try:
        safe_community = validate_snmp_community(community)
        r = subprocess.run(
            ["snmpget", "-v2c", "-c", safe_community, "-Oqv", host, oid],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


class SNMPGenericClient:
    """
    Polls any SNMP device by arbitrary OIDs configured per-device.
    Used for MikroTik, Supermicro IPMI, unrecognized switches, etc.
    """

    def __init__(self, host: str, community: str = "public", oids: dict | None = None):
        self.host = host
        self.community = community
        self.oids = oids or {}

    def poll(self) -> dict:
        results = {}
        for key, oid in self.oids.items():
            val = _snmp_get_one(self.host, self.community, oid)
            if val is not None:
                results[key] = val
        return results

    def get_status(self, data: dict) -> str:
        if not data or "error" in data:
            return "unknown"
        return "healthy"
