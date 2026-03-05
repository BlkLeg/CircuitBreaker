import subprocess

APC_OIDS = {
    "battery_capacity":     "1.3.6.1.4.1.318.1.1.1.2.2.1.0",
    "battery_runtime_min":  "1.3.6.1.4.1.318.1.1.1.2.2.3.0",
    "load_percent":         "1.3.6.1.4.1.318.1.1.1.4.2.3.0",
    "input_voltage":        "1.3.6.1.4.1.318.1.1.1.3.2.1.0",
    "output_voltage":       "1.3.6.1.4.1.318.1.1.1.4.2.1.0",
    "battery_temp_c":       "1.3.6.1.4.1.318.1.1.1.2.2.2.0",
    "last_transfer_reason": "1.3.6.1.4.1.318.1.1.1.3.2.5.0",
    "self_test_result":     "1.3.6.1.4.1.318.1.1.1.7.2.3.0",
    "battery_status":       "1.3.6.1.4.1.318.1.1.1.2.1.1.0",
    "comm_status":          "1.3.6.1.4.1.318.1.1.1.8.1.0",
}


def _snmp_get_one(host: str, community: str, oid: str) -> str | None:
    try:
        r = subprocess.run(
            ["snmpget", "-v2c", "-c", community, "-Oqv", host, oid],
            capture_output=True, text=True, timeout=3,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


class APCUPSClient:
    def __init__(self, host: str, community: str = "public"):
        self.host = host
        self.community = community

    def poll(self) -> dict:
        results = {}
        for key, oid in APC_OIDS.items():
            val = _snmp_get_one(self.host, self.community, oid)
            if val is not None:
                try:
                    results[key] = int(val)
                except (TypeError, ValueError):
                    results[key] = val

        # Runtime OID returns tenths-of-seconds — convert to minutes
        if "battery_runtime_min" in results and isinstance(results["battery_runtime_min"], int):
            results["battery_runtime_min"] = results["battery_runtime_min"] // 100 // 60

        return results

    def get_status(self, data: dict) -> str:
        cap = data.get("battery_capacity", 100)
        load = data.get("load_percent", 0)
        if cap < 20 or load > 90:
            return "critical"
        if cap < 50 or load > 75:
            return "degraded"
        return "healthy"
