import subprocess

from app.core.validation import validate_snmp_community

IDRAC_SNMP_OIDS = {
    "cpu_temp": "1.3.6.1.4.1.674.10892.5.4.700.20.1.8.1.1",
    "psu1_status": "1.3.6.1.4.1.674.10892.5.4.600.12.1.5.1.1",
    "psu2_status": "1.3.6.1.4.1.674.10892.5.4.600.12.1.5.1.2",
    "fan_rpm": "1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.1",
    "memory_ecc": "1.3.6.1.4.1.674.10892.5.4.1100.50.1.6.1.1",
    "system_power_w": "1.3.6.1.4.1.674.10892.5.4.600.30.1.8.1.1",
}


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


class IDRACClient:
    def __init__(self, host: str, community: str = "public", version: str = "v2c"):
        self.host = host
        self.community = community

    def poll(self) -> dict:
        results = {}
        for key, oid in IDRAC_SNMP_OIDS.items():
            val = _snmp_get_one(self.host, self.community, oid)
            if val is not None:
                try:
                    results[key] = float(val)
                except (TypeError, ValueError):
                    results[key] = val  # type: ignore[assignment]

        return self._normalize(results)

    def _normalize(self, raw: dict) -> dict:
        return {
            "cpu_temp": raw.get("cpu_temp"),
            "psu1_load_w": raw.get("psu1_status"),
            "psu2_load_w": raw.get("psu2_status"),
            "fan_rpm": raw.get("fan_rpm"),
            "system_power_w": raw.get("system_power_w"),
        }

    def get_status(self, data: dict) -> str:
        if data.get("cpu_temp") and data["cpu_temp"] > 80:
            return "critical"
        if data.get("cpu_temp") and data["cpu_temp"] > 70:
            return "degraded"
        return "healthy"
